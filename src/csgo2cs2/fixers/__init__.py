# register fixers on import.

from . import (
    asset_paths,  # noqa: F401  (asset_path_backslash fixer)
    clip_textures,  # noqa: F401  (texture_clip_custom fixer)
    entities,  # noqa: F401  (entity_unsupported / entity_deprecated_s2 fixer)
    light_environment,  # noqa: F401  (light_environment_count dedupe fixer)
    skybox,  # noqa: F401  (skybox_unknown / skybox_hdr_only fixer)
    vmf_top_level,  # noqa: F401  (vmf_missing_top_level_keys fixer)
)
from .base import FixResult, apply_all, get, register  # noqa: F401

