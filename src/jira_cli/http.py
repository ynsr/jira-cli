"""HTTP helpers for Jira REST API, compatible with both Jira Server/Data Center
(API v2) and Jira Cloud (API v3).

The write-path API version (v2 vs v3) is auto-detected from
``GET /rest/api/2/serverInfo``'s ``deploymentType`` ("Cloud" => v3, otherwise
v2) and cached for the process lifetime. It can be forced with the
``JIRA_API_VERSION`` environment variable (``auto`` | ``2`` | ``3``).

Reads (GET/HEAD) and JQL searches always use API v2, which Jira Cloud still
serves and Jira Server/DC requires.

Field formats differ between the two APIs:
  - v2 (Server/DC): ``description`` and comment bodies are plain wiki-markup
    strings.
  - v3 (Cloud): ``description`` and comment bodies must be Atlassian Document
    Format (ADF) documents.

Use :func:`ensure_api_version_detected` (or :func:`is_api_v3`) before building
payloads, and :func:`description_body` / :func:`comment_body` to produce the
correct body shape for the detected version.
"""

import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

# ---------------------------------------------------------------------------
# API version detection (v2 = Server/DC, v3 = Cloud)
# ---------------------------------------------------------------------------

_WRITE_API_VERSION = None  # cached detected/forced version; None until detected
_DETECTION_ERROR = False   # set when detection HTTP fails; keeps us on v2


def _version_from_env():
    """Return the forced API version from JIRA_API_VERSION env var, or None.

    Accepted values: 2, 3, "v2", "v3" (case-insensitive). Anything else
    (including "auto" or unset) means auto-detect.
    """
    raw = (os.environ.get("JIRA_API_VERSION") or "").strip().lower()
    if raw in ("2", "v2"):
        return 2
    if raw in ("3", "v3"):
        return 3
    return None


def _reset_version_state():
    """Reset cached detection state (used by tests and forced re-detection)."""
    global _WRITE_API_VERSION, _DETECTION_ERROR
    _WRITE_API_VERSION = None
    _DETECTION_ERROR = False


def set_write_api_version(version):
    """Force the write API version (2 or 3), bypassing detection.

    Primarily for tests and the JIRA_API_VERSION env override.
    """
    global _WRITE_API_VERSION, _DETECTION_ERROR
    if version not in (2, 3):
        raise ValueError(f"Unsupported API version: {version!r}")
    _WRITE_API_VERSION = version
    _DETECTION_ERROR = False


def get_write_api_version():
    """Return the currently cached write API version (2/3) or None if undetected."""
    return _WRITE_API_VERSION


def _probe_server_info(cfg):
    """GET /rest/api/2/serverInfo without exiting on failure.

    Returns the parsed dict, or None when the probe fails for any reason
    (network error, HTTP error, non-JSON body). Errors are swallowed on
    purpose: detection is best-effort and must not break the actual command.
    """
    url = f"{cfg['url']}/rest/api/2/serverInfo"
    req = urllib.request.Request(url, headers=auth_header(cfg), method="GET")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            if not data:
                return None
            return json.loads(data)
    except Exception:
        return None


def detect_write_api_version(cfg):
    """Detect (and cache) which REST API version write operations must use.

    Resolution order:
      1. JIRA_API_VERSION env var (2/3) — explicit override, no network call.
      2. GET /rest/api/2/serverInfo -> deploymentType == "Cloud" means v3.
      3. On any detection failure, fall back to v2 (Server/DC semantics) so the
         CLI keeps working against self-hosted instances.

    Returns the detected version (2 or 3).
    """
    global _WRITE_API_VERSION, _DETECTION_ERROR

    if _WRITE_API_VERSION is not None:
        return _WRITE_API_VERSION

    forced = _version_from_env()
    if forced is not None:
        _WRITE_API_VERSION = forced
        return forced

    info = _probe_server_info(cfg)
    if info is None:
        # Probe failed — assume Server/DC (v2), the historically-supported mode.
        _DETECTION_ERROR = True
        _WRITE_API_VERSION = 2
        return _WRITE_API_VERSION

    deployment = (info.get("deploymentType") or "").strip().lower()
    _WRITE_API_VERSION = 3 if deployment == "cloud" else 2
    return _WRITE_API_VERSION


def ensure_api_version_detected(cfg):
    """Ensure detection has run; return the write API version (2 or 3)."""
    if _WRITE_API_VERSION is None:
        return detect_write_api_version(cfg)
    return _WRITE_API_VERSION


def is_api_v3(cfg):
    """True when write operations must use API v3 (Cloud) payload formats."""
    return ensure_api_version_detected(cfg) == 3


def description_body(text):
    """Return `text` shaped for the issue `description` field.

    v2 (Server/DC): plain wiki-markup string.
    v3 (Cloud): Atlassian Document Format (ADF) document.
    Call after the API version has been detected (e.g. via is_api_v3()).
    """
    from jira_cli.format import _build_adf_doc

    if _WRITE_API_VERSION == 3:
        return _build_adf_doc(text)
    return text


def comment_body(text):
    """Return `text` shaped for comment bodies (same rules as description_body)."""
    return description_body(text)


# ---------------------------------------------------------------------------
# Core request plumbing
# ---------------------------------------------------------------------------

def auth_header(cfg):
    """Return Basic auth header from user:pass."""
    token = base64.b64encode(f"{cfg['user']}:{cfg['pass']}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _send(req, raw=False):
    """Send a prepared request; return parsed JSON ({} on empty body) or raw bytes when raw. Exits on error."""
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            if raw:
                return data
            if not data:
                return {}
            return json.loads(data)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            err = json.loads(body)
            msg = err.get("errorMessages", [str(e)])
        except json.JSONDecodeError:
            msg = [body or str(e)]
        print(f"ERROR {e.code}: {'; '.join(msg)}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: {e.reason}", file=sys.stderr)
        sys.exit(1)


def _request(cfg, method, path, data=None, params=None):
    """Generic request, routed to API v2 or v3 depending on method and detection.

    Reads (GET/HEAD) always hit v2: Jira Server/DC only has v2 and Jira Cloud
    still serves v2 for reads/search, so detection is not needed for them.
    Write methods (POST/PUT/DELETE) use the detected version.
    """
    if method.upper() in ("GET", "HEAD"):
        api = 2
    else:
        api = ensure_api_version_detected(cfg)

    url = f"{cfg['url']}/rest/api/{api}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)

    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=auth_header(cfg), method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    return _send(req)


def jira_get(cfg, path, params=None):
    """GET request to Jira REST API v2."""
    return _request(cfg, "GET", path, params=params)


def jira_post(cfg, path, data):
    """POST JSON data to Jira REST API (v2 on Server/DC, v3 on Cloud)."""
    return _request(cfg, "POST", path, data=data)


def jira_put(cfg, path, data):
    """PUT JSON data to Jira REST API (v2 on Server/DC, v3 on Cloud)."""
    return _request(cfg, "PUT", path, data=data)


def jira_delete(cfg, path):
    """DELETE request to Jira REST API (v2 on Server/DC, v3 on Cloud)."""
    return _request(cfg, "DELETE", path)


def jira_post_attachment(cfg, issue_key, paths):
    """Upload files as attachments to an issue (multipart/form-data).

    Returns the list of created attachment objects (Jira REST API v2).
    """
    boundary = "----jira-cli-" + uuid.uuid4().hex
    buf = bytearray()
    for p in paths:
        filename = os.path.basename(p)
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode("utf-8")
        buf.extend(header)
        with open(p, "rb") as f:
            buf.extend(f.read())
        buf.extend(b"\r\n")
    buf.extend(f"--{boundary}--\r\n".encode("utf-8"))

    req = urllib.request.Request(
        f"{cfg['url']}/rest/api/2/issue/{issue_key}/attachments",
        data=bytes(buf),
        headers=auth_header(cfg),
        method="POST",
    )
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("X-Atlassian-Token", "no-check")
    return _send(req)


def jira_get_binary(cfg, path):
    """GET a binary resource; returns raw bytes. `path` may be a full URL."""
    url = path if path.startswith("http") else f"{cfg['url']}/rest/api/2/{path}"
    req = urllib.request.Request(url, headers=auth_header(cfg), method="GET")
    req.add_header("Accept", "application/octet-stream")
    return _send(req, raw=True)


def jira_delete_attachment(cfg, attachment_id):
    """DELETE an attachment (requires X-Atlassian-Token)."""
    req = urllib.request.Request(
        f"{cfg['url']}/rest/api/2/attachment/{attachment_id}",
        headers=auth_header(cfg),
        method="DELETE",
    )
    req.add_header("Accept", "application/json")
    req.add_header("X-Atlassian-Token", "no-check")
    return _send(req)
