# wrapper around valve's cs2 map importer.

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..platform_check import require_windows


@dataclass
class ImportInputs:
    # path to a folder that contains gameinfo.txt for the s1 (csgo) install,
    # and any compiled .mdl/.vmt/.vtf the map references.
    s1_gameinfo_dir: Path
    # path to a folder containing source content. the importer expects the
    # map at <s1_content_dir>/maps/<mapname>.vmf and instances/prefabs in the
    # same maps/ subtree. paths must not contain spaces.
    s1_content_dir: Path
    # path to a folder containing gameinfo.gi for the s2 (cs2) install.
    s2_gameinfo_dir: Path
    # name of an existing cs2 workshop addon. content lands under
    # <s2_install>/game/csgo_addons/<s2_addon>/.
    s2_addon: str
    # map name without .vmf extension. may include a subdir relative to
    # <s1_content_dir>/maps/, e.g. "my_maps/de_examplemap".
    mapname: str


class ImportMapTool:
    name = "import_map_community"

    def __init__(
        self,
        importer_path: str | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.importer_path = importer_path
        # Default to the *same* Python that's running csgo2cs2. The previous
        # default ("python") leaned on $PATH resolution, which on Windows
        # routinely picked up the Store stub or a system 3.11 lacking our
        # deps -- the importer would crash on `import colorama` before it
        # could do anything useful.
        self.python_executable = python_executable or sys.executable

    def resolve(self) -> Path | None:
        if not self.importer_path:
            return None
        p = Path(self.importer_path)
        return p if p.exists() else None

    # build the importer command line without running it. exposed so the
    # `port --dry-run` path can show users exactly what would execute.
    def build_command(
        self,
        inputs: ImportInputs,
        use_bsp: bool = True,
        no_merge_instances: bool = False,
        skip_deps: bool = False,
        extra_args: Sequence[str] | None = None,
    ) -> list[str]:
        importer = self.resolve()
        if not importer:
            raise RuntimeError("import_map_community.py not configured. Set the path in config.")
        cmd = [
            self.python_executable,
            str(importer),
            str(inputs.s1_gameinfo_dir),
            str(inputs.s1_content_dir),
            str(inputs.s2_gameinfo_dir),
            inputs.s2_addon,
            inputs.mapname,
        ]
        if use_bsp and no_merge_instances:
            cmd.append("-usebsp_nomergeinstances")
        elif use_bsp:
            cmd.append("-usebsp")
        if skip_deps:
            cmd.append("-skipdeps")
        if extra_args:
            cmd.extend(extra_args)
        return cmd

    # invoke the importer with the canonical 5 positional args plus optional flags.
    # see https://github.com/andreaskeller96/cs2-import-scripts (essentially valve's
    # script with python 3 fixes).
    def import_map(
        self,
        inputs: ImportInputs,
        use_bsp: bool = True,
        no_merge_instances: bool = False,
        skip_deps: bool = False,
        extra_args: Sequence[str] | None = None,
    ) -> subprocess.CompletedProcess:
        require_windows("import_map_community.py")
        cmd = self.build_command(
            inputs,
            use_bsp=use_bsp,
            no_merge_instances=no_merge_instances,
            skip_deps=skip_deps,
            extra_args=extra_args,
        )
        return subprocess.run(cmd, check=False, capture_output=True, text=True)
