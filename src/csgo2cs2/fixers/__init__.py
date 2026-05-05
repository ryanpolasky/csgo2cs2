# register fixers on import.

from . import (
    entities,  # noqa: F401  (registers entity_unsupported fixer)
    skybox,  # noqa: F401  (registers skybox_unknown fixer)
)
from .base import FixResult, apply_all, get, register  # noqa: F401
