"""Changelog normalization for jira-cli (F2/F3).

Jira Server/DC changelog shape (also served by Cloud v2 reads)::

    {"histories": [{"id": ..., "created": "2024-01-02T10:00:00.000+0000",
                    "author": {"name": "jdoe", "displayName": "John Doe"},
                    "items": [{"field": "status", "fieldtype": "jira",
                               "from": "1", "fromString": "To Do",
                               "to": "3", "toString": "In Progress"}]}], ...}

Normalized entries: ``[{at, author, field, from, to}]`` where ``at`` is the
raw ``created`` timestamp and ``author`` the display name:

- assignee: ``from``/``to`` combine username + display name
  (``"jdoe (John Doe)"``; display-only when the username is unknown).
- status/sprint: human names (``fromString``/``toString``).
- other fields: ``toString``/``fromString`` when present, else raw ids.

``parse_changelog_fields_arg("assignee,status,sprint")`` lowercases and splits
the filter arg; ``None`` means no filtering. ``normalize_histories`` never
raises (bad items are skipped).
"""

from datetime import datetime

_CHANGELOG_FIELD_ALIASES = {
    "assignee": "assignee",
    "status": "status",
    "sprint": "sprint",
}


def parse_changelog_fields_arg(raw):
    """Split a ``--changelog-fields`` value into lowercase field names (None = no filter)."""
    if raw is None:
        return None
    parts = [p.strip().lower() for p in str(raw).split(",")]
    parts = [p for p in parts if p]
    return parts or None


def _norm_field_name(item):
    """Lowercase field key for an item (maps 'Sprint' custom names to 'sprint')."""
    name = str(item.get("field") or "").strip().lower()
    if name in _CHANGELOG_FIELD_ALIASES:
        return name
    field_id = str(item.get("fieldId") or item.get("field_id") or "").strip().lower()
    if "sprint" in field_id or "sprint" in name:
        return "sprint"
    if "assignee" in field_id:
        return "assignee"
    return name


def _person_text(name, display):
    """Combine username + display name for assignee entries."""
    name = (name or "").strip()
    display = (display or "").strip()
    if name and display and name != display:
        return f"{name} ({display})"
    return display or name or ""


def _reporter_name(item):
    """Best-effort username for an assignee changelog item."""
    for key in ("from", "to"):
        val = item.get(key)
        if isinstance(val, str) and val.strip() and not val.strip().isdigit():
            return val.strip()
    return ""


def normalize_histories(histories, fields=None, since=None):
    """Normalize raw ``histories`` to ``[{at, author, field, from, to}]``.

    ``fields``: lowercase names to keep (None = all). ``since``: ISO date
    prefix filter on ``at`` (``YYYY-MM-DD`` or full timestamp). Never raises.
    """
    out = []
    wanted = {f.lower() for f in fields} if fields else None
    for hist in histories or []:
        if not isinstance(hist, dict):
            continue
        try:
            at = hist.get("created") or ""
            if since and str(at) < str(since):
                continue
            author = hist.get("author")
            if isinstance(author, dict):
                author = author.get("displayName") or author.get("name") or ""
            author = str(author or "")
            for item in hist.get("items") or []:
                if not isinstance(item, dict):
                    continue
                try:
                    field = _norm_field_name(item)
                    if wanted is not None and field not in wanted:
                        continue
                    if field == "assignee":
                        frm = _person_text(item.get("from"), item.get("fromString"))
                        to = _person_text(item.get("to"), item.get("toString"))
                    elif field in ("status", "sprint"):
                        frm = item.get("fromString")
                        to = item.get("toString")
                        frm = str(frm) if frm is not None else str(item.get("from") or "")
                        to = str(to) if to is not None else str(item.get("to") or "")
                    else:
                        frm = item.get("fromString")
                        to = item.get("toString")
                        if frm is None:
                            frm = item.get("from")
                        if to is None:
                            to = item.get("to")
                        frm = "" if frm is None else str(frm)
                        to = "" if to is None else str(to)
                    out.append({"at": at, "author": author, "field": field,
                                "from": frm, "to": to})
                except Exception:
                    continue
        except Exception:
            continue
    return out


def iter_full_histories(cfg, issue_key, changelog, jira_get):
    """Yield all histories, backfilling via ``GET issue/K/changelog`` when truncated.

    ``changelog`` is the inline ``expand=changelog`` block
    (``{histories, total, maxResults}``). Extra pages are fetched with
    ``startAt``/``maxResults`` until ``total`` is reached. ``jira_get`` is
    injected for testability. Never raises on fetch failure (yields inline).
    """
    changelog = changelog or {}
    inline = changelog.get("histories") or []
    total = changelog.get("total")
    for hist in inline:
        yield hist
    if not isinstance(total, int) or total <= len(inline):
        return
    start = len(inline)
    page_size = changelog.get("maxResults") or 100
    try:
        page_size = max(1, int(page_size))
    except (TypeError, ValueError):
        page_size = 100
    while start < total:
        try:
            page = jira_get(cfg, f"issue/{issue_key}/changelog",
                            {"startAt": start, "maxResults": page_size})
        except Exception:
            return
        items = (page or {}).get("histories") or []
        if not items:
            return
        for hist in items:
            yield hist
        start += len(items)
        total = (page or {}).get("total", total)
        if len(items) < page_size:
            return


def _parse_since(since):
    """Parse --since to a comparable string; supports YYYY-MM-DD and ISO timestamps."""
    if not since:
        return ""
    text = str(since).strip()
    try:
        if len(text) == 10:
            datetime.strptime(text, "%Y-%m-%d")
            return text
        return text
    except ValueError:
        raise ValueError(f"Invalid --since date: {since!r} (use YYYY-MM-DD)")
