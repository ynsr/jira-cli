"""All command implementations for jira-cli."""

import json
import os
import sys

from jira_cli.config import load_config, save_config
from jira_cli.http import (
    ensure_api_version_detected,
    description_body,
    comment_body,
    jira_get, jira_post, jira_put, jira_post_attachment,
    jira_get_binary, jira_delete_attachment,
)
from jira_cli.format import fmt_date, status_badge, priority_label, extract_adf_text, truncate
from jira_cli.fields import extract_agile_fields
from jira_cli.help_texts import print_help

CONFIG_PATH = __import__("jira_cli.config", fromlist=[""]).CONFIG_PATH


def guard_destructive(action, method, path, payload=None, yes=False, dry_run=False):
    """Gate destructive API calls. Returns True to proceed, False on dry-run.

    --dry-run prints the request that would be sent (no network call).
    Otherwise --yes is required to execute: on a TTY the user is prompted,
    in a non-interactive session the command fails with an actionable message.
    """
    if dry_run:
        print("DRY-RUN — request that would be sent:")
        print(f"  {method} {path}")
        if payload is not None:
            print(f"  payload: {json.dumps(payload, indent=2)}")
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
    print(f"Error: {action} is destructive. Re-run with --yes to execute or --dry-run to preview.", file=sys.stderr)
    sys.exit(2)


# -------------------------------------------------------------------
# Command: projects
# -------------------------------------------------------------------

def cmd_projects(cfg):
    """List all projects."""
    data = jira_get(cfg, "project")
    print(f"\n{'Key':15} {'Name':40} {'Lead':20} {'Type':10}")
    print("-" * 85)
    for p in sorted(data, key=lambda x: x["key"]):
        lead = p.get("lead", {}).get("displayName", "")
        ptype = p.get("projectTypeKey", "")
        print(f"{p['key']:15} {p['name']:40} {lead:20} {ptype:10}")
    print(f"\n\033[1m{len(data)} projects\033[0m")


def _project_for_field_cache(jql=None, issues=(), issue_key=None):
    """Best-effort project key for the field-ID cache scope.

    From an explicit issue key, else the first issue's project/key, else a
    ``project=X`` token in the JQL, else ``"global"``.
    """
    if issue_key and "-" in issue_key:
        return issue_key.split("-", 1)[0].upper()
    for iss in issues or []:
        proj = ((iss.get("fields") or {}).get("project") or {}).get("key")
        if proj:
            return str(proj).upper()
        key = iss.get("key") or ""
        if "-" in key:
            return key.split("-", 1)[0].upper()
    import re as _re

    m = _re.search(r"project\s*=\s*([A-Za-z0-9_]+)", jql or "")
    if m:
        return m.group(1).upper()
    return "global"


def _agile_json_fields(fields, cfg=None, project=None):
    """Curated agile keys merged into search JSON payloads (no-op when absent)."""
    agile = extract_agile_fields(fields or {}, cfg, project)
    out = {}
    if agile["resolution"] is not None and not isinstance((fields or {}).get("resolution"), dict):
        out["resolution"] = agile["resolution"]
    if agile["story_points"] is not None:
        out["story_points"] = agile["story_points"]
    if agile["sprint"]:
        out["sprint"] = agile["sprint"]
    if agile["sprints"]:
        out["sprints"] = agile["sprints"]
    if agile["epic_key"] is not None:
        out["epic_key"] = agile["epic_key"]
    return out


def _agile_table_suffix(agile):
    """Compact one-line 'Resolution: X | SP: N | Sprint: Y' suffix ('' when empty)."""
    parts = []
    if agile.get("resolution"):
        parts.append(f"Resolution: {agile['resolution']}")
    if agile.get("story_points") is not None:
        parts.append(f"SP: {agile['story_points']}")
    if agile.get("sprint"):
        parts.append(f"Sprint: {', '.join(agile['sprint'])}")
    return " | ".join(parts)


def _search_pages(cfg, jql, start_at=0, limit=20, fetch_all=False,
                  max_results=1000, fields=None, expand=None):
    """Yield ``(issues, total)`` pages from ``GET search`` (auto-paginate with --all).

    Single page: ``startAt=start_at, maxResults=limit``. With ``fetch_all``,
    pages use the server page size (first response's ``maxResults``, fallback
    50) and stop at ``total`` or ``max_results``. Returns first-page total.
    """
    base_fields = ("summary,status,priority,assignee,created,updated,"
                   "issuetype,reporter,resolution,*navigable")
    page_size = limit
    start = max(0, start_at)
    collected = []
    total = 0
    first = True
    while True:
        params = {"jql": jql, "startAt": start, "maxResults": page_size,
                  "fields": fields or base_fields}
        if expand:
            params["expand"] = ",".join(expand)
        data = jira_get(cfg, "search", params)
        batch = data.get("issues", [])
        total = data.get("total", 0)
        collected.extend(batch)
        if not fetch_all:
            return collected, total
        if first:
            first = False
            try:
                page_size = max(1, int(data.get("maxResults") or 50))
            except (TypeError, ValueError):
                page_size = 50
            page_size = min(page_size, max(1, max_results))
        start += len(batch)
        if not batch or start >= total or len(collected) >= max_results:
            return collected[:max_results], total


def cmd_search(cfg, jql, limit=20, fmt="table", start_at=0, fetch_all=False,
               max_results=1000, fields=None, expand=None, envelope=False,
               changelog_fields=None):
    """Search issues with JQL. fmt: table|json.

    ``fetch_all`` auto-paginates (capped by ``max_results``); ``envelope``
    wraps JSON as ``{total,start_at,returned,next_start_at,issues}``.
    ``changelog_fields`` attaches filtered ``changelog`` entries per issue
    (requires ``changelog`` in ``expand``); truncated inline histories are
    backfilled via ``GET issue/K/changelog``.
    """
    from jira_cli.changelog import (iter_full_histories, normalize_histories,
                                    parse_changelog_fields_arg)

    issues, total = _search_pages(cfg, jql, start_at, limit, fetch_all,
                                  max_results, fields, expand)
    want_changelog = expand and "changelog" in [e.strip().lower() for e in expand]
    clog_wanted = parse_changelog_fields_arg(changelog_fields) if want_changelog else None
    proj = _project_for_field_cache(jql=jql, issues=issues)
    for iss in issues:
        iss.setdefault("fields", {}).update(
            _agile_json_fields(iss.get("fields", {}), cfg, proj))
        if want_changelog and clog_wanted is not None:
            block = iss.get("changelog") or {}
            histories = list(iter_full_histories(cfg, iss.get("key", ""), block, jira_get))
            iss["changelog"] = normalize_histories(histories, clog_wanted)

    if fmt == "json":
        if envelope:
            returned = len(issues)
            nxt = start_at + returned
            payload = {"total": total, "start_at": start_at,
                       "returned": returned,
                       "next_start_at": nxt if nxt < total else None,
                       "issues": issues}
        else:
            payload = issues
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return payload if envelope else issues
    if not issues:
        print("No issues found.")
        return []

    print(f"\n\033[1mQuery:\033[0m {jql}")
    print(f"\033[1mTotal: {total} issues (showing {len(issues)})\033[0m\n")
    for iss in issues:
        key = iss["key"]
        f = iss.get("fields", {})
        agile = extract_agile_fields(f, cfg, _project_for_field_cache(jql=jql, issues=issues))
        summary = f.get("summary", "")[:70]
        status = f.get("status", {}).get("name", "")
        priority = f.get("priority", {})
        assignee = f.get("assignee", {}) or {}
        assignee_name = assignee.get("displayName", "Unassigned")
        created = fmt_date(f.get("created", ""))
        pname = priority.get("name", "") if priority else ""
        print(f"  \033[1m{key}\033[0m  {status_badge(status):20} {pname:10} {assignee_name:20} {created}")
        print(f"       {summary}")
        extra = _agile_table_suffix(agile)
        if extra:
            print(f"       \033[38;5;244m{extra}\033[0m")
        print()


# -------------------------------------------------------------------
# Command: issue (+ sub-commands)
# -------------------------------------------------------------------

def cmd_issue(cfg, issue_key, fmt="table", include_raw=False):
    """Show issue detail with the latest comment (table) or full JSON view."""
    data = jira_get(cfg, f"issue/{issue_key}")
    f = data.get("fields", {})
    cmts_data = jira_get(cfg, f"issue/{issue_key}/comment", {"maxResults": 50, "startAt": 0})
    comments = cmts_data.get("comments", [])

    if fmt == "json":
        agile = extract_agile_fields(f, cfg, _project_for_field_cache(issue_key=issue_key, issues=[data]))
        out = {
            "key": data.get("key", issue_key),
            "summary": f.get("summary", ""),
            "description": extract_adf_text(f.get("description")),
            "status": f.get("status") or {},
            "priority": f.get("priority") or {},
            "issuetype": f.get("issuetype") or {},
            "assignee": f.get("assignee") or {},
            "reporter": f.get("reporter") or {},
            "created": f.get("created", ""),
            "updated": f.get("updated", ""),
            "project": f.get("project") or {},
            "labels": f.get("labels") or [],
            "resolution": agile["resolution"],
            "story_points": agile["story_points"],
            "sprint": agile["sprint"],
            "sprints": agile["sprints"],
            "epic_key": agile["epic_key"],
            "comments": [
                {
                    "id": c.get("id", ""),
                    "author": (c.get("author") or {}).get("displayName", ""),
                    "created": c.get("created", ""),
                    "updated": c.get("updated", ""),
                    "body": extract_adf_text(c.get("body")),
                }
                for c in comments
            ],
        }
        if include_raw:
            out["raw"] = data
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return

    print(f"\n\033[1m{'='*60}\033[0m")
    print(f"  \033[1m{data['key']}\033[0m  {f.get('summary','')}")
    print(f"\033[1m{'='*60}\033[0m")

    status = f.get("status", {}).get("name", "")
    priority = f.get("priority", {}).get("name", "")
    issuetype = f.get("issuetype", {}).get("name", "")
    assignee = (f.get("assignee") or {}).get("displayName", "Unassigned")
    reporter = (f.get("reporter") or {}).get("displayName", "")
    created = fmt_date(f.get("created", ""))
    updated = fmt_date(f.get("updated", ""))

    print(f"  Status:    {status_badge(status):20}  Priority: {priority_label(f.get('priority', {}))}")
    print(f"  Type:      {issuetype}")
    print(f"  Assignee:  {assignee}")
    print(f"  Reporter:  {reporter}")
    print(f"  Created:   {created}")
    print(f"  Updated:   {updated}")
    print(f"  Project:   {f.get('project', {}).get('name','')} ({f.get('project', {}).get('key','')})")
    agile = extract_agile_fields(f, cfg, _project_for_field_cache(issue_key=issue_key, issues=[data]))
    if agile["resolution"]:
        print(f"  Resolution: {agile['resolution']}")
    if agile["story_points"] is not None:
        print(f"  Story Points: {agile['story_points']}")
    if agile["sprint"]:
        print(f"  Sprint:    {', '.join(agile['sprint'])}")

    desc = f.get("description")
    if desc:
        print(f"\n  \033[1mDescription:\033[0m")
        text = extract_adf_text(desc)
        if text:
            for line in text.strip().split("\n"):
                print(f"    {line}")

    rf = data.get("renderedFields")
    if rf and rf.get("description"):
        print(f"\n  \033[1mDescription (rendered):\033[0m")
        print(f"    {rf['description']}")

    if comments:
        latest = comments[-1]
        author = latest.get("author", {}).get("displayName", "")
        created_c = fmt_date(latest.get("created", ""))
        body = extract_adf_text(latest.get("body", "")) or ""
        print(f"\n  \033[1mLatest comment \u2014 {author} ({created_c}):\033[0m")
        print(f"    {truncate(body, 300)}")
        if len(comments) > 1:
            print(f"    \033[38;5;244m(+ {len(comments) - 1} more \u2014 use 'issue {issue_key} comments' to see all)\033[0m")
    print()


def cmd_issue_comments(cfg, issue_key, limit=5, page=1, desc=False, fmt="table"):
    """Paginated comment list with truncated text."""
    start_at = max(0, (page - 1) * limit)
    params = {"maxResults": limit, "startAt": start_at}
    data = jira_get(cfg, f"issue/{issue_key}/comment", params)
    comments = data.get("comments", [])
    total = data.get("total", 0)

    if fmt == "json":
        print(json.dumps(comments, indent=2, ensure_ascii=False))
        return
    if not comments:
        print("No comments found.")
        return

    # Sort: most recent last unless --desc
    if desc:
        comments = list(reversed(comments))

    print(f"\n\033[1mComments for {issue_key}\033[0m ({total} total, showing page {page})")
    print()
    for c in comments:
        author = c.get("author", {}).get("displayName", "")
        created_c = fmt_date(c.get("created", ""))
        cid = c.get("id", "")
        body = extract_adf_text(c.get("body", "")) or ""
        print(f"  \033[1m#{cid}\033[0m  \033[38;5;244m{author} \u2014 {created_c}\033[0m")
        print(f"       {truncate(body)}")
        print()


def cmd_issue_changelog(cfg, issue_key, changelog_fields=None, since=None, fmt="table"):
    """Normalized changelog entries for an issue: ``[{at,author,field,from,to}]``.

    Fetches ``GET issue/K?expand=changelog`` (inline histories) and backfills
    truncated pages via ``GET issue/K/changelog``. ``since`` filters by date
    (``YYYY-MM-DD`` prefix or full timestamp). Table mode prints one line per
    entry; JSON prints the entry list.
    """
    from jira_cli.changelog import (iter_full_histories, normalize_histories,
                                    parse_changelog_fields_arg, _parse_since)

    wanted = parse_changelog_fields_arg(changelog_fields)
    since_cmp = _parse_since(since) if since else ""
    if since and not since_cmp:
        print(f"Error: invalid --since date: {since!r} (use YYYY-MM-DD).", file=sys.stderr)
        sys.exit(2)
    data = jira_get(cfg, f"issue/{issue_key}", {"expand": "changelog"})
    block = data.get("changelog") or {}
    histories = list(iter_full_histories(cfg, issue_key, block, jira_get))
    entries = normalize_histories(histories, wanted, since_cmp or None)
    if fmt == "json":
        print(json.dumps(entries, indent=2, ensure_ascii=False))
        return entries
    if not entries:
        print(f"No changelog entries for {issue_key}.")
        return []
    print(f"\n\033[1mChangelog for {issue_key}\033[0m ({len(entries)} entries)")
    print()
    for e in entries:
        print(f"  \033[38;5;244m{e['at'][:10]} {e['author']}\033[0m  {e['field']}: {e['from']!r} \u2192 {e['to']!r}")
    print()
    return entries


def cmd_issue_comment(cfg, issue_key, comment_id, fmt="table"):
    """Show full detail for a single comment."""
    data = jira_get(cfg, f"issue/{issue_key}/comment/{comment_id}")
    author = data.get("author", {}).get("displayName", "")
    created_c = fmt_date(data.get("created", ""))
    updated_c = fmt_date(data.get("updated", ""))
    body = extract_adf_text(data.get("body", "")) or ""

    if fmt == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    print(f"\n\033[1mComment #{data.get('id', '')} on {issue_key}\033[0m")
    print(f"  \033[38;5;244mAuthor:   {author}\033[0m")
    print(f"  \033[38;5;244mCreated:  {created_c}\033[0m")
    print(f"  \033[38;5;244mUpdated:  {updated_c}\033[0m")
    print(f"\n  \033[1mBody:\033[0m")
    for line in body.strip().split("\n"):
        print(f"    {line}")
    print()


def cmd_issue_add_comment(cfg, issue_key, body_text):
    """Add a comment to an issue."""
    if not body_text:
        # Read from stdin until EOF
        print("Enter comment body (Ctrl+D when done):", file=sys.stderr)
        body_text = sys.stdin.read().strip()
        if not body_text:
            print("Error: comment body is empty.", file=sys.stderr)
            sys.exit(1)

    ensure_api_version_detected(cfg)
    # v2 (Server/DC): plain text body; v3 (Cloud): ADF document
    data = jira_post(cfg, f"issue/{issue_key}/comment", {"body": comment_body(body_text)})
    cid = data.get("id", "?")
    created_c = fmt_date(data.get("created", ""))
    print(f"\n\033[1mComment #{cid} added to {issue_key}\033[0m")
    print(f"  \033[38;5;244mCreated: {created_c}\033[0m")
    print()



# -------------------------------------------------------------------
# Command: issue transition (update status)
# -------------------------------------------------------------------

def cmd_issue_update_status(cfg, issue_key, transition_id_or_name,
                            yes=False, dry_run=False):
    """Transition an issue to a new status."""
    # Try numeric transition ID first, then name
    data = {"transition": {"id": transition_id_or_name}}
    if not guard_destructive(
        f"Transition {issue_key} to '{transition_id_or_name}'",
        "POST", f"issue/{issue_key}/transitions", data, yes, dry_run,
    ):
        return None
    result = jira_post(cfg, f"issue/{issue_key}/transitions", data)
    print(f"\n\033[1mTransition applied to {issue_key}\033[0m")
    return result


# -------------------------------------------------------------------
# Command: issue edit-comment
# -------------------------------------------------------------------

def cmd_issue_update_comment(cfg, issue_key, comment_id, body_text,
                             yes=False, dry_run=False):
    """Update/replace the body of an existing comment."""
    if not body_text:
        print("Error: comment body is empty.", file=sys.stderr)
        sys.exit(1)

    ensure_api_version_detected(cfg)
    data = {"body": comment_body(body_text)}
    if not guard_destructive(
        f"Edit comment #{comment_id} on {issue_key}",
        "PUT", f"issue/{issue_key}/comment/{comment_id}", data, yes, dry_run,
    ):
        return None
    result = jira_put(cfg, f"issue/{issue_key}/comment/{comment_id}", data)
    updated_c = fmt_date(result.get("updated", ""))
    print(f"\n\033[1mComment #{comment_id} updated on {issue_key}\033[0m")
    return result

# -------------------------------------------------------------------
# Command: create issue
# -------------------------------------------------------------------

def cmd_create_issue(cfg, project, summary, issue_type="Task", description=None,
                     priority=None, assignee=None, fmt="table"):
    """Create a new issue. Returns the created issue dict."""
    ensure_api_version_detected(cfg)

    fields = {
        "project": {"key": project},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }
    if description is not None:
        fields["description"] = description_body(description)
    if priority:
        fields["priority"] = {"name": priority}
    if assignee is not None:
        # Empty string means unassigned; otherwise assign by name.
        fields["assignee"] = {"name": assignee}

    data = jira_post(cfg, "issue", {"fields": fields})
    key = data.get("key", "?")
    if fmt == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return data
    print(f"\n\033[1mCreated \033[0m\033[1m{key}\033[0m")
    print(f"  {cfg['url']}/browse/{key}")
    return data


# -------------------------------------------------------------------
# Command: link issues
# -------------------------------------------------------------------

def cmd_link_issues(cfg, outward_key, inward_key, link_type="Relates", comment=None):
    """Create a link between two issues. Returns {} on success."""
    ensure_api_version_detected(cfg)

    payload = {
        "type": {"name": link_type},
        "inwardIssue": {"key": inward_key},
        "outwardIssue": {"key": outward_key},
    }
    if comment:
        payload["comment"] = {"body": comment_body(comment)}

    result = jira_post(cfg, "issueLink", payload)
    print(f"\n\033[1mLinked {outward_key} \u2194 {inward_key} ({link_type})\033[0m")
    return result


# -------------------------------------------------------------------
# Command: issue update (general field update)
# -------------------------------------------------------------------

def cmd_issue_update(cfg, issue_key, summary=None, description=None,
                     priority=None, assignee=None, yes=False, dry_run=False):
    """Update editable fields of an issue (summary/description/priority/assignee)."""
    ensure_api_version_detected(cfg)

    fields = {}
    if summary is not None:
        fields["summary"] = summary
    if description is not None:
        fields["description"] = description_body(description)
    if priority is not None:
        fields["priority"] = {"name": priority}
    if assignee is not None:
        fields["assignee"] = {"name": assignee}

    if not fields:
        print("Error: nothing to update. Use --summary, --description, --priority, or --assignee.", file=sys.stderr)
        sys.exit(1)

    if not guard_destructive(
        f"Update {issue_key}",
        "PUT", f"issue/{issue_key}", {"fields": fields}, yes, dry_run,
    ):
        return None
    result = jira_put(cfg, f"issue/{issue_key}", {"fields": fields})
    changed = ", ".join(fields.keys())
    print(f"\n\033[1mUpdated {issue_key}: {changed}\033[0m")
    return result

# -------------------------------------------------------------------
# Command: issue attach
# -------------------------------------------------------------------

def cmd_issue_attach(cfg, issue_key, files):
    """Upload one or more files as attachments to an issue."""
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        print(f"Error: file not found: {missing[0]}", file=sys.stderr)
        sys.exit(1)

    attachments = jira_post_attachment(cfg, issue_key, files)
    if not isinstance(attachments, list):
        attachments = []

    print(f"\n\033[1mAttached to {issue_key}:\033[0m")
    for att in attachments:
        print(f"  \033[1m{att.get('filename', '?')}\033[0m  id={att.get('id', '?')}  {att.get('size', 0)} bytes")
    print()
    return attachments

# -------------------------------------------------------------------
# Command: issue attachments (list)
# -------------------------------------------------------------------

def _get_attachments_meta(cfg, issue_key):
    """Return the list of attachment objects for an issue."""
    data = jira_get(cfg, f"issue/{issue_key}", {"fields": "attachment"})
    return (data.get("fields") or {}).get("attachment") or []


def cmd_issue_attachments(cfg, issue_key, fmt="table"):
    """List attachments of an issue."""
    attachments = _get_attachments_meta(cfg, issue_key)
    if not attachments:
        print("No attachments.")
        return []

    if fmt == "json":
        print(json.dumps(attachments, indent=2, ensure_ascii=False))
        return attachments

    print(f"\n\033[1mAttachments for {issue_key}\033[0m ({len(attachments)})")
    print()
    for a in attachments:
        author = (a.get("author") or {}).get("displayName", "")
        created_c = fmt_date(a.get("created", ""))
        size = a.get("size", 0)
        print(f"  \033[1m{a.get('id', '?')}\033[0m  {a.get('filename', '?')}  \033[38;5;244m{size} bytes  {author} \u2014 {created_c}\033[0m")
    print()
    return attachments


# -------------------------------------------------------------------
# Command: issue download attachments
# -------------------------------------------------------------------

def cmd_issue_download_attachment(cfg, issue_key, attachment_ids=None,
                                  dest_dir=".", all_attachments=False):
    """Download attachment(s) of an issue to dest_dir. Returns saved paths."""
    if all_attachments or not attachment_ids:
        metas = _get_attachments_meta(cfg, issue_key)
        if not metas:
            print("No attachments to download.")
            return []
    else:
        metas = [jira_get(cfg, f"attachment/{aid}") for aid in attachment_ids]

    os.makedirs(dest_dir, exist_ok=True)
    saved = []
    for meta in metas:
        filename = os.path.basename(meta.get("filename", "attachment"))
        content_url = meta.get("content")
        if not content_url:
            print(f"Error: no download URL for {filename}", file=sys.stderr)
            sys.exit(1)
        content = jira_get_binary(cfg, content_url)
        path = os.path.join(dest_dir, filename)
        with open(path, "wb") as f:
            f.write(content)
        saved.append(path)
        print(f"Downloaded {filename} ({len(content)} bytes) \u2192 {path}")
    return saved


# -------------------------------------------------------------------
# Command: issue delete attachments
# -------------------------------------------------------------------

def cmd_issue_delete_attachment(cfg, issue_key, attachment_ids=None,
                                all_attachments=False, yes=False, dry_run=False):
    """Delete attachment(s) of an issue. Returns list of deleted ids."""
    if all_attachments:
        ids = [a.get("id") for a in _get_attachments_meta(cfg, issue_key)]
    else:
        ids = list(attachment_ids or [])

    if not ids:
        print("No attachments to delete.")
        return []

    if not guard_destructive(
        f"Delete {len(ids)} attachment(s) from {issue_key}",
        "DELETE", f"attachment/{{id}} for ids: {', '.join(str(i) for i in ids)}",
        {"attachment_ids": ids}, yes, dry_run,
    ):
        return None

    deleted = []
    for aid in ids:
        jira_delete_attachment(cfg, aid)
        deleted.append(aid)
        print(f"Deleted attachment {aid} from {issue_key}")
    return deleted

# -------------------------------------------------------------------
# Command: setup
# -------------------------------------------------------------------

def cmd_setup(cfg):
    """Configure Jira credentials interactively."""
    default_url = cfg.get("url", "https://tribe.jibit.cloud")
    url = input(f"Jira URL [{default_url}]: ").strip()
    user = input(f"Username [{cfg.get('user', '')}]: ").strip()
    passwd = input("Password: ").strip()
    if not url:
        url = default_url
    if not user:
        user = cfg.get("user", "")
    if not passwd:
        passwd = cfg.get("pass", "")
    save_config(url, user, passwd)
    print("Env override: JIRA_URL, JIRA_USER, JIRA_PASS")
