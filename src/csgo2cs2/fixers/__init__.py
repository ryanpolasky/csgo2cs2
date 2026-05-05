# register fixers on import.

from . import skybox  # noqa: F401  (registers skybox_unknown fixer)
from . import entities  # noqa: F401  (registers entity_unsupported fixer)
from .base import FixResult, apply_all, get, register  # noqa: F401
