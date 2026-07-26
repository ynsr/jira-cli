#!/usr/bin/env python3
"""
Ad-hoc verification: jira-cli filters subcommand, issue sub-commands, -h, completion.
Now imports from the jira_cli package.

Usage:  python3 tests/test_jira_cli.py
"""

import sys
import io
import os

# Ensure the src directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from jira_cli.filters import FILTERS, FILTER_ALIASES, resolve_filter, combine_filters
from jira_cli.flags import parse_flags, has_help_flag, build_jql
from jira_cli.help_texts import HELP, print_help
from jira_cli.format import COMMENT_TRUNCATE, truncate, extract_adf_text, status_badge
from jira_cli.http import jira_post
from jira_cli.commands import (
    cmd_issue,
    cmd_issue_comments,
    cmd_issue_comment,
    cmd_issue_add_comment,
    cmd_projects,
    cmd_search,
)

PASS = 0
FAIL = 0


def check(label, ok):
    global PASS, FAIL
    if ok:
        print(f"  PASS  {label}")
        PASS += 1
    else:
        print(f"  FAIL  {label}")
        FAIL += 1


def test():
    print("=== jira-cli: filters + issue sub-commands ===\n")

    # 1 — 5 predefined filters
    for name in ["my-issues", "active-sprint", "todo", "in-progress", "blocked"]:
        check(f"FILTERS['{name}'] exists", name in FILTERS)

    # 2 — alias
    check("alias my \u2192 my-issues", resolve_filter("my") == "my-issues")
    check("identity roundtrip", resolve_filter("blocked") == "blocked")
    check("unknown returns None", resolve_filter("nope") is None)

    # 3 — combine_filters AND-join
    j = combine_filters(["my-issues", "in-progress"])
    check("AND: has assignee", "assignee=currentUser()" in j)
    check("AND: has resolution Unresolved", "resolution=Unresolved" in j)
    check("AND: has status In Progress", 'status="In Progress"' in j)
    check("AND: ORDER BY present", "ORDER BY" in j)
    check("AND: last ORDER BY wins (no created DESC)", "created DESC" not in j)

    # 4 — + syntax
    j = combine_filters(["my-issues+blocked"])
    check("+: resolution", "resolution=Unresolved" in j)
    check("+: blocked status", "status=Blocked" in j)

    # 5 — comma expansion (as done by cmd_filters before combine_filters)
    expanded = [x for fn in ["my-issues,in-progress"] for x in fn.split(",")]
    j = combine_filters(expanded)
    check("comma expansion: In Progress", 'status="In Progress"' in j)

    # 6 — active-sprint
    j = combine_filters(["active-sprint"])
    check("active-sprint: openSprints()", "sprint in openSprints()" in j)

    # 7 — blocked
    j = combine_filters(["blocked"])
    check("blocked: status=Blocked", "status=Blocked" in j)

    # 8 — build_jql
    j = build_jql(["todo"], ["project=BANKING"])
    check("build_jql saved+raw: project", "project=BANKING" in j)
    check("build_jql saved+raw: To Do", 'status="To Do"' in j)
    check("build_jql saved+raw: parens", j.startswith("("))

    j = build_jql([], ["project=BANKING", "ORDER BY", "created", "DESC"])
    check("build_jql raw only", j == "project=BANKING ORDER BY created DESC")

    j = build_jql(["blocked"], [])
    check("build_jql saved only", "status=Blocked" in j)

    # 9 — parse_flags
    r, f = parse_flags(["--saved", "my-issues,blocked", "--limit", "50", "--format", "json"])
    check("--saved count", len(f["saved"]) == 2)
    check("saved[0]=my-issues", f["saved"][0] == "my-issues")
    check("limit=50", f["limit"] == 50)
    check("format=json", f["format"] == "json")

    r, f = parse_flags(["--page", "3", "--desc", "--body", "hi world"])
    check("page=3", f["page"] == 3)
    check("desc=True", f["desc"] is True)
    check("body=hi world", f["body"] == "hi world")

    r, f = parse_flags([])
    check("default limit=20", f["limit"] == 20)
    check("default page=1", f["page"] == 1)
    check("default format=table", f["format"] == "table")
    check("default desc=False", f["desc"] is False)
    check("default saved=[]", f["saved"] == [])
    check("default body=None", f["body"] is None)

    # 10 — HELP texts
    for t in ["main", "search", "issue", "projects", "setup"]:
        check(f"HELP['{t}'] > 50 chars", len(HELP.get(t, "")) > 50)
    check("HELP[issue] has comment <ID>", "comment <ID>" in HELP["issue"])
    check("HELP[issue] has add-comment", "add-comment" in HELP["issue"])
    check("HELP[issue] has --limit flags", "--limit" in HELP["issue"])
    check("HELP[issue] has --desc flag", "--desc" in HELP["issue"])
    check("HELP[search] has --list-filters", "--list-filters" in HELP["search"])
    check("HELP[main] has completion", "completion" in HELP["main"])
    check("HELP[main] mentions -h", "-h" in HELP["main"])

    # 11 — print_help exists
    check("print_help() callable", callable(print_help))

    # 12 — has_help_flag
    check("--help detected", has_help_flag(["--help"]))
    check("-h detected", has_help_flag(["-h"]))
    check("no flag", not has_help_flag(["--limit", "5"]))
    check("mixed", not has_help_flag(["issue", "PROJ-123"]))
    check("both flags", has_help_flag(["-h", "test"]))
    check("help anywhere in list", has_help_flag(["search", "--limit", "5", "-h"]))

    # 13 — truncate
    check("COMMENT_TRUNCATE=250", COMMENT_TRUNCATE == 250)
    check("truncate short unchanged", truncate("hi") == "hi")
    long = "hello world " * 50
    t = truncate(long, 30)
    check("truncate long shortened", len(t) < len(long))
    check("truncate ends with \u2026", t.endswith("\u2026"))

    # 14 — ADF
    adf = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"text": "Hello", "type": "text"}]}]}
    check("ADF single para", extract_adf_text(adf) == "Hello")
    adf2 = {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"text": "L1", "type": "text"}]},
        {"type": "paragraph", "content": [{"text": "L2", "type": "text"}]}]}
    check("ADF multi para", extract_adf_text(adf2) == "L1\nL2")

    # 15 — jira_post function defined
    check("jira_post defined", callable(jira_post))

    # 16 — issue sub-command functions exist
    check("cmd_issue exists", callable(cmd_issue))
    check("cmd_issue_comments exists", callable(cmd_issue_comments))
    check("cmd_issue_comment exists", callable(cmd_issue_comment))
    check("cmd_issue_add_comment exists", callable(cmd_issue_add_comment))

    # 17 — parse_flags handles --list-filters
    r, f = parse_flags(["--list-filters"])
    check("--list-filters flag detected", f.get("list_filters") is True)
    r, f = parse_flags(["project=BANKING", "--limit", "5"])
    check("--list-filters false by default", f.get("list_filters") is False)

    # 18 — status_badge includes Blocked
    check("Blocked badge is red", "\033[38;5;196m" in status_badge("Blocked"))

    # 19 — completion subcommand: bash generates something
    from jira_cli.completion import cmd_completion
    check("cmd_completion callable", callable(cmd_completion))

    old_stdout = sys.stdout

    captured = io.StringIO()
    sys.stdout = captured
    try:
        cmd_completion("bash")
    except SystemExit:
        pass
    sys.stdout = old_stdout
    out = captured.getvalue()
    check("completion bash contains jira-cli", "jira-cli" in out)
    check("completion bash contains _init_completion", "_init_completion" in out)

    captured = io.StringIO()
    sys.stdout = captured
    try:
        cmd_completion("zsh")
    except SystemExit:
        pass
    sys.stdout = old_stdout
    out = captured.getvalue()
    check("completion zsh contains _arguments", "_arguments" in out)

    captured = io.StringIO()
    sys.stdout = captured
    try:
        cmd_completion("fish")
    except SystemExit:
        pass
    sys.stdout = old_stdout
    out = captured.getvalue()
    check("completion fish contains complete -c", "complete -c" in out)

    # 20 — CLI main dispatch handles -h via has_help_flag
    from jira_cli.cli import main
    check("main() callable", callable(main))

    print(f"\nResults: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(test())
