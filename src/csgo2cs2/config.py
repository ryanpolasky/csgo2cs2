# config loading and saving.

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG_DIR = Path.home() / ".csgo2cs2"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_WORKSPACE_DIR = DEFAULT_CONFIG_DIR / "workspace"


@dataclass
class Config:
    # external tool paths
    steamcmd_path: Optional[str] = None
    bspsource_path: Optional[str] = None        # bspsrc.jar or wrapper script
    vpkedit_path: Optional[str] = None
    bspzip_path: Optional[str] = None
    java_path: Optional[str] = None             # optional override; PATH used otherwise

    # cs:go/cs2 install layout
    csgo_install_path: Optional[str] = None     # "Counter-Strike Global Offensive" folder
    cs2_addons_path: Optional[str] = None       # <install>/game/csgo_addons
    cs2_bin_path: Optional[str] = None          # <install>/game/bin/win64
    legacy_csgo_bin_path: Optional[str] = None  # <install>/bin

    # workspace root for downloads, decompiles, manifests, reports
    workspace_dir: str = str(DEFAULT_WORKSPACE_DIR)

    # defaults applied during fixes
    default_skybox: str = "sky_day01_01"

    # steam username only; never store passwords here
    steam_login: Optional[str] = None

    # behavior toggles
    auto_apply_doctor_fixes: bool = False


def _resolve_path(path: Optional[str]) -> Path:
    return Path(path).expanduser() if path else DEFAULT_CONFIG_PATH


def load_config(path: Optional[str] = None) -> Config:
    p = _resolve_path(path)
    if not p.exists():
        return Config()
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    valid_keys = {f.name for f in fields(Config)}
    return Config(**{k: v for k, v in data.items() if k in valid_keys})


def save_config(config: Config, path: Optional[str] = None) -> Path:
    p = _resolve_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(asdict(config), f, indent=2)
    return p


def config_path(path: Optional[str] = None) -> Path:
    return _resolve_path(path)
