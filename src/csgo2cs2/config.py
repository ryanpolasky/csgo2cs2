# config loading and saving.

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import List

DEFAULT_CONFIG_DIR = Path.home() / ".csgo2cs2"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_WORKSPACE_DIR = DEFAULT_CONFIG_DIR / "workspace"


@dataclass
class Config:
    # external tool paths
    steamcmd_path: str | None = None
    bspsource_path: str | None = None  # bspsrc.jar or wrapper script
    vpkedit_path: str | None = None
    bspzip_path: str | None = None
    java_path: str | None = None  # optional override; PATH used otherwise
    import_script_path: str | None = None  # explicit import_map_community.py override
    python_executable: str | None = None  # python to invoke the importer with

    # cs:go/cs2 install layout
    csgo_install_path: str | None = None  # "Counter-Strike Global Offensive" folder
    cs2_addons_path: str | None = None  # <install>/game/csgo_addons
    cs2_bin_path: str | None = None  # <install>/game/bin/win64
    legacy_csgo_bin_path: str | None = None  # <install>/bin

    # workspace root for downloads, decompiles, manifests, reports
    workspace_dir: str = str(DEFAULT_WORKSPACE_DIR)

    # defaults applied during fixes
    # default replacement skybox used when --fix can't find a mood-aware
    # match. wiki-confirmed cs2 sky from
    # https://developer.valvesoftware.com/wiki/Counter-Strike_2_Workshop_Tools/CS2_Sky_List
    # picked for its neutral overcast lighting (brightness=0 in cs_office's
    # documented light_environment, so it doesn't overpower the map's
    # existing sun direction).
    default_skybox: str = "sky_cs_office"

    # override the analyzer's known-good CS2 sky list. None = use built-in.
    cs2_sky_list: List[str] | None = None

    # extra unsupported entity classnames the analyzer should flag (additive)
    extra_unsupported_entities: List[str] = field(default_factory=list)

    # steam username only; never store passwords here
    steam_login: str | None = None

    # behavior toggles
    auto_apply_doctor_fixes: bool = False
    steamcmd_retries: int = 3


def _resolve_path(path: str | None) -> Path:
    return Path(path).expanduser() if path else DEFAULT_CONFIG_PATH


def load_config(path: str | None = None) -> Config:
    p = _resolve_path(path)
    if not p.exists():
        return Config()
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    valid_keys = {f.name for f in fields(Config)}
    return Config(**{k: v for k, v in data.items() if k in valid_keys})


def save_config(config: Config, path: str | None = None) -> Path:
    p = _resolve_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(asdict(config), f, indent=2)
    return p


def config_path(path: str | None = None) -> Path:
    return _resolve_path(path)
