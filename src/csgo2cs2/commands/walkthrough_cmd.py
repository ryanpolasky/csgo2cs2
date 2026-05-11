# `csgo2cs2 walkthrough` --- interactive guided tour.
#
# Walks a new user through the typical first-port flow: explains what the
# tool does, checks each prerequisite, prompts for the bits we need, and
# runs the underlying subcommands. Re-runnable: each stage detects its own
# state and skips when there's nothing to do. Aliased as `tour`.
#
# Designed to be testable -- prompt and confirm functions are injectable
# so tests can drive the flow with scripted inputs without touching real
# files or running subcommands.

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable, List, Optional

from .. import __version__
from ..config import Config, config_path, load_config
from ..logging_utils import Fore, Style, header, info, success, warn
from ..platform_check import is_windows, os_label
from ..utils.drift import load_state

PromptFn = Callable[[str], str]
ConfirmFn = Callable[[str, bool], bool]


# ----- prompt helpers -----------------------------------------------------


def _confirm(question: str, default: bool, prompt_fn: PromptFn = input) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    raw = prompt_fn(f"{question} {suffix} ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def _noninteractive_prompt(_p: str) -> str:
    """Prompt stand-in used when `--yes` is set. Returns empty so `_ask`
    falls back to its default; `_ask` recognizes this and refuses to
    loop on `required=True` prompts, raising instead."""
    return ""


class _NoninteractiveValueRequiredError(RuntimeError):
    """Raised when a required-no-default prompt fires under `--yes`.
    The walkthrough caller catches this and surfaces an actionable hint."""


def _ask(
    question: str,
    *,
    default: str = "",
    required: bool = False,
    prompt_fn: PromptFn = input,
) -> str:
    label = f" [{default}]" if default else ""
    while True:
        raw = prompt_fn(f"{question}{label}: ").strip()
        if raw:
            return raw
        if default:
            return default
        if not required:
            return ""
        # noninteractive mode: never loop. fail loudly so the caller
        # passes the value on the command line instead.
        if prompt_fn is _noninteractive_prompt:
            raise _NoninteractiveValueRequiredError(question)
        warn("A value is required for this step.")


# ----- stage helpers ------------------------------------------------------


def _print_welcome() -> None:
    header("csgo2cs2 walkthrough")
    info(f"Version: {__version__}  |  Host: {os_label()}")
    print()
    print("This tour walks through a typical first port end to end:")
    print(f"  {Fore.CYAN}1.{Style.RESET_ALL} Confirm a config exists (or create one).")
    print(f"  {Fore.CYAN}2.{Style.RESET_ALL} Make sure the external tools are installed.")
    print(f"  {Fore.CYAN}3.{Style.RESET_ALL} Apply the CS2 install patches (Windows only).")
    print(f"  {Fore.CYAN}4.{Style.RESET_ALL} Download, decompile, analyze, and import a map.")
    print(f"  {Fore.CYAN}5.{Style.RESET_ALL} Verify the resulting addon.")
    print(
        f"  {Fore.CYAN}6.{Style.RESET_ALL} Optionally launch CS2 with the addon active (Windows only)."
    )
    print()
    print("You will need:")
    print("  - A CS:GO/CS2 install (the 'Counter-Strike Global Offensive' folder).")
    print("  - A Steam Workshop URL or numeric ID for a CS:GO map you want to port.")
    print("  - About 5-15 minutes for a clean run, depending on map size and download speed.")
    print()
    print("Each step will explain what is about to happen and ask before doing anything")
    print("that writes to disk. Re-running the walkthrough is safe -- already-done")
    print("steps will be skipped.")
    print()


def _config_summary(cfg: Config) -> List[str]:
    lines = []
    if cfg.csgo_install_path:
        lines.append(f"  csgo_install_path : {cfg.csgo_install_path}")
    else:
        lines.append("  csgo_install_path : <unset>")
    if cfg.steamcmd_path:
        lines.append(f"  steamcmd_path     : {cfg.steamcmd_path}")
    else:
        lines.append("  steamcmd_path     : <unset>")
    if cfg.bspsource_path:
        lines.append(f"  bspsource_path    : {cfg.bspsource_path}")
    else:
        lines.append("  bspsource_path    : <unset>")
    return lines


def _config_is_workable(cfg: Config) -> bool:
    # The minimum we need to attempt a port. Tools install can fill in
    # steamcmd / bspsource, but csgo_install_path is the user-supplied bit
    # that init can't always auto-detect.
    return bool(cfg.csgo_install_path)


def _tools_status(cfg: Config) -> dict[str, bool]:
    return {
        "steamcmd": bool(cfg.steamcmd_path and Path(cfg.steamcmd_path).exists()),
        "bspsource": bool(cfg.bspsource_path and Path(cfg.bspsource_path).exists()),
        "import_map_community": bool(
            cfg.import_script_path and Path(cfg.import_script_path).exists()
        ),
    }


def _patches_applied(cfg: Config) -> bool:
    workspace = Path(cfg.workspace_dir)
    state = load_state(workspace)
    return bool(state.entries)


# ----- stage runners ------------------------------------------------------


def _stage_config(
    args: argparse.Namespace,
    *,
    confirm_fn: ConfirmFn,
    prompt_fn: PromptFn,
) -> int:
    header("Step 1/6: Config")
    path = config_path(args.config)
    if path.exists():
        cfg = load_config(args.config)
        success(f"Existing config: {path}")
        for line in _config_summary(cfg):
            print(line)
        if not _config_is_workable(cfg):
            warn("csgo_install_path is unset -- the port pipeline will fail without it.")
            if confirm_fn("Run `csgo2cs2 init --interactive` to fill it in now?", True):
                return _run_subcommand(["init", "--interactive"], args)
        return 0

    info(f"No config file at {path}.")
    if not confirm_fn("Run `csgo2cs2 init` to create one (with auto-detection)?", True):
        warn("Skipping config setup. The walkthrough will likely fail later steps.")
        return 0
    interactive = confirm_fn(
        "Use --interactive to also prompt for paths we cannot auto-detect?",
        True,
    )
    init_args = ["init"]
    if interactive:
        init_args.append("--interactive")
    return _run_subcommand(init_args, args)


def _stage_tools(
    args: argparse.Namespace,
    *,
    confirm_fn: ConfirmFn,
) -> int:
    header("Step 2/6: External tools")
    cfg = load_config(args.config)
    statuses = _tools_status(cfg)
    missing = [name for name, ok in statuses.items() if not ok]

    for name, ok in statuses.items():
        marker = (
            f"{Fore.GREEN}ok{Style.RESET_ALL}" if ok else f"{Fore.YELLOW}missing{Style.RESET_ALL}"
        )
        print(f"  {name:<22} {marker}")

    if not missing:
        success("All required tools are configured.")
        return 0

    info(f"Missing tools: {', '.join(missing)}.")
    if not confirm_fn(
        "Run `csgo2cs2 tools install` to download the pinned versions now?",
        True,
    ):
        warn("Skipping tool install. The port pipeline will fail without these.")
        return 0
    return _run_subcommand(["tools", "install"], args)


def _stage_patches(
    args: argparse.Namespace,
    *,
    confirm_fn: ConfirmFn,
) -> int:
    header("Step 3/6: CS2 install patches")
    if not is_windows():
        info(f"Skipping -- install patches only apply on Windows. Detected: {os_label()}.")
        return 0

    cfg = load_config(args.config)
    if _patches_applied(cfg):
        success("Install patches are already recorded as applied.")
        info("Run `csgo2cs2 doctor` later to detect any drift after Steam updates.")
        return 0

    info("Patches needed: remove `.decode()` from import_map_community.py + rename")
    info("vpk.signatures to vpk.signatures.old. Both are reversible via `doctor --unfix`.")
    if not confirm_fn("Run `csgo2cs2 doctor --fix` now?", True):
        warn("Skipping doctor --fix. The import step will fail without it.")
        return 0
    return _run_subcommand(["doctor", "--fix"], args)


def _stage_port(
    args: argparse.Namespace,
    *,
    confirm_fn: ConfirmFn,
    prompt_fn: PromptFn,
) -> tuple[int, Optional[str]]:
    header("Step 4/6: Port a map")
    if args.workshop_url and args.addon:
        info(f"Using workshop ID/URL from --workshop: {args.workshop_url}")
        info(f"Using addon name from --addon: {args.addon}")
        url = args.workshop_url
        addon = args.addon
    else:
        info(
            "Provide the Steam Workshop URL (or just the numeric ID) for the map you want to port."
        )
        info("Example: https://steamcommunity.com/sharedfiles/filedetails/?id=123456789")
        url = _ask(
            "Workshop URL or ID",
            required=True,
            prompt_fn=prompt_fn,
        )
        addon = _ask(
            "CS2 addon name (lowercase, no spaces)",
            default=args.addon or "my_addon",
            required=True,
            prompt_fn=prompt_fn,
        )

    auto = confirm_fn(
        "Apply auto-fixes (skybox, entities, paths) without prompting per finding?",
        True,
    )

    auto_addoninfo = False
    export_images: Optional[str] = None
    if is_windows():
        auto_addoninfo = confirm_fn(
            "Auto-populate addoninfo.json from the workshop metadata?",
            True,
        )
        if confirm_fn(
            "Also save the workshop preview image + metadata.json to a folder?",
            False,
        ):
            cfg = load_config(args.config)
            default_dir = str(Path(cfg.workspace_dir) / "images")
            export_images = _ask(
                "Image export directory",
                default=default_dir,
                prompt_fn=prompt_fn,
            )

    skip_import = not is_windows()
    if skip_import:
        warn(f"Detected non-Windows host ({os_label()}). The walkthrough will run")
        warn("download/decompile/analyze only and skip the actual import. To finish")
        warn("the port, re-run `csgo2cs2 port <url> --addon <name> --auto` on Windows.")
        if not confirm_fn("Continue with the cross-platform dry run?", True):
            return 0, None

    port_args = ["port", url, "--addon", addon]
    if auto:
        port_args.append("--auto")
    if skip_import:
        port_args.append("--skip-import")
    if auto_addoninfo:
        port_args.append("--auto-addoninfo")
    if export_images:
        port_args.extend(["--export-images", export_images])

    rc = _run_subcommand(port_args, args)
    return rc, addon if rc == 0 else None


def _stage_verify(args: argparse.Namespace, addon: str) -> int:
    header("Step 5/6: Verify the imported addon")
    if not is_windows():
        info("Skipping -- verify checks the actual addon directory under cs2_bin_path,")
        info("which only exists on a Windows host with cs2 installed. Run")
        info(f"  csgo2cs2 verify {addon}")
        info("on the Windows machine after running the port there.")
        return 0
    return _run_subcommand(["verify", addon], args)


def _stage_launch(
    args: argparse.Namespace,
    addon: str,
    *,
    confirm_fn: ConfirmFn,
) -> int:
    header("Step 6/6: Launch CS2 with the addon")
    if args.no_launch:
        info("Skipping -- --no-launch was passed.")
        return 0
    if not is_windows():
        info(f"Skipping -- launch is Windows-only. Run `csgo2cs2 launch {addon}` on Windows")
        info("to start CS2 with the addon active.")
        return 0
    if not confirm_fn(f"Launch CS2 with `--addon {addon}` now?", False):
        info(f"Skipped. Run `csgo2cs2 launch {addon}` later when ready.")
        return 0
    return _run_subcommand(["launch", addon], args)


def _stage_farewell(addon: Optional[str]) -> None:
    header("All done")
    if addon:
        success(f"Addon ready: {addon}")
        print()
        print("Next steps:")
        print(f"  - Open CS2 and load the addon (or run `csgo2cs2 launch {addon}`).")
        print(f"  - Re-run `csgo2cs2 verify {addon}` after editing in Hammer 2.")
        print(f"  - Package for upload with `csgo2cs2 publish {addon}`.")
    else:
        info("No addon was created in this run. Re-run the walkthrough when ready.")
    print()
    print("VAC safety reminder:")
    print("  Running on a VAC server with the install patches applied is not recommended.")
    print("  When you are done porting for the session, run:")
    print(f"    {Fore.CYAN}csgo2cs2 doctor --unfix{Style.RESET_ALL}")
    print("  to restore import_map_community.py and vpk.signatures.")
    print()
    print("More info: `csgo2cs2 about` or `csgo2cs2 explain --list`.")


# ----- subcommand dispatch ------------------------------------------------


def _run_subcommand(argv: List[str], parent_args: argparse.Namespace) -> int:
    # Re-parse the requested subcommand through the top-level parser so it
    # picks up the same `--config` / `--verbose` flags the walkthrough was
    # invoked with. We import build_parser lazily to avoid a circular
    # import at module load time.
    from ..cli import build_parser

    parser = build_parser()
    full_argv = []
    if parent_args.config:
        full_argv.extend(["--config", parent_args.config])
    if getattr(parent_args, "verbose", False):
        full_argv.append("--verbose")
    full_argv.extend(argv)
    sub_args = parser.parse_args(full_argv)
    rc = sub_args.func(sub_args)
    return rc if rc is not None else 0


# ----- registration -------------------------------------------------------


STAGES = ("config", "tools", "patches", "port", "verify", "launch")


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Assume yes for every confirmation prompt (non-interactive).",
    )
    p.add_argument(
        "--from",
        dest="from_stage",
        choices=STAGES,
        default=None,
        help="Resume from a specific stage instead of starting at the beginning.",
    )
    p.add_argument(
        "--workshop",
        dest="workshop_url",
        default=None,
        help="Workshop URL or numeric ID (skips the prompt in the port stage).",
    )
    p.add_argument(
        "--addon",
        default=None,
        help="CS2 addon name (skips the prompt in the port stage).",
    )
    p.add_argument(
        "--no-launch",
        action="store_true",
        help="Skip the optional launch step at the end.",
    )
    p.set_defaults(func=run)


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "walkthrough",
        help="Interactive guided tour for a first-time map port.",
    )
    _add_common_args(p)

    # alias -- same handler, separately registered so `--help` lists it.
    alias = subparsers.add_parser(
        "tour",
        help="Alias for `walkthrough`.",
    )
    _add_common_args(alias)


# ----- entry point --------------------------------------------------------


def run(
    args: argparse.Namespace,
    *,
    prompt_fn: PromptFn = input,
    confirm_fn: Optional[ConfirmFn] = None,
) -> int:
    # under `--yes`, the walkthrough is non-interactive: swap the prompt
    # stand-in so we never block on stdin. tests rely on this too --
    # pytest's stdin capture raises OSError on windows for any `input()`
    # call, even if a default would be used.
    if args.yes and prompt_fn is input:
        prompt_fn = _noninteractive_prompt

    if confirm_fn is None:
        if args.yes:
            confirm_fn = lambda _q, _d: True  # noqa: E731
        else:
            confirm_fn = lambda q, d: _confirm(q, d, prompt_fn=prompt_fn)  # noqa: E731

    _print_welcome()
    if not confirm_fn("Ready to start?", True):
        info("Walkthrough cancelled. Re-run `csgo2cs2 walkthrough` any time.")
        return 0

    stages_to_run = list(STAGES)
    if args.from_stage:
        idx = STAGES.index(args.from_stage)
        stages_to_run = list(STAGES[idx:])
        info(f"Resuming from stage: {args.from_stage}")

    addon: Optional[str] = args.addon

    for stage in stages_to_run:
        if stage == "config":
            rc = _stage_config(args, confirm_fn=confirm_fn, prompt_fn=prompt_fn)
            if rc != 0:
                warn("Config stage did not complete cleanly. Continuing.")
        elif stage == "tools":
            rc = _stage_tools(args, confirm_fn=confirm_fn)
            if rc != 0:
                warn("Tools stage did not complete cleanly. Continuing.")
        elif stage == "patches":
            rc = _stage_patches(args, confirm_fn=confirm_fn)
            if rc != 0:
                warn("Patches stage did not complete cleanly. Continuing.")
        elif stage == "port":
            rc, addon = _stage_port(args, confirm_fn=confirm_fn, prompt_fn=prompt_fn)
            if rc != 0:
                warn("Port stage failed. Stopping the walkthrough.")
                _stage_farewell(None)
                return rc
        elif stage == "verify":
            if addon:
                _stage_verify(args, addon)
            else:
                info("Skipping verify -- no addon was created.")
        elif stage == "launch":
            if addon:
                _stage_launch(args, addon, confirm_fn=confirm_fn)
            else:
                info("Skipping launch -- no addon was created.")

    _stage_farewell(addon)
    return 0
