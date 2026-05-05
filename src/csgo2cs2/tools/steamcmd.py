# steamcmd adapter.

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .base import ToolAdapter

CSGO_APP_ID = "730"


class SteamCMD(ToolAdapter):
    name = "steamcmd"

    # return the folder containing the steamcmd executable.
    def steamcmd_root(self) -> Optional[Path]:
        resolved = self.resolve()
        if not resolved:
            return None
        return Path(resolved).parent

    def expected_workshop_path(
        self, workshop_id: str, app_id: str = CSGO_APP_ID
    ) -> Optional[Path]:
        root = self.steamcmd_root()
        if not root:
            return None
        return root / "steamapps" / "workshop" / "content" / app_id / workshop_id

    # run steamcmd to download one workshop item.
    def download_workshop_item(
        self,
        workshop_id: str,
        app_id: str = CSGO_APP_ID,
        login: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        login_arg = login or "anonymous"
        args = [
            "+login", login_arg,
            "+workshop_download_item", app_id, workshop_id,
            "+quit",
        ]
        return self.run(args, check=False)
