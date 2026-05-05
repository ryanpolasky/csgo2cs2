# register fixers on import.

from . import (
    asset_paths,  # noqa: F401  (asset_path_backslash fixer)
    entities,  # noqa: F401  (entity_unsupported / entity_deprecated_s2 fixer)
    light_environment,  # noqa: F401  (light_environment_count dedupe fixer)
    skybox,  # noqa: F401  (skybox_unknown / skybox_hdr_only fixer)
)
from .base import FixResult, apply_all, get, register  # noqa: F401
