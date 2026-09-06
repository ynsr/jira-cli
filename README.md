# jira-cli

Query, list, and interact with Jira issues from the terminal.
Connects to any Jira instance (self-hosted or Cloud) with Basic Auth.

## Install

```bash
pipx install .
```

> **Troubleshooting**: If `jira-cli` is not found after install, the pipx
> symlink in `~/.local/bin/` may be missing. Re-run with `--force`:
> ```bash
> pipx install --force .
> ```
> Make sure `~/.local/bin` is on your `$PATH`.

Or from a remote source once published.

## Usage

```
jira-cli <command> [args...] [-h] [flags]
```

### Commands

| Command     | Description                                 |
|-------------|---------------------------------------------|
| `projects`  | List all projects                           |
| `search`    | Search issues with JQL or saved filters     |
| `create`    | Create a new issue                          |
| `link`      | Link two issues                             |
| `issue`     | Issue detail, comments, add-comment, attachments (list/download/delete), attach, update |
| `setup`     | Configure Jira credentials                  |
| `help`      | Print help text (AI-agent friendly)         |
| `completion`| Print shell completion script               |

### Examples

```bash
jira-cli projects
jira-cli search "project=BANKING" --format json
jira-cli search --list-filters
jira-cli search --saved my-issues --limit 5 --format json
jira-cli search --saved my-issues+blocked
jira-cli issue PROJ-123
jira-cli issue PROJ-123 comments --limit 10 --desc
jira-cli issue PROJ-123 comment 54321
jira-cli issue PROJ-123 add-comment --body "Working on this"
jira-cli issue PROJ-123 attach ./screenshot.png ./error.log
jira-cli issue PROJ-123 attachments
jira-cli issue PROJ-123 download --all --dir ./attachments
jira-cli issue PROJ-123 download 10001
jira-cli issue PROJ-123 delete-attachment 10001
jira-cli issue PROJ-123 update --summary "New title" --priority High
jira-cli issue PROJ-123 update --description "New description" --assignee jane.doe
jira-cli create --project BANKING --summary "Fix bug" --type Bug --priority High
jira-cli link BANKING-123 BANKING-456 --type Blocks --comment "Depends on this"
jira-cli completion bash
jira-cli completion zsh
jira-cli completion fish
```

### Config

Set `JIRA_URL`, `JIRA_USER`, `JIRA_PASS` env vars, or run `jira-cli setup`
to save credentials to `~/.jira-cli.json` (chmod 600).

### Jira Server/DC & Cloud compatibility

jira-cli works with both **Jira Server/Data Center** (REST API v2) and
**Jira Cloud** (REST API v3):

- Reads and JQL searches always use API v2 (served by both platforms).
- Write operations (create, update, comments, links) use the version
  auto-detected from `/rest/api/2/serverInfo` (`deploymentType`).
- On Server/DC the `description` and comment bodies are sent as plain
  wiki-markup strings; on Cloud they are sent as Atlassian Document Format
  (ADF) documents — handled automatically.
- Force a version if needed: `JIRA_API_VERSION=2` or `JIRA_API_VERSION=3`
  (default `auto`).

## Development

```bash
pip install -e .
python -m pytest tests/
```
