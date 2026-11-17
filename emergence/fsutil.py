"""Saving files safely on Windows, including in synced folders.

Dropbox, OneDrive and virus scanners briefly lock a file while they read it.
Replacing it then fails with "Access is denied" (WinError 5) or "being used by
another process" (WinError 32). safe_replace waits and tries again, and as a
last resort copies the new contents over the old file."""
from __future__ import annotations

import os
import shutil
import time


def safe_replace(tmp: str, dst: str, wait_s: float = 4.0) -> None:
    delay, waited = 0.05, 0.0
    while True:
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if waited >= wait_s:
                break
            time.sleep(delay)
            waited += delay
            delay = min(delay * 2, 0.5)
    # still locked against renaming: write the contents into the existing file
    shutil.copyfile(tmp, dst)
    try:
        os.remove(tmp)
    except OSError:
        pass
