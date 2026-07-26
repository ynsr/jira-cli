"""HTTP helpers for Jira REST API v2."""

import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def auth_header(cfg):
    """Return Basic auth header from user:pass."""
    token = base64.b64encode(f"{cfg['user']}:{cfg['pass']}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


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

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
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
