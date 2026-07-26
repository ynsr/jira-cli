"""Flag parsing and JQL construction helpers."""


def parse_flags(args, known=()):
    """
    Scan args for --limit, --page, --format, --desc, --saved, --body flags.
    known: additional flags to accept (e.g. ('--body',)).
    Returns (remaining_args, dict).
    """
    limit = 20
    page = 1
    fmt = "table"
    desc = False
    saved = []
    body = None
    list_filters = False
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
        elif a == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
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
        else:
            rest.append(a)
            i += 1
    return rest, {"limit": limit, "page": page, "format": fmt, "desc": desc, "saved": saved, "body": body, "list_filters": list_filters}


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
