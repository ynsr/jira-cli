"""Agile field extraction for Jira issues.

Resolution is a standard field (``fields.resolution``). Story Points and
Sprint live in instance-specific ``customfield_NNNNN`` slots whose IDs vary
per Jira instance, so they are resolved via ``GET /rest/api/2/field`` and
matched by field *name* (case-insensitive):

- Story Points: "Story Points" (also "Story Point Estimate").
- Sprint: "Sprint".

Resolved IDs are cached per (domain, project) on disk for 30 days
(``$JIRA_CLI_FIELD_CACHE_DIR`` or ``~/.config/jira-cli/field-cache/``) plus
an in-process memory cache, so the ``/field`` lookup costs one request per
month per domain+project. Stale cache is reused when the fetch fails.

When IDs are unknown (fetch failed and no cache), extraction falls back to
value-*shape* scanning of the issue's ``fields`` dict: a numeric
``customfield_*`` is treated as Story Points, and a list of GreenHopper
``Sprint@...`` strings (or ``{name, state}`` dicts) as Sprint. Sprint values
are normalized to ``"<name> (<state>)"``. Extraction never raises.
"""

import json
import os
import re
import time
import urllib.parse

from jira_cli import config as _config

FIELD_CACHE_TTL = 30 * 24 * 3600  # 1 month, in seconds

_STORY_POINTS_NAMES = {"story points", "story point estimate"}
_SPRINT_NAMES = {"sprint"}

_SPRINT_RE_NAME = re.compile(r"name=([^,\]]+)")
_SPRINT_RE_STATE = re.compile(r"state=([^,\]]+)")

_CACHE_MEMORY = {}  # (url, project) -> {"story_points": id|None, "sprint": id|None}


def _reset_field_cache():
    """Clear the in-process field-ID cache (used by tests)."""
    _CACHE_MEMORY.clear()


def _cache_dir():
    """Directory holding cached field-ID files (env-overridable for tests)."""
    return os.environ.get("JIRA_CLI_FIELD_CACHE_DIR") or os.path.join(
        _config.CONFIG_DIR, "field-cache"
    )


def _safe_part(text, fallback="global"):
    """Make a string safe for use as a cache filename component."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", (text or "").strip())
    return cleaned[:80] or fallback


def _cache_path(url, project):
    """Cache file for one (domain, project) pair."""
    try:
        domain = urllib.parse.urlparse(url or "").netloc or url or "global"
    except Exception:
        domain = url or "global"
    return os.path.join(
        _cache_dir(), f"{_safe_part(domain)}__{_safe_part(project)}.json"
    )


def _read_cache(path):
    """Return cached ``{"fetched_at": ts, "fields": {...}}`` or {} on any error."""
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _write_cache(path, ids):
    """Persist resolved IDs; best-effort, never raises."""
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        with open(path, "w") as f:
            json.dump({"fetched_at": time.time(), "fields": ids}, f)
        os.chmod(path, 0o600)
    except OSError:
        pass


def _match_field_ids(field_list):
    """Map a ``/field`` response list to ``{"story_points": id, "sprint": id}``."""
    ids = {"story_points": None, "sprint": None}
    for fld in field_list or []:
        if not isinstance(fld, dict):
            continue
        name = str(fld.get("name") or "").strip().lower()
        fid = fld.get("id")
        if not fid:
            continue
        if name in _STORY_POINTS_NAMES and ids["story_points"] is None:
            ids["story_points"] = fid
        elif name in _SPRINT_NAMES and ids["sprint"] is None:
            ids["sprint"] = fid
    return ids


def get_custom_field_ids(cfg, project=None):
    """Return ``{"story_points": id|None, "sprint": id|None}`` for (domain, project).

    Fresh file cache (< 30 days) wins; otherwise ``GET /rest/api/2/field``
    is fetched once and cached. A failed fetch falls back to stale cache,
    then to all-``None`` (callers shape-scan). Never raises.
    """
    cfg = cfg or {}
    url = cfg.get("url") or ""
    proj = (project or "global").strip() or "global"
    memkey = (url, proj)
    if memkey in _CACHE_MEMORY:
        return _CACHE_MEMORY[memkey]
    ids = {"story_points": None, "sprint": None}
    if not url:
        _CACHE_MEMORY[memkey] = ids
        return ids

    path = _cache_path(url, proj)
    cached = _read_cache(path)
    cached_ids = cached.get("fields") if isinstance(cached.get("fields"), dict) else None
    if cached_ids and time.time() - cached.get("fetched_at", 0) < FIELD_CACHE_TTL:
        ids = {"story_points": cached_ids.get("story_points"),
               "sprint": cached_ids.get("sprint")}
        _CACHE_MEMORY[memkey] = ids
        return ids

    fetched = None
    try:
        from jira_cli.http import jira_get

        data = jira_get(cfg, "field")
        if isinstance(data, list):
            fetched = _match_field_ids(data)
    except Exception:
        fetched = None
    if fetched is not None:
        ids = fetched
        _write_cache(path, ids)
    elif cached_ids:
        ids = {"story_points": cached_ids.get("story_points"),
               "sprint": cached_ids.get("sprint")}
    _CACHE_MEMORY[memkey] = ids
    return ids


def parse_sprint_value(value):
    """Normalize a raw Sprint field value to a list of display names.

    Accepts GreenHopper ``Sprint@...[name=X,state=Y,...]`` strings, dicts
    with ``name``/``state`` keys, and plain strings. Returns ``[]`` for
    empty/unknown input.
    """
    if not value:
        return []
    raw_items = value if isinstance(value, list) else [value]
    names = []
    for item in raw_items:
        if isinstance(item, dict):
            name = item.get("name")
            if name:
                state = item.get("state")
                names.append(f"{name} ({state})" if state else str(name))
            continue
        text = str(item)
        m_name = _SPRINT_RE_NAME.search(text)
        if m_name:
            name = m_name.group(1).strip()
            m_state = _SPRINT_RE_STATE.search(text)
            state = m_state.group(1).strip() if m_state else ""
            if state and state.upper() != "UNKNOWN":
                names.append(f"{name} ({state})")
            else:
                names.append(name)
        elif text.strip():
            names.append(text.strip())
    return names


def _is_story_points_value(val):
    """True for a plausible Story Points value: numeric, not bool."""
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def _looks_like_sprint(val):
    """True when a value has the shape of a Sprint custom field."""
    return (
        isinstance(val, list)
        and bool(val)
        and (
            (isinstance(val[0], str) and "Sprint@" in val[0])
            or (isinstance(val[0], dict) and val[0].get("name"))
        )
    )


def extract_agile_fields(fields, cfg=None, project=None):
    """Extract resolution/story-points/sprint from an issue ``fields`` dict.

    With ``cfg`` (+ ``project``), exact custom-field IDs from the monthly
    ``/field`` cache are preferred; anything still unknown falls back to
    shape scanning. Without ``cfg``, pure shape scanning applies.

    Returns ``{"resolution": str|None, "story_points": number|None,
    "sprint": [str]}``. Never raises.
    """
    fields = fields or {}
    resolution = fields.get("resolution")
    if isinstance(resolution, dict):
        resolution = resolution.get("name")
    resolution = resolution or None

    sp_id = sprint_id = None
    if cfg and cfg.get("url"):
        try:
            ids = get_custom_field_ids(cfg, project)
            sp_id, sprint_id = ids.get("story_points"), ids.get("sprint")
        except Exception:
            sp_id = sprint_id = None

    story_points = None
    sprints = []
    if sp_id is not None and sp_id in fields:
        if _is_story_points_value(fields[sp_id]):
            story_points = fields[sp_id]
    if sprint_id is not None and sprint_id in fields:
        sprints = parse_sprint_value(fields[sprint_id])

    if story_points is None or not sprints:
        for key, val in fields.items():
            if not isinstance(key, str) or not key.startswith("customfield_"):
                continue
            if key in (sp_id, sprint_id):
                continue
            if story_points is None and sp_id is None and _is_story_points_value(val):
                story_points = val
            if not sprints and sprint_id is None and _looks_like_sprint(val):
                sprints = parse_sprint_value(val)
    return {
        "resolution": resolution,
        "story_points": story_points,
        "sprint": sprints,
    }
