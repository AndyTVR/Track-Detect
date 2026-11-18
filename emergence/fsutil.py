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


import json as _json
import threading as _threading
import time as _time

_LOCKS: dict = {}
_LOCKS_GUARD = _threading.Lock()


def _lock_for(path):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(os.path.abspath(path), _threading.Lock())


def write_json(path: str, data, indent=1) -> None:
    """Save data as JSON safely: through a temporary file of its own (so two
    saves at once can't mix), one save of a file at a time, then swapped in."""
    with _lock_for(path):
        tmp = f"{path}.{os.getpid()}-{_threading.get_ident()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                _json.dump(data, fh, indent=indent)
            safe_replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


DAMAGED = []   # (file, kept copy) noted this session, for the error log


def read_json(path: str):
    """The JSON in path; None if there's no file. A file that's there but
    can't be read as JSON (half-written, or half-synced by Dropbox) is kept as
    <name>.damaged-<date-time> before anything replaces it, and None returned."""
    try:
        with open(path, encoding="utf-8") as fh:
            return _json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeDecodeError):
        keep = f"{path}.damaged-{_time.strftime('%Y%m%d-%H%M%S')}"
        try:
            shutil.copyfile(path, keep)
            DAMAGED.append((path, keep))
        except OSError:
            pass
        return None


# ---- where a recording's own files go (analysis, activity, caches)
# Set by the program to its project-folder rule (see org.analysis_dir); left
# unset, files sit beside the recording as they always used to. Files found in
# an older place (beside the recording, or in another project's folder) are
# moved to the new one the first time they're used.
SIDE = {"dir": None, "others": None}


def side_path(path: str, ext: str) -> str:
    rule = SIDE["dir"]
    legacy = path + ext
    if rule is None:
        return legacy
    try:
        d = rule(path)
    except Exception:
        return legacy
    if not d:
        return legacy
    new = os.path.join(d, os.path.basename(path) + ext)
    if os.path.exists(new):
        return new
    olds = [legacy]
    try:
        olds += [os.path.join(o, os.path.basename(path) + ext) for o in (SIDE["others"](path) if SIDE["others"] else [])]
    except Exception:
        pass
    for o in olds:
        if os.path.normcase(os.path.abspath(o)) != os.path.normcase(os.path.abspath(new)) and os.path.exists(o):
            try:
                os.makedirs(d, exist_ok=True)
                shutil.move(o, new)
                return new
            except OSError:
                return o   # couldn't move it (in use, say): carry on with it where it is
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return legacy
    return new
