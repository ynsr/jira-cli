"""CLI dispatcher — main entry point for jira-cli."""

import sys

from jira_cli.config import load_config
from jira_cli.help_texts import print_help
from jira_cli.flags import parse_flags, has_help_flag, build_jql
from jira_cli.filters import FILTERS
from jira_cli.commands import (
    cmd_projects,
    cmd_search,
    cmd_issue,
    cmd_issue_comments,
    cmd_issue_comment,
    cmd_issue_add_comment,
    cmd_setup,
    cmd_issue_update_description,
    cmd_issue_update_status,
    cmd_issue_assign,
    cmd_issue_update_comment,
)
from jira_cli.completion import cmd_completion


def print_usage_err():
    """Print short usage to stderr."""
    print("Usage: jira-cli <command> [args...] [-h]", file=sys.stderr)
    print("Commands: projects, search, issue, setup, help, completion", file=sys.stderr)


def main():
    """Main entry point — dispatches to sub-commands."""
    cfg = load_config()

    # Config check — skip for setup and help
    needs_config = {"projects", "search", "issue"}
    cmd = sys.argv[1] if len(sys.argv) > 1 else None
    if cmd not in ("setup", "help", "completion", None):
        if not cfg.get("url") or not cfg.get("user") or not cfg.get("pass"):
            print("Jira not configured.", file=sys.stderr)
            print("  jira-cli setup", file=sys.stderr)
            print("  or: export JIRA_URL=... JIRA_USER=... JIRA_PASS=...", file=sys.stderr)
            sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: jira-cli <command> [args...] [-h]")
        print("Commands: projects, search, issue, setup, help, completion")
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    # --help / -h / help on root command
    if cmd in ("--help", "-h", "help"):
        print_help("main")
        return

    if cmd == "setup":
        if has_help_flag(args):
            print_help("setup")
            return
        return cmd_setup(cfg)

    if cmd == "completion":
        if has_help_flag(args) or not args:
            if not args:
                print("Usage: jira-cli completion <shell>", file=sys.stderr)
                print("Shells: bash, zsh, fish", file=sys.stderr)
                print("  jira-cli completion bash   # print bash completion script", file=sys.stderr)
                print("  jira-cli completion zsh    # print zsh completion script", file=sys.stderr)
                print("  jira-cli completion fish   # print fish completion script", file=sys.stderr)
                return
            print_help("main")
            return
        return cmd_completion(args[0])

    # --- projects ---
    if cmd == "projects":
        if has_help_flag(args):
            print_help("projects")
            return
        return cmd_projects(cfg)

    # --- search ---
    if cmd == "search":
        if has_help_flag(args):
            print_help("search")
            return
        rest, flags = parse_flags(args)
        if flags.get("list_filters"):
            from jira_cli.filters import FILTERS
            print("AVAILABLE SAVED FILTERS:\n")
            for name in sorted(FILTERS.keys()):
                info = FILTERS[name]
                print(f"  {name:20} {info['desc']}")
                print(f"  {'':20} JQL: {info['jql']}")
                print()
            print("EXAMPLES:")
            print("  jira-cli search --saved my-issues                        # single filter")
            print("  jira-cli search --saved my-issues,in-progress            # comma combined")
            print("  jira-cli search --saved my-issues 'project=BANKING'      # filter + JQL")
            print("  jira-cli search --saved todo --limit 5 --format json     # with flags")
            return
        jql = build_jql(flags["saved"], rest)
        if not jql:
            print_help("search")
            sys.exit(1)
        return cmd_search(cfg, jql, flags["limit"], flags["format"])

    # --- issue ---
    if cmd == "issue":
        if has_help_flag(args):
            print_help("issue")
            return
        if not args:
            print("Usage: jira-cli issue <issue-key> [comments|comment|add-comment] [args...]", file=sys.stderr)
            sys.exit(1)
        issue_key = args[0].upper()
        sub = args[1] if len(args) > 1 else None

        # issue <key>
        if sub is None:
            return cmd_issue(cfg, issue_key)

        sub_args = args[2:]

        # issue <key> -h / --help
        if sub in ("--help", "-h"):
            print_help("issue")
            return

        # issue <key> comments
        if sub == "comments":
            if has_help_flag(sub_args):
                print_help("issue")
                return
            rest, flags = parse_flags(sub_args)
            return cmd_issue_comments(
                cfg, issue_key,
                limit=flags["limit"],
                page=flags["page"],
                desc=flags["desc"],
                fmt=flags["format"],
            )

        # issue <key> comment <id>
        if sub == "comment":
            if not sub_args or has_help_flag(sub_args):
                print("Usage: jira-cli issue <issue-key> comment <comment-id> [--format json]", file=sys.stderr)
                sys.exit(1) if not sub_args else print_help("issue")
                return
            cmt_id = sub_args[0]
            rest, flags = parse_flags(sub_args[1:])
            return cmd_issue_comment(cfg, issue_key, cmt_id, flags["format"])

        # issue <key> add-comment
        if sub == "add-comment":
            if has_help_flag(sub_args):
                print("Usage: jira-cli issue <issue-key> add-comment [--body <text>]", file=sys.stderr)
                print("  Omit --body to read comment from stdin (Ctrl+D to end).", file=sys.stderr)
                sys.exit(0)
            rest, flags = parse_flags(sub_args)
            return cmd_issue_add_comment(cfg, issue_key, flags["body"])

        # issue <key> update-description
        if sub == "update-description":
            if has_help_flag(sub_args):
                print("Usage: jira-cli issue <issue-key> update-description --body <text>", file=sys.stderr)
                sys.exit(0)
            rest, flags = parse_flags(sub_args)
            if not flags.get("body"):
                print("Error: --body <text> is required.", file=sys.stderr)
                sys.exit(1)
            return cmd_issue_update_description(cfg, issue_key, flags["body"])

        # issue <key> transition <id|name>
        if sub == "transition":
            if not sub_args or has_help_flag(sub_args):
                print("Usage: jira-cli issue <issue-key> transition <transition-id-or-name>", file=sys.stderr)
                sys.exit(1) if not sub_args else print_help("issue")
                return
            return cmd_issue_update_status(cfg, issue_key, sub_args[0])

        # issue <key> assign <username>
        if sub == "assign":
            if not sub_args or has_help_flag(sub_args):
                print("Usage: jira-cli issue <issue-key> assign <username>", file=sys.stderr)
                if not sub_args:
                    sys.exit(1)
                print_help("issue")
                return
            return cmd_issue_assign(cfg, issue_key, sub_args[0])

        # issue <key> edit-comment <id>
        if sub == "edit-comment":
            if not sub_args or has_help_flag(sub_args):
                print("Usage: jira-cli issue <issue-key> edit-comment <comment-id> --body <text>", file=sys.stderr)
                sys.exit(1) if not sub_args else print_help("issue")
                return
            cmt_id = sub_args[0]
            rest, flags = parse_flags(sub_args[1:])
            return cmd_issue_update_comment(cfg, issue_key, cmt_id, flags.get("body", ""))

        print(f"Unknown issue subcommand: {sub}", file=sys.stderr)
        print("Subcommands: comments, comment <id>, add-comment, update-description, transition, assign, edit-comment", file=sys.stderr)
        sys.exit(1)

    # --- unknown ---
    print(f"Unknown: {cmd}", file=sys.stderr)
    print_usage_err()
    sys.exit(1)


if __name__ == "__main__":
    main()
