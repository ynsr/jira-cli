"""Flag parsing and JQL construction helpers."""


def parse_flags(args, known=()):
    """
    Scan args for --limit, --page, --start-at, --max-results, --all, --format,
    --json, --desc, --saved, --body, --include-raw, --fields, --expand,
    --envelope, --changelog-fields, --since, plus create/update flags
    (--project, --summary, --description, --type, --priority, --assignee,
    --link-type, --comment) and agile/move flags (--board, --state, --last,
    --sprint, --journal, --check).
    known: additional flags to accept (e.g. ('--body',)).
    Returns (remaining_args, dict).
    """
    limit = 20
    page = 1
    start_at = 0
    max_results = 1000
    fetch_all = False
    fmt = "table"
    desc = False
    saved = []
    body = None
    list_filters = False
    project = None
    summary = None
    description = None
    issue_type = None
    priority = None
    assignee = None
    link_type = None
    comment = None
    dir_ = None
    all_ = False
    include_raw = False
    yes = False
    dry_run = False
    fields = None
    expand = []
    envelope = False
    changelog_fields = None
    since = None
    board = None
    state = None
    last = None
    sprint = None
    journal = None
    check = []
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif a == "--page" and i + 1 < len(args):
            page = int(args[i + 1])
            i += 2
        elif a == "--start-at" and i + 1 < len(args):
            start_at = int(args[i + 1])
            i += 2
        elif a == "--max-results" and i + 1 < len(args):
            max_results = int(args[i + 1])
            i += 2
        elif a == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
        elif a == "--json":
            fmt = "json"
            i += 1
        elif a == "--desc":
            desc = True
            i += 1
        elif a == "--list-filters":
            list_filters = True
            i += 1
        elif a == "--saved" and i + 1 < len(args):
            for part in args[i + 1].split(","):
                part = part.strip()
                if part:
                    saved.append(part)
            i += 2
        elif a == "--body" and i + 1 < len(args):
            body = args[i + 1]
            i += 2
        elif a == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif a == "--summary" and i + 1 < len(args):
            summary = args[i + 1]
            i += 2
        elif a == "--description" and i + 1 < len(args):
            description = args[i + 1]
            i += 2
        elif a == "--type" and i + 1 < len(args):
            issue_type = args[i + 1]
            i += 2
        elif a == "--priority" and i + 1 < len(args):
            priority = args[i + 1]
            i += 2
        elif a == "--assignee" and i + 1 < len(args):
            assignee = args[i + 1]
            i += 2
        elif a == "--link-type" and i + 1 < len(args):
            link_type = args[i + 1]
            i += 2
        elif a == "--comment" and i + 1 < len(args):
            comment = args[i + 1]
            i += 2
        elif a == "--dir" and i + 1 < len(args):
            dir_ = args[i + 1]
            i += 2
        elif a == "--all":
            all_ = True
            i += 1
        elif a == "--include-raw":
            include_raw = True
            i += 1
        elif a == "--yes":
            yes = True
            i += 1
        elif a == "--dry-run":
            dry_run = True
            i += 1
        elif a == "--fields" and i + 1 < len(args):
            fields = args[i + 1]
            i += 2
        elif a == "--expand" and i + 1 < len(args):
            for part in args[i + 1].split(","):
                part = part.strip()
                if part:
                    expand.append(part)
            i += 2
        elif a == "--envelope":
            envelope = True
            i += 1
        elif a == "--changelog-fields" and i + 1 < len(args):
            changelog_fields = args[i + 1]
            i += 2
        elif a == "--since" and i + 1 < len(args):
            since = args[i + 1]
            i += 2
        elif a == "--board" and i + 1 < len(args):
            board = args[i + 1]
            i += 2
        elif a == "--state" and i + 1 < len(args):
            state = args[i + 1]
            i += 2
        elif a == "--last" and i + 1 < len(args):
            last = int(args[i + 1])
            i += 2
        elif a == "--sprint" and i + 1 < len(args):
            sprint = args[i + 1]
            i += 2
        elif a == "--journal" and i + 1 < len(args):
            journal = args[i + 1]
            i += 2
        elif a == "--check" and i + 1 < len(args):
            for part in args[i + 1].split(","):
                part = part.strip()
                if part:
                    check.append(part)
            i += 2
        else:
            rest.append(a)
            i += 1
    return rest, {
        "limit": limit, "page": page, "start_at": start_at,
        "max_results": max_results, "format": fmt, "desc": desc, "saved": saved,
        "body": body, "list_filters": list_filters, "project": project,
        "summary": summary, "description": description, "type": issue_type,
        "priority": priority, "assignee": assignee, "link_type": link_type,
        "comment": comment, "dir": dir_, "all": all_, "include_raw": include_raw,
        "yes": yes, "dry_run": dry_run, "fields": fields, "expand": expand,
        "envelope": envelope, "changelog_fields": changelog_fields,
        "since": since, "board": board, "state": state, "last": last,
        "sprint": sprint, "journal": journal, "check": check,
    }


def has_help_flag(args):
    """Check if --help or -h is in args."""
    return "--help" in args or "-h" in args


def build_jql(saved_filters, raw_parts):
    """Build a final JQL from saved filter names and raw JQL fragments. AND-joined."""
    from jira_cli.filters import combine_filters

    jql = None
    if saved_filters:
        jql = combine_filters(saved_filters)
    if raw_parts:
        raw = " ".join(raw_parts)
        if jql:
            jql = f"({jql}) AND ({raw})"
        else:
            jql = raw
    return jql
