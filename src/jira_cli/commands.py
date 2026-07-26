"""All command implementations for jira-cli."""

import json
import sys

from jira_cli.config import load_config, save_config
from jira_cli.http import jira_get, jira_post, jira_put
from jira_cli.format import fmt_date, status_badge, priority_label, extract_adf_text, truncate
from jira_cli.help_texts import print_help

CONFIG_PATH = __import__("jira_cli.config", fromlist=[""]).CONFIG_PATH


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


# -------------------------------------------------------------------
# Command: search
# -------------------------------------------------------------------

def cmd_search(cfg, jql, limit=20, fmt="table"):
    """Search issues with JQL. fmt: table|json."""
    params = {
        "jql": jql,
        "maxResults": limit,
        "fields": "summary,status,priority,assignee,created,updated,issuetype,reporter",
    }
    data = jira_get(cfg, "search", params)
    issues = data.get("issues", [])
    total = data.get("total", 0)

    if not issues:
        print("No issues found.")
        return
    if fmt == "json":
        print(json.dumps(issues, indent=2))
        return

    print(f"\n\033[1mQuery:\033[0m {jql}")
    print(f"\033[1mTotal: {total} issues (showing {len(issues)})\033[0m\n")
    for iss in issues:
        key = iss["key"]
        f = iss.get("fields", {})
        summary = f.get("summary", "")[:70]
        status = f.get("status", {}).get("name", "")
        priority = f.get("priority", {})
        assignee = f.get("assignee", {}) or {}
        assignee_name = assignee.get("displayName", "Unassigned")
        created = fmt_date(f.get("created", ""))
        pname = priority.get("name", "") if priority else ""
        print(f"  \033[1m{key}\033[0m  {status_badge(status):20} {pname:10} {assignee_name:20} {created}")
        print(f"       {summary}")
        print()


# -------------------------------------------------------------------
# Command: issue (+ sub-commands)
# -------------------------------------------------------------------

def cmd_issue(cfg, issue_key):
    """Show issue detail with the latest comment."""
    data = jira_get(cfg, f"issue/{issue_key}")
    f = data.get("fields", {})

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

    # Latest comment only (fetch via comments API, last item)
    cmts_data = jira_get(cfg, f"issue/{issue_key}/comment", {"maxResults": 50, "startAt": 0})
    comments = cmts_data.get("comments", [])
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

    if not comments:
        print("No comments found.")
        return
    if fmt == "json":
        print(json.dumps(comments, indent=2))
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


def cmd_issue_comment(cfg, issue_key, comment_id, fmt="table"):
    """Show full detail for a single comment."""
    data = jira_get(cfg, f"issue/{issue_key}/comment/{comment_id}")
    author = data.get("author", {}).get("displayName", "")
    created_c = fmt_date(data.get("created", ""))
    updated_c = fmt_date(data.get("updated", ""))
    body = extract_adf_text(data.get("body", "")) or ""

    if fmt == "json":
        print(json.dumps(data, indent=2))
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

    # For self-hosted Jira, plain text body is accepted
    data = jira_post(cfg, f"issue/{issue_key}/comment", {"body": body_text})
    cid = data.get("id", "?")
    created_c = fmt_date(data.get("created", ""))
    print(f"\n\033[1mComment #{cid} added to {issue_key}\033[0m")
    print(f"  \033[38;5;244mCreated: {created_c}\033[0m")
    print()



# -------------------------------------------------------------------
# Command: issue update-description
# -------------------------------------------------------------------

def cmd_issue_update_description(cfg, issue_key, description):
    """Update the description of an issue (ADF format)."""
    from jira_cli.format import _build_adf_doc

    data = {"update": {"description": [{"set": _build_adf_doc(description)}]}}
    result = jira_put(cfg, f"issue/{issue_key}", data)
    print(f"\n\033[1mDescription updated for {issue_key}\033[0m")
    return result


# -------------------------------------------------------------------
# Command: issue transition (update status)
# -------------------------------------------------------------------

def cmd_issue_update_status(cfg, issue_key, transition_id_or_name):
    """Transition an issue to a new status."""
    # Try numeric transition ID first, then name
    data = {"transition": {"id": transition_id_or_name}}
    result = jira_post(cfg, f"issue/{issue_key}/transitions", data)
    print(f"\n\033[1mTransition applied to {issue_key}\033[0m")
    return result


# -------------------------------------------------------------------
# Command: issue assign
# -------------------------------------------------------------------

def cmd_issue_assign(cfg, issue_key, assignee):
    """Assign an issue to a user (by name). Use empty string to unassign."""
    data = {"name": assignee}
    result = jira_put(cfg, f"issue/{issue_key}/assignee", data)
    name_display = assignee or "Unassigned"
    print(f"\n\033[1m{issue_key} assigned to {name_display}\033[0m")
    return result

# -------------------------------------------------------------------
# Command: issue edit-comment
# -------------------------------------------------------------------

def cmd_issue_update_comment(cfg, issue_key, comment_id, body_text):
    """Update/replace the body of an existing comment."""
    if not body_text:
        print("Error: comment body is empty.", file=sys.stderr)
        sys.exit(1)

    data = {"body": body_text}
    result = jira_put(cfg, f"issue/{issue_key}/comment/{comment_id}", data)
    updated_c = fmt_date(result.get("updated", ""))
    print(f"\n\033[1mComment #{comment_id} updated on {issue_key}\033[0m")
    return result

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
