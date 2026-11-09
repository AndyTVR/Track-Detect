"""Customer beta: version, licence acceptance and the trial period.

beta.json (bundled with the program, stamped by the build) says which build
this is. Beta rules only apply to the packaged program, or when TD_BETA=1 is
set for testing, so the in-house copy is never locked.

The trial lasts `trial_days` from the first time it was installed or run on
this computer, taken as the earliest of: the date the installer recorded in
the registry, and the date stored in the user's AppData. A build also stops
`hard_expiry_days` after it was made, so reinstalling can't extend a beta
forever.
"""
from __future__ import annotations

import datetime as _dt
import json
import os

INFO: dict = {}
STATE_FILE = None   # set by init()
REG_KEY = r"Software\Thermal Vision Ecology\Track and Detect"


def _today() -> _dt.date:
    return _dt.date.today()


def _parse(d):
    try:
        return _dt.date.fromisoformat(str(d)[:10])
    except (TypeError, ValueError):
        return None


def init(res_dir: str, data_dir: str, packaged: bool):
    global STATE_FILE
    try:
        with open(os.path.join(res_dir, "beta.json"), encoding="utf-8") as fh:
            INFO.update(json.load(fh))
    except (OSError, ValueError):
        INFO.update({"product": "Track & Detect", "version": "dev", "channel": "dev"})
    INFO["active"] = bool(packaged or os.environ.get("TD_BETA") == "1") and INFO.get("channel") == "beta"
    STATE_FILE = os.path.join(data_dir, "beta_state.json")
    if INFO["active"]:
        st = _state()
        if not _parse(st.get("first_run")):
            st["first_run"] = _today().isoformat()
            _save(st)


def _state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        return {}


def _save(st: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(st, fh, indent=1)
    except OSError:
        pass


def _registry_install_date():
    if os.name != "nt":
        return _parse(os.environ.get("TD_TEST_INSTALL_DATE"))
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            return _parse(winreg.QueryValueEx(k, "InstallDate")[0])
    except OSError:
        return None


def status() -> dict:
    """Everything the screen needs: version, licence and days left."""
    out = {"product": INFO.get("product", "Track & Detect"), "version": INFO.get("version", "dev"),
           "channel": INFO.get("channel", "dev"), "active": INFO.get("active", False),
           "company": INFO.get("company", ""), "feedback_email": INFO.get("feedback_email", "")}
    if not out["active"]:
        return out
    st = _state()
    starts = [d for d in (_parse(st.get("first_run")), _registry_install_date()) if d]
    start = min(starts) if starts else _today()
    ends = [start + _dt.timedelta(days=int(INFO.get("trial_days", 90)))]
    built = _parse(INFO.get("build_date"))
    if built:
        ends.append(built + _dt.timedelta(days=int(INFO.get("hard_expiry_days", 180))))
    end = min(ends)
    left = (end - _today()).days
    out.update({
        "started": start.isoformat(), "ends": end.isoformat(), "days_left": max(0, left),
        "expired": left <= 0,
        "licence_version": int(INFO.get("licence_version", 1)),
        "licence_accepted": int(st.get("licence_accepted", 0) or 0) >= int(INFO.get("licence_version", 1)),
    })
    return out


def accept_licence():
    st = _state()
    st["licence_accepted"] = int(INFO.get("licence_version", 1))
    st["licence_accepted_on"] = _dt.datetime.now().isoformat(timespec="seconds")
    _save(st)
    return status()


def blocked() -> str | None:
    """Why analysis is unavailable right now (None if it's fine)."""
    s = status()
    if not s["active"]:
        return None
    if s["expired"]:
        return "expired"
    if not s["licence_accepted"]:
        return "licence"
    return None
