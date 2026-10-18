"""Agile field extraction for Jira issues.

Resolution is a standard field (``fields.resolution``). Story Points, Sprint,
and Epic Link live in instance-specific ``customfield_NNNNN`` slots whose IDs
vary per Jira instance, so they are resolved in layers:

1. Config/env override: ``cfg["fields"][kind]`` (or ``cfg["<kind>_field"]``)
   wins, else ``JIRA_CLI_SP_FIELD`` / ``JIRA_CLI_SPRINT_FIELD`` /
   ``JIRA_CLI_EPIC_LINK_FIELD`` (``JIRA_CLI_EPIC_FIELD`` also accepted).
2. Case-insensitive name match on ``GET /rest/api/2/field``:
   - Story Points: "Story Points", "Story Point Estimate",
     "Original Story Points".
   - Sprint: "Sprint".
   - Epic Link: "Epic Link".
3. None -> null (callers surface a ``doctor`` warning).

Resolved IDs are cached per (domain, project) on disk for 30 days
(``$JIRA_CLI_FIELD_CACHE_DIR`` or ``~/.config/jira-cli/field-cache/``) plus
an in-process memory cache, so the ``/field`` lookup costs one request per
month per domain+project. Stale cache is reused when the fetch fails.
Old two-key cache files (story_points/sprint) are read compatibly.

When IDs are unknown (fetch failed and no cache), extraction falls back to
value-*shape* scanning of the issue's ``fields`` dict: a numeric
``customfield_*`` is treated as Story Points, and a list of GreenHopper
``Sprint@...`` strings (or ``{name, state}`` dicts) as Sprint. Sprint values
are normalized to ``"<name> (<state>)"``. Extraction never raises.

``sprints`` (structured) and ``epic_key`` are new normalized keys; the legacy
``sprint`` display-name list is kept untouched for backward compatibility.
"""

import json
import os
import re
import time
import urllib.parse

from jira_cli import config as _config

FIELD_CACHE_TTL = 30 * 24 * 3600  # 1 month, in seconds

_STORY_POINTS_NAMES = {"story points", "story point estimate", "original story points"}
_SPRINT_NAMES = {"sprint"}
_EPIC_LINK_NAMES = {"epic link"}

_EMPTY_IDS = {"story_points": None, "sprint": None, "epic_link": None}

_SPRINT_RE_NAME = re.compile(r"name=([^,\]]+)")
_SPRINT_RE_STATE = re.compile(r"state=([^,\]]+)")
_SPRINT_RE_ID = re.compile(r"id=([^,\]]+)")
_SPRINT_RE_START = re.compile(r"startDate=([^,\]]+)")
_SPRINT_RE_END = re.compile(r"endDate=([^,\]]+)")
_SPRINT_RE_COMPLETE = re.compile(r"completeDate=([^,\]]+)")

_CACHE_MEMORY = {}  # (url, project) -> {"story_points": id|None, "sprint": id|None, "epic_link": id|None}


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


def _override_ids(cfg):
    """Layer-1 IDs from config/env overrides: ``{"kind": id|None}`` (unset -> None).

    Precedence per kind: ``cfg["fields"][kind]`` (dict, e.g. from a
    ``fields.story_points`` config key), then ``cfg["<kind>_field"]``, then env:
    ``JIRA_CLI_SP_FIELD`` (story_points; ``JIRA_STORY_POINTS_FIELD`` also read),
    ``JIRA_CLI_SPRINT_FIELD``, ``JIRA_CLI_EPIC_LINK_FIELD``
    (``JIRA_CLI_EPIC_FIELD`` also read).
    """
    cfg = cfg or {}
    nested = cfg.get("fields") if isinstance(cfg.get("fields"), dict) else {}
    table = (
        ("story_points", ("story_points_field",), ("JIRA_CLI_SP_FIELD", "JIRA_STORY_POINTS_FIELD")),
        ("sprint", ("sprint_field",), ("JIRA_CLI_SPRINT_FIELD",)),
        ("epic_link", ("epic_link_field", "epic_field"), ("JIRA_CLI_EPIC_LINK_FIELD", "JIRA_CLI_EPIC_FIELD")),
    )
    out = {}
    for kind, cfg_keys, env_keys in table:
        val = nested.get(kind)
        if not val:
            for ck in cfg_keys:
                if cfg.get(ck):
                    val = cfg.get(ck)
                    break
        if not val:
            for ek in env_keys:
                if os.environ.get(ek, "").strip():
                    val = os.environ.get(ek).strip()
                    break
        out[kind] = str(val).strip() if val else None
    return out


def _match_field_ids(field_list):
    """Map a ``/field`` response list to ``{"story_points": id, "sprint": id, "epic_link": id}``."""
    ids = dict(_EMPTY_IDS)
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
        elif name in _EPIC_LINK_NAMES and ids["epic_link"] is None:
            ids["epic_link"] = fid
    return ids


def _pick_cached_ids(cached_ids):
    """Project a cache-file ``fields`` dict onto the current key set (old 2-key files compatible)."""
    return {kind: (cached_ids.get(kind) if isinstance(cached_ids, dict) else None)
            for kind in _EMPTY_IDS}


def get_custom_field_ids(cfg, project=None):
    """Return ``{"story_points": id|None, "sprint": id|None, "epic_link": id|None}``.

    Layer 1 (config/env overrides) wins per kind and is returned without any
    network call for the overridden kinds. Remaining kinds use the fresh file
    cache (< 30 days), else ``GET /rest/api/2/field`` fetched once and cached.
    A failed fetch falls back to stale cache, then to ``None`` (callers
    shape-scan). Never raises.
    """
    cfg = cfg or {}
    url = cfg.get("url") or ""
    proj = (project or "global").strip() or "global"
    memkey = (url, proj)
    if memkey in _CACHE_MEMORY:
        return _CACHE_MEMORY[memkey]
    ids = dict(_EMPTY_IDS)
    overrides = _override_ids(cfg)
    if not url:
        ids.update({k: v for k, v in overrides.items() if v})
        _CACHE_MEMORY[memkey] = ids
        return ids

    path = _cache_path(url, proj)
    cached = _read_cache(path)
    cached_ids = cached.get("fields") if isinstance(cached.get("fields"), dict) else None
    if cached_ids and time.time() - cached.get("fetched_at", 0) < FIELD_CACHE_TTL:
        ids = _pick_cached_ids(cached_ids)
        ids.update({k: v for k, v in overrides.items() if v})
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
        ids = _pick_cached_ids(cached_ids)
    ids.update({k: v for k, v in overrides.items() if v})
    _CACHE_MEMORY[memkey] = ids
    return ids


def unresolved_field_kinds(cfg, project=None):
    """Kinds (subset of story_points/sprint/epic_link) with no resolved ID: ``doctor`` warning source."""
    try:
        ids = get_custom_field_ids(cfg, project)
    except Exception:
        return ["story_points", "sprint", "epic_link"]
    return [k for k in ("story_points", "sprint", "epic_link") if not ids.get(k)]


def _sprint_name_state(text):
    """Split a GreenHopper ``Sprint@...`` string into (name, state-or-"")."""
    m_name = _SPRINT_RE_NAME.search(text)
    if not m_name:
        return (text.strip(), "")
    name = m_name.group(1).strip()
    m_state = _SPRINT_RE_STATE.search(text)
    state = m_state.group(1).strip() if m_state else ""
    if state.upper() == "UNKNOWN":
        state = ""
    return (name, state)


def _sprint_kv(text, rx):
    """First ``key=value`` capture from a GreenHopper string, "" when absent/blank."""
    m = rx.search(text)
    if not m:
        return ""
    val = m.group(1).strip()
    return "" if val in ("", "<null>", "None") else val


def parse_sprints(value):
    """Normalize a raw Sprint value to ``[{id,name,state,start,end}]`` (Cloud dicts + legacy strings).

    Legacy Server strings look like
    ``com.atlassian.greenhopper.service.sprint.Sprint@[id=547,name=X,state=ACTIVE,startDate=..,endDate=..]``;
    ids/ints are kept as strings-or-ints as received (``id`` int when numeric).
    Unknown/empty items are skipped. Never raises.
    """
    if not value:
        return []
    raw_items = value if isinstance(value, list) else [value]
    out = []
    for item in raw_items:
        try:
            if isinstance(item, dict):
                name = item.get("name")
                if not name:
                    continue
                state = item.get("state") or item.get("status") or ""
                out.append({
                    "id": item.get("id"),
                    "name": str(name),
                    "state": str(state) if state else "",
                    "start": item.get("startDate") or item.get("start") or "",
                    "end": item.get("endDate") or item.get("end") or item.get("completeDate") or "",
                })
                continue
            text = str(item)
            if "Sprint@" in text and ("name=" in text or "id=" in text):
                name, state = _sprint_name_state(text)
                raw_id = _sprint_kv(text, _SPRINT_RE_ID)
                try:
                    sid = int(raw_id) if raw_id else None
                except ValueError:
                    sid = raw_id or None
                out.append({
                    "id": sid,
                    "name": name,
                    "state": state,
                    "start": _sprint_kv(text, _SPRINT_RE_START),
                    "end": _sprint_kv(text, _SPRINT_RE_END) or _sprint_kv(text, _SPRINT_RE_COMPLETE),
                })
            elif text.strip():
                out.append({"id": None, "name": text.strip(), "state": "", "start": "", "end": ""})
        except Exception:
            continue
    return out


def parse_sprint_value(value):
    """Normalize a raw Sprint field value to a list of display names.

    Accepts GreenHopper ``Sprint@...[name=X,state=Y,...]`` strings, dicts
    with ``name``/``state`` keys, and plain strings. Returns ``[]`` for
    empty/unknown input. Legacy display form; new code prefers
    :func:`parse_sprints`.
    """
    names = []
    for sp in parse_sprints(value):
        if sp.get("state"):
            names.append(f"{sp['name']} ({sp['state']})")
        else:
            names.append(str(sp["name"]))
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


_EPIC_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def _epic_key_value(val):
    """Best-effort epic key from a raw Epic Link value (str key or {key} dict)."""
    try:
        if isinstance(val, dict):
            key = val.get("key") or val.get("epicKey") or val.get("epic_key")
            return str(key).strip() if key else None
        text = str(val or "").strip()
        if not text:
            return None
        m = _EPIC_KEY_RE.search(text)
        return m.group(1) if m else None
    except Exception:
        return None


def _looks_like_epic(val):
    """True when a value has the shape of an Epic Link custom field."""
    if isinstance(val, dict):
        return bool(val.get("key") or val.get("epicKey"))
    return isinstance(val, str) and bool(_EPIC_KEY_RE.search(val or ""))


def extract_agile_fields(fields, cfg=None, project=None):
    """Extract resolution/story-points/sprint/epic from an issue ``fields`` dict.

    With ``cfg`` (+ ``project``), layered IDs (override, then monthly
    ``/field`` cache) are preferred; anything still unknown falls back to
    shape scanning. Without ``cfg``, pure shape scanning applies.

    Returns ``{"resolution": str|None, "story_points": number|None,
    "sprint": [str], "sprints": [{id,name,state,start,end}],
    "epic_key": str|None}``. ``sprint`` is the legacy display list, kept
    untouched. Never raises.
    """
    fields = fields or {}
    resolution = fields.get("resolution")
    if isinstance(resolution, dict):
        resolution = resolution.get("name")
    resolution = resolution or None

    sp_id = sprint_id = epic_id = None
    if cfg and (cfg.get("url") or _override_ids(cfg).get("story_points")):
        try:
            ids = get_custom_field_ids(cfg, project)
            sp_id, sprint_id, epic_id = ids.get("story_points"), ids.get("sprint"), ids.get("epic_link")
        except Exception:
            sp_id = sprint_id = epic_id = None

    story_points = None
    sprint_raw = None
    epic_key = None
    if sp_id is not None and sp_id in fields:
        if _is_story_points_value(fields[sp_id]):
            story_points = fields[sp_id]
    if sprint_id is not None and sprint_id in fields:
        sprint_raw = fields[sprint_id]
    if epic_id is not None and epic_id in fields:
        epic_key = _epic_key_value(fields[epic_id])

    if story_points is None or sprint_raw is None or epic_key is None:
        for key, val in fields.items():
            if not isinstance(key, str) or not key.startswith("customfield_"):
                continue
            if key in (sp_id, sprint_id, epic_id):
                continue
            if story_points is None and sp_id is None and _is_story_points_value(val):
                story_points = val
            if sprint_raw is None and sprint_id is None and _looks_like_sprint(val):
                sprint_raw = val
            if epic_key is None and epic_id is None and _looks_like_epic(val):
                epic_key = _epic_key_value(val)
    try:
        structured = parse_sprints(sprint_raw)
    except Exception:
        structured = []
    return {
        "resolution": resolution,
        "story_points": story_points,
        "sprint": parse_sprint_value(sprint_raw),
        "sprints": structured,
        "epic_key": epic_key,
    }
