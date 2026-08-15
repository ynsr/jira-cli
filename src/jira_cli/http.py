"""HTTP helpers for Jira REST API v2."""

import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


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
    """Generic request to Jira REST API v2."""
    url = f"{cfg['url']}/rest/api/2/{path}"
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
    """POST JSON data to Jira REST API v2."""
    return _request(cfg, "POST", path, data=data)


def jira_put(cfg, path, data):
    """PUT JSON data to Jira REST API v2."""
    return _request(cfg, "PUT", path, data=data)


def jira_delete(cfg, path):
    """DELETE request to Jira REST API v2."""
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
