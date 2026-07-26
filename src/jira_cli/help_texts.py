"""Help texts for all jira-cli commands."""

from jira_cli.filters import FILTERS

HELP = {}

HELP["main"] = """JIRA-CLI HELP — AI-agent friendly

COMMANDS:
  projects                    List all projects
  search <jql> [flags]        Search issues with JQL + saved filters
  issue <KEY>                 Show issue detail + latest comment
  issue <KEY> comments        Paginated comment list (truncated text)
  issue <KEY> comment <ID>    Full single comment detail
  issue <KEY> add-comment     Add a comment
  issue <KEY> update-description  Update issue description (--body)
  issue <KEY> transition <ID>     Transition issue to a new status
  issue <KEY> assign <USER>       Assign/reassign issue
  issue <KEY> edit-comment <ID>   Edit an existing comment body
  setup                       Configure credentials
  completion <shell>          Print a shell completion script (bash, zsh, fish)
  help                        This help text

EXAMPLES:
  jira-cli projects
  jira-cli search "project=BANKING" --format json
  jira-cli search --list-filters
  jira-cli search --saved my-issues+in-progress
  jira-cli issue PROJ-123
  jira-cli issue PROJ-123 comments --limit 5 --desc
  jira-cli issue PROJ-123 comment 12345
  jira-cli issue PROJ-123 add-comment --body "Looking into this"
  jira-cli issue PROJ-123 update-description --body "New description text"
  jira-cli issue PROJ-123 transition 41
  jira-cli issue PROJ-123 assign jane.doe
  jira-cli issue PROJ-123 edit-comment 12345 --body "Updated comment"
  jira-cli completion bash

AI USAGE:
  issues = run("jira-cli search --saved my-issues --limit 5 --format json")
  detail = run("jira-cli issue PROJ-123")
  cmts   = run("jira-cli issue PROJ-123 comments --limit 3 --format json")

Run 'jira-cli <command> -h' for per-command help with examples.
"""

HELP["search"] = """jira-cli search — search issues with JQL

Usage:
  jira-cli search <jql> [--saved <filter>] [--limit N] [--format <table|json>]
  jira-cli search --list-filters                 List saved filters with JQL
  jira-cli search --saved <name> [<name>...]     Run saved filters (AND-joined)

Args:
  <jql>               Raw JQL query (required unless --saved is used)
  --saved <filter>    AND-join a predefined filter (repeatable, comma-separated)
  --list-filters      List all saved filters and exit
  --limit <N>         Max results (default: 20)
  --format <fmt>      Output: table (default) or json

Available --saved filters:
""" + "\n".join(f"  {n:20} {v['desc']}" for n, v in sorted(FILTERS.items())) + """

EXAMPLES:
  jira-cli search "project=BANKING AND status='In Progress'"
  jira-cli search --list-filters
  jira-cli search --saved my-issues --limit 10 --format json
  jira-cli search --saved my-issues,in-progress "project=BANKING"
  jira-cli search --saved todo
"""

HELP["issue"] = """jira-cli issue — show issue detail and work with comments

Usage:
  jira-cli issue <KEY>                         Show issue detail + latest comment
  jira-cli issue <KEY> comments [flags]        List paginated comments (truncated)
  jira-cli issue <KEY> comment <ID>            Show full single comment
  jira-cli issue <KEY> add-comment [--body <text>]  Add a comment
  jira-cli issue <KEY> -h                      This help text

Flags for 'comments' subcommand:
  --limit <N>         Comments per page (default: 5)
  --page <N>          Page number, 1-based (default: 1)
  --desc              Newest-first order
  --format <fmt>      table (default) or json

Flags for 'add-comment' subcommand:
  --body <text>       Comment body text (omit to read from stdin until Ctrl+D)

EXAMPLES:
  jira-cli issue PROJ-123                                        # detail + latest comment
  jira-cli issue PROJ-123 comments --limit 10 --page 2 --desc    # paginated comments
  jira-cli issue PROJ-123 comment 54321                          # full comment detail
  jira-cli issue PROJ-123 add-comment --body "Working on this"   # add comment
  echo "Done" | jira-cli issue PROJ-123 add-comment              # add from stdin
"""

HELP["projects"] = """jira-cli projects — list all Jira projects

Usage:
  jira-cli projects

Output: table with Key, Name, Lead, Type columns.

EXAMPLE:
  jira-cli projects
"""

HELP["setup"] = """jira-cli setup — configure Jira credentials

Usage:
  jira-cli setup

Prompts for Jira URL, username, and password.
Saves to ~/.jira-cli.json (chmod 600).
Can be overridden by env vars: JIRA_URL, JIRA_USER, JIRA_PASS.

EXAMPLE:
  jira-cli setup
"""


def print_help(topic="main"):
    """Print help text for a topic."""
    text = HELP.get(topic, HELP["main"])
    print(text.strip())
