# steamcmd adapter.

from __future__ import annotations

import subprocess
import time
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

    def expected_workshop_path(self, workshop_id: str, app_id: str = CSGO_APP_ID) -> Optional[Path]:
        root = self.steamcmd_root()
        if not root:
            return None
        return root / "steamapps" / "workshop" / "content" / app_id / workshop_id

    # run steamcmd to download one workshop item, retrying on transient
    # failures. anonymous workshop_download_item is famously flaky.
    def download_workshop_item(
        self,
        workshop_id: str,
        app_id: str = CSGO_APP_ID,
        login: Optional[str] = None,
        retries: int = 3,
        backoff_seconds: float = 5.0,
    ) -> subprocess.CompletedProcess:
        login_arg = login or "anonymous"
        args = [
            "+login",
            login_arg,
            "+workshop_download_item",
            app_id,
            workshop_id,
            "+quit",
        ]
        attempts = max(1, retries)
        last: Optional[subprocess.CompletedProcess] = None
        expected = self.expected_workshop_path(workshop_id, app_id)
        for i in range(attempts):
            last = self.run(args, check=False)
            # success heuristic: the expected workshop path now contains a .bsp
            if expected and expected.exists() and any(expected.glob("*.bsp")):
                return last
            if i < attempts - 1:
                time.sleep(backoff_seconds * (i + 1))
        assert last is not None
        return last
