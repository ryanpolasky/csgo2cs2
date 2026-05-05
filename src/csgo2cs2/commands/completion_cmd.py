# `csgo2cs2 completion <shell>` -- emit shell completion scripts.
#
# we hand-roll the templates rather than depending on argcomplete: it
# avoids a runtime dep, the subcommand surface is small enough to spell
# out, and users can pipe-redirect the output into their rc / profile.

from __future__ import annotations

import argparse

# subcommands the cli exposes. when adding new subcommands, append them
# here so completion stays current. matched in build_parser order.
SUBCOMMANDS = (
    "init",
    "doctor",
    "tools",
    "download",
    "decompile",
    "analyze",
    "explain",
    "port",
    "list",
    "status",
    "cleanup",
    "launch",
    "verify",
    "publish",
    "about",
    "completion",
)

SHELLS = ("bash", "zsh", "powershell")


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "completion",
        help="Print shell completion script for bash/zsh/powershell.",
    )
    p.add_argument("shell", choices=SHELLS, help="Target shell.")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    if args.shell == "bash":
        print(_bash())
    elif args.shell == "zsh":
        print(_zsh())
    elif args.shell == "powershell":
        print(_powershell())
    else:  # pragma: no cover (argparse choices guard)
        return 2
    return 0


def _subcommand_list() -> str:
    return " ".join(SUBCOMMANDS)


def _bash() -> str:
    cmds = _subcommand_list()
    return f"""# csgo2cs2 bash completion
# install: source <(csgo2cs2 completion bash)
# or save to /etc/bash_completion.d/csgo2cs2

_csgo2cs2_completion() {{
    local cur prev words cword
    _init_completion || return

    if [[ $cword -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "{cmds}" -- "$cur") )
        return
    fi

    case "$prev" in
        --config|-o|--output)
            COMPREPLY=( $(compgen -f -- "$cur") )
            return
            ;;
        --fix-spawns)
            COMPREPLY=( $(compgen -W "ct t" -- "$cur") )
            return
            ;;
        completion)
            COMPREPLY=( $(compgen -W "bash zsh powershell" -- "$cur") )
            return
            ;;
    esac

    if [[ "$cur" == --* ]]; then
        COMPREPLY=( $(compgen -W "--help --config --verbose --version" -- "$cur") )
        return
    fi
    COMPREPLY=( $(compgen -f -- "$cur") )
}}

complete -F _csgo2cs2_completion csgo2cs2
"""


def _zsh() -> str:
    cmds = _subcommand_list()
    # _arguments-driven; light surface but covers subcommand + common flags
    return f"""#compdef csgo2cs2
# csgo2cs2 zsh completion
# install: place in a directory on $fpath and re-run `compinit`
# or for ad-hoc use: source <(csgo2cs2 completion zsh)

_csgo2cs2() {{
    local -a cmds shells sides
    cmds=({cmds})
    shells=(bash zsh powershell)
    sides=(ct t)

    _arguments -C \\
        '--config[Path to config JSON]:file:_files' \\
        '--verbose[Verbose logging]' \\
        '--version[Print version]' \\
        '1: :->cmd' \\
        '*::arg:->args'

    case $state in
        cmd)
            _values 'csgo2cs2 subcommand' "${{cmds[@]}}"
            ;;
        args)
            case $words[1] in
                completion)
                    _values 'shell' "${{shells[@]}}"
                    ;;
                analyze|port)
                    _arguments \\
                        '--fix[Apply auto-fixes]' \\
                        '--dry-run[Preview without writing]' \\
                        '--fix-spawns[Convert legacy spawns]:side:(ct t)' \\
                        '*:vmf or workshop id:_files'
                    ;;
                doctor)
                    _arguments \\
                        '--fix[Apply install patches]' \\
                        '--unfix[Reverse install patches]' \\
                        '--json[Emit structured json report]'
                    ;;
                explain|launch|verify|publish|status)
                    _files
                    ;;
            esac
            ;;
    esac
}}

compdef _csgo2cs2 csgo2cs2
"""


def _powershell() -> str:
    cmds = _subcommand_list().replace(" ", "', '")
    return f"""# csgo2cs2 powershell completion
# install: . <(csgo2cs2 completion powershell)
# or pipe into $PROFILE: csgo2cs2 completion powershell >> $PROFILE

Register-ArgumentCompleter -Native -CommandName csgo2cs2 -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)

    $commands = @('{cmds}')
    $tokens = $commandAst.CommandElements |
        ForEach-Object {{ $_.ToString() }}

    if ($tokens.Count -le 2) {{
        $commands |
            Where-Object {{ $_ -like "$wordToComplete*" }} |
            ForEach-Object {{
                [System.Management.Automation.CompletionResult]::new(
                    $_, $_, 'ParameterValue', $_)
            }}
        return
    }}

    $sub = $tokens[1]
    switch ($sub) {{
        'completion' {{
            @('bash', 'zsh', 'powershell') |
                Where-Object {{ $_ -like "$wordToComplete*" }} |
                ForEach-Object {{
                    [System.Management.Automation.CompletionResult]::new(
                        $_, $_, 'ParameterValue', $_)
                }}
        }}
        default {{
            @('--help', '--config', '--verbose') |
                Where-Object {{ $_ -like "$wordToComplete*" }} |
                ForEach-Object {{
                    [System.Management.Automation.CompletionResult]::new(
                        $_, $_, 'ParameterName', $_)
                }}
        }}
    }}
}}
"""
