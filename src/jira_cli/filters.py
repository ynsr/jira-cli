"""Saved filter definitions and JQL combination logic."""

import re
import sys

FILTER_ALIASES = {
    "my": "my-issues",  # backward compat
}

FILTERS = {
    "my-issues": {
        "jql": 'assignee=currentUser() AND resolution=Unresolved ORDER BY priority DESC, created DESC',
        "desc": "Your unresolved issues",
    },
    "active-sprint": {
        "jql": 'assignee=currentUser() AND sprint in openSprints() AND resolution=Unresolved ORDER BY priority DESC',
        "desc": "Your issues in the active sprint",
    },
    "todo": {
        "jql": 'assignee=currentUser() AND status="To Do" ORDER BY priority DESC',
        "desc": "Your To Do issues",
    },
    "in-progress": {
        "jql": 'assignee=currentUser() AND status="In Progress" ORDER BY priority DESC',
        "desc": "Your In Progress issues",
    },
    "blocked": {
        "jql": 'assignee=currentUser() AND status=Blocked ORDER BY priority DESC',
        "desc": "Your Blocked issues",
    },
    "unresolved": {
        "jql": 'resolution=Unresolved ORDER BY priority DESC, created DESC',
        "desc": "All unresolved issues",
    },
    "recent": {
        "jql": 'ORDER BY updated DESC',
        "desc": "Recently updated issues",
    },
}


def resolve_filter(name):
    """Resolve a filter name, following aliases. Returns canonical name or None."""
    n = name.strip()
    if n in FILTERS:
        return n
    if n in FILTER_ALIASES:
        return FILTER_ALIASES[n]
    return None


def combine_filters(names):
    """
    Given a list of filter name strings (each may contain +), AND-join their JQL.
    Only the last ORDER BY among all filters is kept.
    """
    clauses = []
    order_by = None

    for raw in names:
        for part in raw.split("+"):
            part = part.strip()
            fn = resolve_filter(part)
            if not fn or fn not in FILTERS:
                print(f"Unknown filter: {part}", file=sys.stderr)
                print(f"Available: {', '.join(sorted(FILTERS.keys()))}", file=sys.stderr)
                sys.exit(1)
            jql = FILTERS[fn]["jql"]
            m = re.search(r'\bORDER\s+BY\s+.*', jql, re.IGNORECASE)
            if m:
                clause = jql[:m.start()].strip()
                order_by = m.group(0)
            else:
                clause = jql.strip()
            if clause:
                clauses.append(clause)

    if not clauses:
        return ""
    combined = " AND ".join(clauses)
    if order_by:
        combined += f" {order_by}"
    return combined
