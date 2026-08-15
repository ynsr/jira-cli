"""Command: completion — print shell completion scripts for bash, zsh, or fish."""

import shlex

_COMPLETION_COMMANDS = [
    "projects",
    "search",
    "create",
    "link",
    "issue",
    "setup",
    "help",
    "completion",
]

_COMPLETION_SUBCOMMANDS = {
    "issue": ["comments", "comment", "add-comment", "attachments", "download", "delete-attachment", "attach", "update", "transition", "edit-comment"],
    "completion": ["bash", "zsh", "fish"],
}

_COMPLETION_FLAGS = {
    "search": ["--limit", "--saved", "--list-filters", "--format"],
    "issue": ["--limit", "--page", "--desc", "--format", "--body"],
    "create": ["--project", "--summary", "--type", "--description", "--priority", "--assignee", "--format"],
    "link": ["--type", "--comment"],
    "issue-update": ["--summary", "--description", "--priority", "--assignee"],
    "issue-transition": [],
    "issue-edit-comment": ["--body"],
}


def cmd_completion(shell):
    """Print a shell completion script for bash, zsh, or fish."""
    shell = shell.lower().strip()
    if shell == "bash":
        print(_bash_completion())
    elif shell == "zsh":
        print(_zsh_completion())
    elif shell == "fish":
        print(_fish_completion())
    else:
        print(f"Unknown shell: {shell}", file=__import__("sys").stderr)
        print("Supported shells: bash, zsh, fish", file=__import__("sys").stderr)
        __import__("sys").exit(1)


def _bash_completion():
    """Generate bash completion script."""
    cmds = " ".join(_COMPLETION_COMMANDS)
    return f"""# bash completion for jira-cli
_jira_cli()
{{
    local cur prev words cword
    _init_completion -s || return

    # top-level commands
    if [[ $cword -eq 1 ]]; then
        COMPREPLY=($(compgen -W "{cmds}" -- "$cur"))
        return
    fi

    # sub-commands / flags
    case "${{words[1]}}" in
        search)
            if [[ "$cur" == -* ]]; then
                COMPREPLY=($(compgen -W "--limit --saved --list-filters --format --help -h" -- "$cur"))
            fi
            ;;
        issue)
            if [[ $cword -eq 2 ]]; then
                if [[ "$cur" == -* ]]; then
                    COMPREPLY=($(compgen -W "--help -h" -- "$cur"))
                fi
            elif [[ $cword -eq 3 ]]; then
                local subs="comments comment add-comment attachments download delete-attachment attach update transition edit-comment"
                COMPREPLY=($(compgen -W "$subs" -- "$cur"))
            elif [[ $cword -ge 4 ]]; then
                case "${{words[3]}}" in
                    download)
                        COMPREPLY=($(compgen -W "--dir --all --help -h" -- "$cur"))
                        ;;
                    delete-attachment)
                        COMPREPLY=($(compgen -W "--all --help -h" -- "$cur"))
                        ;;
                    attach)
                        if [[ "$cur" != -* ]]; then
                            # complete local file paths
                            COMPREPLY=($(compgen -f -- "$cur"))
                        else
                            COMPREPLY=($(compgen -W "--help -h" -- "$cur"))
                        fi
                        ;;
                    comments)
                        COMPREPLY=($(compgen -W "--limit --page --desc --format --help -h" -- "$cur"))
                        ;;
                    update)
                        COMPREPLY=($(compgen -W "--summary --description --priority --assignee --help -h" -- "$cur"))
                        ;;
                    comment)
                        if [[ "$cur" != -* ]]; then
                            # suggest numeric IDs; no dynamic lookup
                            COMPREPLY=()
                        else
                            COMPREPLY=($(compgen -W "--format --help -h" -- "$cur"))
                        fi
                        ;;
                    add-comment)
                        COMPREPLY=($(compgen -W "--body --help -h" -- "$cur"))
                        ;;
                esac
            fi
            ;;
        completion)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "bash zsh fish" -- "$cur"))
            fi
            ;;
        *)
            if [[ "$cur" == -* ]]; then
                COMPREPLY=($(compgen -W "--help -h" -- "$cur"))
            fi
            ;;
    esac
}} && complete -F _jira_cli jira-cli
"""


def _zsh_completion():
    """Generate zsh completion script."""
    return """#compdef jira-cli

_jira_cli_commands() {
    local -a commands
    commands=(
        'projects:List all projects'
        'search:Search issues with JQL or saved filters'
        'create:Create a new issue'
        'link:Link two issues'
        'issue:Show issue detail and work with comments'
        'setup:Configure Jira credentials'
        'help:Print help text'
        'completion:Print a shell completion script'
    )
    _describe -t commands 'command' commands
}

_jira_cli_issue_sub() {
    local -a subs
    subs=(
        'comments:List paginated comments'
        'comment:Show full comment detail'
        'add-comment:Add a comment to an issue'
        'attachments:List attachment file(s)'
        'download:Download attachment file(s)'
        'delete-attachment:Delete attachment file(s)'
        'attach:Upload attachment file(s)'
        'update:Update summary/description/priority/assignee'
    )
    _describe -t subcommands 'subcommand' subs
}

_jira_cli_completion_shells() {
    local -a shells
    shells=('bash:Bash shell' 'zsh:Zsh shell' 'fish:Fish shell')
    _describe -t shells 'shell' shells
}

_jira_cli() {
    local context state state_descr line
    typeset -A opt_args

    _arguments -C \\
        '(- *)'{-h,--help}'[Show help]' \\
        '1:command:->cmds' \\
        '*::arg:->args'

    case "$state" in
        cmds)
            _jira_cli_commands
            ;;
        args)
            case "$words[1]" in
                search)
                    _arguments \\
                        '(-h --help)'{-h,--help}'[Show help]' \\
                        '--limit=[Max results]:number' \\
                        '--saved=[Saved filter]:filter' \\
                        '--list-filters[List saved filters]' \\
                        '--format=[Output format]:format:(table json)' \\
                        '*:JQL string'
                    ;;
                create)
                    _arguments \\
                        '(-h --help)'{-h,--help}'[Show help]' \\
                        '--project=[Project key]:key' \\
                        '--summary=[Issue summary]:text' \\
                        '--type=[Issue type]:type:(Task Bug Story Epic)' \\
                        '--description=[Issue description]:text' \\
                        '--priority=[Priority]:priority:(Highest High Medium Low Lowest)' \\
                        '--assignee=[Assignee username]:user' \\
                        '--format=[Output format]:format:(table json)'
                    ;;
                link)
                    _arguments \\
                        '(-h --help)'{-h,--help}'[Show help]' \\
                        '--type=[Link type]:type:(Relates Blocks Duplicate)' \\
                        '--comment=[Link comment]:text' \\
                        '*:issue keys'
                    ;;
                issue)
                    if [[ $CURRENT -eq 3 ]]; then
                        _arguments '(-h --help)'{-h,--help}'[Show help]'
                        _jira_cli_issue_sub
                    elif [[ $CURRENT -eq 4 ]]; then
                        # sub-args
                        case "$words[3]" in
            comments)
                _arguments \\
                    '(-h --help)'{-h,--help}'[Show help]' \\
                    '--limit=[Comments per page]:number' \\
                    '--page=[Page number]:number' \\
                    '--desc[Newest-first order]' \\
                    '--format=[Output format]:format:(table json)'
                ;;
            comment)
                _arguments \\
                    '(-h --help)'{-h,--help}'[Show help]' \\
                    '--format=[Output format]:format:(table json)' \\
                    '*:comment ID'
                ;;
add-comment)
                    _arguments \\
                        '(-h --help)'{-h,--help}'[Show help]' \\
                        '--body=[Comment body text]:text'
                ;;
            attach)
                    _arguments \\
                        '(-h --help)'{-h,--help}'[Show help]' \\
                        '*:file:_files'
                ;;
            attachments)
                    _arguments \\
                        '(-h --help)'{-h,--help}'[Show help]' \\
                        '--format=[Output format]:format:(table json)'
                ;;
            download)
                    _arguments \\
                        '(-h --help)'{-h,--help}'[Show help]' \\
                        '--dir=[Destination directory]:dir:_directories' \\
                        '--all[Download every attachment]' \\
                        '*:attachment id'
                ;;
            delete-attachment)
                    _arguments \\
                        '(-h --help)'{-h,--help}'[Show help]' \\
                        '--all[Delete every attachment]' \\
                        '*:attachment id'
                ;;
            update)
                _arguments \\
                    '(-h --help)'{-h,--help}'[Show help]' \\
                    '--summary=[New summary]:text' \\
                    '--description=[New description]:text' \\
                    '--priority=[Priority]:priority:(Highest High Medium Low Lowest)' \\
                    '--assignee=[Assignee username]:user'
                ;;
                        esac
                    fi
                    ;;
                completion)
                    _arguments '1:shell:->shells'
                    ;;
                *)
                    _arguments '(-h --help)'{-h,--help}'[Show help]'
                    ;;
            esac
            ;;
        shells)
            _jira_cli_completion_shells
            ;;
    esac
}

_jira_cli
"""


def _fish_completion():
    """Generate fish completion script."""
    return """# fish completion for jira-cli
function __fish_jira_cli_needs_command
    set cmd (commandline -opc)
    if [ (count $cmd) -eq 1 ]
        return 0
    end
    return 1
end

function __fish_jira_cli_using_command
    set cmd (commandline -opc)
    if [ (count $cmd) -gt 1 ]
        if [ $argv[1] = $cmd[2] ]
            return 0
        end
    end
    return 1
end

# top-level commands
complete -c jira-cli -f -n '__fish_jira_cli_needs_command' -a projects -d 'List all projects'
complete -c jira-cli -f -n '__fish_jira_cli_needs_command' -a search -d 'Search issues with JQL or saved filters'
complete -c jira-cli -f -n '__fish_jira_cli_needs_command' -a issue -d 'Show issue detail and work with comments'
complete -c jira-cli -f -n '__fish_jira_cli_needs_command' -a setup -d 'Configure Jira credentials'
complete -c jira-cli -f -n '__fish_jira_cli_needs_command' -a help -d 'Print help text'
complete -c jira-cli -f -n '__fish_jira_cli_needs_command' -a completion -d 'Print a shell completion script'

# global flags
complete -c jira-cll -f -n '__fish_jira_cli_needs_command' -s h -l help -d 'Show help'

# search flags
complete -c jira-cli -f -n '__fish_jira_cli_using_command search' -s h -l help -d 'Show help'
complete -c jira-cli -f -n '__fish_jira_cli_using_command search' -l limit -d 'Max results'
complete -c jira-cli -f -n '__fish_jira_cli_using_command search' -l saved -d 'Saved filter (comma-separated)'
complete -c jira-cli -f -n '__fish_jira_cli_using_command search' -l list-filters -d 'List saved filters'
complete -c jira-cli -f -n '__fish_jira_cli_using_command search' -l format -d 'Output format' -xa 'table json'

# create flags
complete -c jira-cli -f -n '__fish_jira_cli_using_command create' -s h -l help -d 'Show help'
complete -c jira-cli -f -n '__fish_jira_cli_using_command create' -l project -d 'Project key'
complete -c jira-cli -f -n '__fish_jira_cli_using_command create' -l summary -d 'Issue summary'
complete -c jira-cli -f -n '__fish_jira_cli_using_command create' -l type -d 'Issue type' -xa 'Task Bug Story Epic'
complete -c jira-cli -f -n '__fish_jira_cli_using_command create' -l description -d 'Issue description'
complete -c jira-cli -f -n '__fish_jira_cli_using_command create' -l priority -d 'Priority' -xa 'Highest High Medium Low Lowest'
complete -c jira-cli -f -n '__fish_jira_cli_using_command create' -l assignee -d 'Assignee username'
complete -c jira-cli -f -n '__fish_jira_cli_using_command create' -l format -d 'Output format' -xa 'table json'

# link flags
complete -c jira-cli -f -n '__fish_jira_cli_using_command link' -s h -l help -d 'Show help'
complete -c jira-cli -f -n '__fish_jira_cli_using_command link' -l type -d 'Link type' -xa 'Relates Blocks Duplicate'
complete -c jira-cli -f -n '__fish_jira_cli_using_command link' -l comment -d 'Link comment'

# issue subcommands
complete -c jira-cli -f -n '__fish_jira_cli_using_command issue' -a comments -d 'List paginated comments'
complete -c jira-cli -f -n '__fish_jira_cli_using_command issue' -a 'comment' -d 'Show full comment detail'
complete -c jira-cli -f -n '__fish_jira_cli_using_command issue' -a 'add-comment' -d 'Add a comment'
complete -c jira-cli -f -n '__fish_jira_cli_using_command issue' -a 'attachments' -d 'List attachment file(s)'
complete -c jira-cli -f -n '__fish_jira_cli_using_command issue' -a 'download' -d 'Download attachment file(s)'
complete -c jira-cli -f -n '__fish_jira_cli_using_command issue' -a 'delete-attachment' -d 'Delete attachment file(s)'
complete -c jira-cli -f -n '__fish_jira_cli_using_command issue' -a 'attach' -d 'Upload attachment file(s)'
complete -c jira-cli -f -n '__fish_jira_cli_using_command issue' -a 'update' -d 'Update summary/description/priority/assignee'
complete -c jira-cli -f -n '__fish_jira_cli_using_command issue' -s h -l help -d 'Show help'

# issue comments flags
complete -c jira-cli -f -n '__fish_jira_cli_using_command comments' -s h -l help -d 'Show help'
complete -c jira-cli -f -n '__fish_jira_cli_using_command comments' -l limit -d 'Comments per page'
complete -c jira-cli -f -n '__fish_jira_cli_using_command comments' -l page -d 'Page number'
complete -c jira-cli -f -n '__fish_jira_cli_using_command comments' -l desc -d 'Newest-first order'
complete -c jira-cli -f -n '__fish_jira_cli_using_command comments' -l format -d 'Output format' -xa 'table json'

# issue comment flags
complete -c jira-cli -f -n '__fish_jira_cli_using_command comment' -s h -l help -d 'Show help'
complete -c jira-cli -f -n '__fish_jira_cli_using_command comment' -l format -d 'Output format' -xa 'table json'

# issue add-comment flags
complete -c jira-cli -f -n '__fish_jira_cli_using_command add-comment' -s h -l help -d 'Show help'
complete -c jira-cli -f -n '__fish_jira_cli_using_command add-comment' -l body -d 'Comment body text'

# issue attach files
complete -c jira-cli -f -n '__fish_jira_cli_using_command attach' -a '(__fish_complete_path)'

# issue attachments flags
complete -c jira-cli -f -n '__fish_jira_cli_using_command attachments' -s h -l help -d 'Show help'
complete -c jira-cli -f -n '__fish_jira_cli_using_command attachments' -l format -d 'Output format' -xa 'table json'

# issue download flags
complete -c jira-cli -f -n '__fish_jira_cli_using_command download' -s h -l help -d 'Show help'
complete -c jira-cli -f -n '__fish_jira_cli_using_command download' -l dir -d 'Destination directory' -a '(__fish_complete_directories)'
complete -c jira-cli -f -n '__fish_jira_cli_using_command download' -l all -d 'Download every attachment'

# issue delete-attachment flags
complete -c jira-cli -f -n '__fish_jira_cli_using_command delete-attachment' -s h -l help -d 'Show help'
complete -c jira-cli -f -n '__fish_jira_cli_using_command delete-attachment' -l all -d 'Delete every attachment'

# issue update flags
complete -c jira-cli -f -n '__fish_jira_cli_using_command update' -s h -l help -d 'Show help'
complete -c jira-cli -f -n '__fish_jira_cli_using_command update' -l summary -d 'New summary'
complete -c jira-cli -f -n '__fish_jira_cli_using_command update' -l description -d 'New description'
complete -c jira-cli -f -n '__fish_jira_cli_using_command update' -l priority -d 'Priority' -xa 'Highest High Medium Low Lowest'
complete -c jira-cli -f -n '__fish_jira_cli_using_command update' -l assignee -d 'Assignee username'

# completion subcommand
complete -c jira-cli -f -n '__fish_jira_cli_using_command completion' -a bash -d 'Bash completions'
complete -c jira-cli -f -n '__fish_jira_cli_using_command completion' -a zsh -d 'Zsh completions'
complete -c jira-cli -f -n '__fish_jira_cli_using_command completion' -a fish -d 'Fish completions'
"""
