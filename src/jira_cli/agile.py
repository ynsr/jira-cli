"""Agile read commands: board/sprint (F4), membership moves (F5), permissions (F6).

All reads use ``/rest/agile/1.0/`` with the same Basic auth. Sprint objects
are normalized to ``{id,name,state,start,end,complete,board}`` from both
Server payloads (``startDate``/``endDate``/``completeDate``) and Cloud shapes
(``startDate``/``originBoardId`` tolerated).

Output convention: ``--format json`` prints data-only JSON
(``ensure_ascii=False``); table mode prints human rows. Membership moves
follow the destructive-action convention (``--dry-run`` previews with zero
write calls, otherwise ``--yes`` or a TTY confirm is required).
"""

import json
import os
import sys

from jira_cli.http import agile_get, agile_post, jira_get

# --- F5 write endpoints (unverified live: Atlassian docs say POST for both;
# an earlier investigation claimed PUT for backlog. Do NOT probe with a real
# write; if a server answers 405 the error envelope names method+path). ---
BACKLOG_MOVE_METHOD = "POST"
BACKLOG_MOVE_PATH = "backlog/issue"
SPRINT_MOVE_METHOD = "POST"
SPRINT_MOVE_PATH_TEMPLATE = "sprint/{id}/issue"

MOVE_CHUNK_SIZE = 50

_JOURNAL_MODE = 0o600


def _print_json(payload):
    """Print data-only JSON (Persian-safe)."""
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def normalize_sprint(raw, board=None):
    """Normalize one sprint object to ``{id,name,state,start,end,complete,board}``."""
    raw = raw or {}
    state = raw.get("state") or raw.get("status") or ""
    board_id = raw.get("originBoardId", raw.get("boardId", board))
    try:
        board_id = int(board_id) if board_id is not None else board
    except (TypeError, ValueError):
        pass
    try:
        sid = raw.get("id")
        sid = int(sid) if sid is not None else None
    except (TypeError, ValueError):
        sid = raw.get("id")
    return {
        "id": sid,
        "name": raw.get("name") or "",
        "state": str(state).upper() if state else "",
        "start": raw.get("startDate") or "",
        "end": raw.get("endDate") or "",
        "complete": raw.get("completeDate") or "",
        "board": board_id,
    }


def _sprint_end_key(sp):
    """Sort key for closed sprints: complete > end > id."""
    return (sp.get("complete") or "", sp.get("end") or "", str(sp.get("id") or ""))


# -------------------------------------------------------------------
# F4 reads
# -------------------------------------------------------------------

def cmd_board_list(cfg, project=None, fmt="table"):
    """List agile boards (``GET board``), optionally filtered by project key."""
    params = {}
    if project:
        params["projectKeyOrId"] = project
    data = agile_get(cfg, "board", params or None)
    boards = data.get("values", data if isinstance(data, list) else [])
    out = [{"id": b.get("id"), "name": b.get("name") or "",
            "type": b.get("type") or "",
            "project": ((b.get("location") or {}).get("projectKey")
                        or (b.get("location") or {}).get("projectId") or "")}
           for b in boards if isinstance(b, dict)]
    if fmt == "json":
        _print_json(out)
        return out
    if not out:
        print("No boards found.")
        return []
    for b in out:
        print(f"  {b['id']:6}  {b['name'][:50]:50}  {b['type']:10}  {b['project']}")
    return out


def _iter_sprints(cfg, board, state=None, page_size=50):
    """Yield raw sprint objects for a board (all pages)."""
    start = 0
    while True:
        params = {"startAt": start, "maxResults": page_size}
        if state:
            params["state"] = state
        data = agile_get(cfg, f"board/{board}/sprint", params)
        batch = data.get("values", [])
        for sp in batch:
            yield sp
        if data.get("isLast", True) or not batch:
            return
        start += len(batch)


def cmd_sprint_list(cfg, board, state=None, last=None, fmt="table"):
    """List sprints for a board, normalized.

    ``state``: comma list among active,future,closed (passed through).
    ``last N``: the N most recently ended closed sprints — the API returns
    oldest first, so all closed pages are read and the tail by
    (completeDate, endDate, id) is kept.
    """
    states = None
    if state:
        states = ",".join(s.strip().lower() for s in str(state).split(",") if s.strip())
    raw = [normalize_sprint(sp, board) for sp in _iter_sprints(cfg, board, states)]
    if last is not None and str(states or "").strip().lower() in ("closed",):
        raw.sort(key=_sprint_end_key)
        raw = raw[-last:] if last > 0 else []
    out = raw
    if fmt == "json":
        _print_json(out)
        return out
    if not out:
        print(f"No sprints found for board {board}.")
        return []
    for sp in out:
        rng = f"{(sp['start'] or '')[:10]}..{(sp['end'] or '')[:10]}"
        print(f"  {sp['id']:6}  {sp['name'][:45]:45}  {sp['state']:8}  {rng}")
    return out


def cmd_sprint_get(cfg, sprint_id, fmt="table"):
    """Show one sprint (``GET sprint/{id}``), normalized."""
    out = normalize_sprint(agile_get(cfg, f"sprint/{sprint_id}"))
    if fmt == "json":
        _print_json(out)
        return out
    print(f"  {out['id']}  {out['name']}  ({out['state']})  "
          f"{(out['start'] or '')[:10]}..{(out['end'] or '')[:10]}")
    return out


def cmd_sprint_issues(cfg, sprint_id, fields=None, fetch_all=False,
                      max_results=1000, fmt="table"):
    """List issues in a sprint: same normalized issue shape as search (F2)."""
    from jira_cli.commands import _agile_json_fields, _project_for_field_cache

    start = 0
    page_size = 50
    collected = []
    total = 0
    while True:
        data = agile_get(cfg, f"sprint/{sprint_id}/issue",
                         {"startAt": start, "maxResults": page_size,
                          **({"fields": fields} if fields else {})})
        batch = data.get("issues", [])
        total = data.get("total", len(batch))
        collected.extend(batch)
        start += len(batch)
        if not fetch_all or not batch or start >= total or len(collected) >= max_results:
            break
    issues = collected[:max_results]
    proj = _project_for_field_cache(issues=issues)
    for iss in issues:
        iss.setdefault("fields", {}).update(
            _agile_json_fields(iss.get("fields", {}), cfg, proj))
    if fmt == "json":
        _print_json(issues)
        return issues
    if not issues:
        print(f"No issues in sprint {sprint_id}.")
        return []
    print(f"\nSprint {sprint_id}: {total} issues (showing {len(issues)})\n")
    for iss in issues:
        f = iss.get("fields", {})
        status = (f.get("status") or {}).get("name", "")
        print(f"  {iss.get('key', '?'):15}  {status:20}  {(f.get('summary') or '')[:70]}")
    print()
    return issues


def cmd_sprint_current(cfg, board, fmt="table"):
    """Print the active sprint, else the earliest future sprint (else exit 1)."""
    sprints = [normalize_sprint(sp, board) for sp in _iter_sprints(cfg, board)]
    active = [s for s in sprints if s["state"] == "ACTIVE"]
    future = sorted([s for s in sprints if s["state"] == "FUTURE"],
                    key=lambda s: (s["start"] or "", str(s["id"] or "")))
    if active:
        out = {"which": "active", "sprint": active[0]}
    elif future:
        out = {"which": "future", "sprint": future[0]}
    else:
        print(f"Error: board {board} has no active or future sprint.", file=sys.stderr)
        sys.exit(1)
    if fmt == "json":
        _print_json(out)
        return out
    sp = out["sprint"]
    print(f"  {out['which']}: {sp['id']}  {sp['name']}  ({sp['state']})")
    return out


# -------------------------------------------------------------------
# F5 membership journal + moves
# -------------------------------------------------------------------

def _journal_path_for(journal, action):
    """Resolve the journal path: explicit --journal, else a timestamped file in cwd."""
    if journal:
        return journal
    import datetime as _dt
    import re as _re
    safe = _re.sub(r"[^A-Za-z0-9_.-]+", ".", str(action))
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"./jira-cli-{safe}-{stamp}.json"


def _current_sprint_ids(cfg, issue_key, sprint_field_id=None):
    """Sprint ids currently containing an issue (via the Sprint custom field)."""
    from jira_cli.fields import get_custom_field_ids, parse_sprints

    data = jira_get(cfg, f"issue/{issue_key}", {"fields": "key,sprint,*navigable"})
    fields = data.get("fields") or {}
    sid = sprint_field_id
    if sid is None:
        try:
            proj = issue_key.split("-", 1)[0].upper() if "-" in issue_key else "global"
            sid = get_custom_field_ids(cfg, proj).get("sprint")
        except Exception:
            sid = None
    raw = fields.get(sid) if sid in fields else None
    if raw is None:
        for key, val in fields.items():
            if isinstance(key, str) and key.startswith("customfield_") and isinstance(val, list) and val:
                first = val[0]
                if (isinstance(first, str) and "Sprint@" in first) or \
                   (isinstance(first, dict) and first.get("name")):
                    raw = val
                    break
    ids = []
    for sp in parse_sprints(raw):
        if isinstance(sp.get("id"), int):
            ids.append(sp["id"])
    return ids


def _write_journal(path, payload):
    """Write the move journal BEFORE any write call (0600). Returns the path."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.chmod(path, _JOURNAL_MODE)
    return path


def _confirm_or_exit(action, yes, dry_run):
    """Shared destructive gate for moves (mirrors guard_destructive semantics)."""
    if dry_run:
        return False
    if yes:
        return True
    if sys.stdin.isatty():
        try:
            answer = input(f"{action} — proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer in ("y", "yes"):
            return True
        print("Aborted.", file=sys.stderr)
        sys.exit(1)
    print(f"Error: {action} is destructive. Re-run with --yes to execute or --dry-run to preview.",
          file=sys.stderr)
    sys.exit(2)


def _chunked(seq, size):
    """Split a list into chunks of <= size."""
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def _do_move(cfg, keys, to, journal, yes, dry_run, action):
    """Validate -> journal-before-write -> chunked POSTs -> verify. Returns journal path."""
    from jira_cli.fields import parse_sprints  # noqa: F401 (re-export guard)

    keys = [k.upper() for k in keys]
    # 1. validate keys exist + read current membership
    items = []
    for key in keys:
        try:
            jira_get(cfg, f"issue/{key}", {"fields": "key"})
        except SystemExit:
            print(f"Error: issue not found: {key}", file=sys.stderr)
            sys.exit(1)
        from_ids = _current_sprint_ids(cfg, key)
        items.append({"key": key, "from_sprint_ids": from_ids, "to": to})
    # 2. journal BEFORE any write
    import datetime as _dt
    payload = {"created_at": _dt.datetime.now().isoformat(timespec="seconds"),
               "user": cfg.get("user", ""),
               "base_url": cfg.get("url", ""),
               "action": action,
               "items": items}
    journal_path = _journal_path_for(journal, action)
    _write_journal(journal_path, payload)
    # 3. gate
    target_desc = f"sprint {to}" if to != "backlog" else "backlog"
    plan = f"Move {len(keys)} issue(s) to {target_desc}"
    if dry_run:
        print(f"DRY-RUN — {plan}:")
        for it in items:
            print(f"  {it['key']}: from={it['from_sprint_ids']} to={to}")
        print(f"  journal: {journal_path}")
        return journal_path
    _confirm_or_exit(plan, yes, dry_run)
    # 4. chunked writes (POST per spec constants; never retried blindly)
    if to == "backlog":
        method, describe = BACKLOG_MOVE_METHOD, BACKLOG_MOVE_PATH
        for chunk in _chunked(keys, MOVE_CHUNK_SIZE):
            agile_post(cfg, BACKLOG_MOVE_PATH, {"issues": chunk})
            print(f"  {method} {describe}: {len(chunk)} issue(s)")
    else:
        path = SPRINT_MOVE_PATH_TEMPLATE.format(id=to)
        for chunk in _chunked(keys, MOVE_CHUNK_SIZE):
            agile_post(cfg, path, {"issues": chunk})
            print(f"  {SPRINT_MOVE_METHOD} {path}: {len(chunk)} issue(s)")
    # 5. verify by re-reading membership
    mismatches = []
    for it in items:
        now = _current_sprint_ids(cfg, it["key"])
        if to == "backlog":
            ok = not now
        else:
            try:
                ok = int(to) in now
            except (TypeError, ValueError):
                ok = False
        if not ok:
            mismatches.append({"key": it["key"], "expected": to, "actual": now})
    if mismatches:
        for m in mismatches:
            print(f"Error: verify failed for {m['key']}: expected {m['expected']}, now in {m['actual']}",
                  file=sys.stderr)
        sys.exit(1)
    print(f"{plan} — verified.")
    return journal_path


def cmd_backlog_move(cfg, keys, journal=None, yes=False, dry_run=False):
    """Move issues to the backlog (POST backlog/issue, chunked, verified)."""
    return _do_move(cfg, keys, "backlog", journal, yes, dry_run, "backlog.move")


def cmd_sprint_move(cfg, sprint_id, keys, journal=None, yes=False, dry_run=False):
    """Move issues into a sprint (POST sprint/{id}/issue, chunked, verified)."""
    return _do_move(cfg, keys, str(sprint_id), journal, yes, dry_run, "sprint.move")


def cmd_sprint_restore(cfg, journal_file, yes=False, dry_run=False):
    """Restore membership from a move journal (group by recorded sprint).

    Items recorded with empty ``from_sprint_ids`` (backlog-origin) go back to
    the backlog. Rank is NOT restored. Closed sprints cannot receive issues —
    the server rejects those with a clean error (exit 1, no blind retry).
    """
    try:
        with open(journal_file, encoding="utf-8") as f:
            journal = json.load(f)
    except (OSError, ValueError) as e:
        print(f"Error: cannot read journal {journal_file}: {e}", file=sys.stderr)
        sys.exit(2)
    items = journal.get("items") or []
    if not items:
        print(f"Error: journal {journal_file} has no items.", file=sys.stderr)
        sys.exit(2)
    groups = {}
    for it in items:
        from_ids = it.get("from_sprint_ids") or []
        dest = str(from_ids[0]) if from_ids else "backlog"
        groups.setdefault(dest, []).append(it["key"])
    plan = f"Restore {len(items)} issue(s) from {journal_file}"
    if dry_run:
        print(f"DRY-RUN — {plan}:")
        for dest, keys in sorted(groups.items()):
            print(f"  to {dest}: {', '.join(keys)}")
        return journal_file
    _confirm_or_exit(plan, yes, dry_run)
    # Closed-sprint guard: refuse destinations that are closed.
    for dest in groups:
        if dest != "backlog":
            sp = normalize_sprint(agile_get(cfg, f"sprint/{dest}"))
            if sp.get("state") == "CLOSED":
                print(f"Error: cannot restore to closed sprint {dest} "
                      f"({sp.get('name')}); move those issues manually.", file=sys.stderr)
                sys.exit(1)
    for dest, keys in sorted(groups.items()):
        _do_move(cfg, keys, dest, journal_file, True, False, "sprint.restore")
    print(f"{plan} — verified.")
    return journal_file


# -------------------------------------------------------------------
# F6 permissions
# -------------------------------------------------------------------

def cmd_permissions(cfg, project, check=(), fmt="table"):
    """Check project permissions (GET /rest/api/2/mypermissions)."""
    params = {}
    if project:
        params["projectKey"] = project
    if check:
        params["permissions"] = ",".join(check)
    data = jira_get(cfg, "mypermissions", params or None)
    perms = data.get("permissions") or {}
    out = {name: bool((info or {}).get("havePermission")) for name, info in perms.items()}
    for name in check or ():
        out.setdefault(name, False)
    if fmt == "json":
        _print_json(out)
        return out
    for name in sorted(out):
        print(f"  {name:30}  {'yes' if out[name] else 'no'}")
    return out


CAPABILITY_FEATURES = [
    "search.paging",
    "search.changelog",
    "issue.changelog",
    "agile.read",
    "sprint.current",
    "backlog.move",
    "sprint.restore",
    "permissions.check",
    "fields.story_points",
]


def cmd_capabilities(cfg, project=None, fmt="table"):
    """Describe server flavor/version, feature list, and resolved field IDs (F7)."""
    from jira_cli import __version__
    from jira_cli.fields import get_custom_field_ids
    from jira_cli.http import jira_get as _jg

    jira_version = ""
    flavor = "server"
    try:
        info = _jg(cfg, "serverInfo")
        jira_version = str(info.get("version") or "")
        deployment = str(info.get("deploymentType") or "").strip().lower()
        flavor = "cloud" if deployment == "cloud" else "server"
    except Exception:
        pass
    try:
        from jira_cli.http import get_write_api_version, ensure_api_version_detected
        ensure_api_version_detected(cfg)
        if (get_write_api_version() or 2) == 3:
            flavor = "cloud"
    except Exception:
        pass
    try:
        resolved = get_custom_field_ids(cfg, project)
    except Exception:
        resolved = {"story_points": None, "sprint": None, "epic_link": None}
    out = {"version": __version__, "flavor": flavor, "jira_version": jira_version,
           "features": list(CAPABILITY_FEATURES),
           "resolved_fields": {"story_points": resolved.get("story_points"),
                               "sprint": resolved.get("sprint"),
                               "epic_link": resolved.get("epic_link")}}
    if fmt == "json":
        _print_json(out)
        return out
    print(f"  jira-cli {__version__} ({flavor}, Jira {jira_version or 'unknown'})")
    print(f"  features: {', '.join(CAPABILITY_FEATURES)}")
    print(f"  fields: story_points={resolved.get('story_points')} "
          f"sprint={resolved.get('sprint')} epic_link={resolved.get('epic_link')}")
    return out
