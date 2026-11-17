"""Shared set-up for the automated tests.

Each test gets its own throwaway folder: the test recordings are linked into
it (so anything saved beside them stays there), the settings and projects go
in it, and the program starts from a clean slate. Nothing real is touched.

The test recordings are too big for the repository. They're looked for in
the folder named by TD_TESTDATA (default /home/claude/td-testdata); tests
that need a missing one are skipped. See tests/README.md.
"""
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TESTDATA = os.environ.get("TD_TESTDATA", "/home/claude/td-testdata")

# name in the test folder -> what it is
FILES = {
    "synthetic.ats": "RS8481 counts, 160 frames, two bat passes",
    "rhino front 1.ats": "RS8481 counts, 20 frames",
    "rhino front 2.ats": "RS8481 counts, 20 frames",
    "rhino rear 1.ats": "RS8481 counts, 20 frames",
    "a700_0.01K.ats": "FLIR A700, temperature stored as 0.01 K",
    "a700_raw.ats": "FLIR A700 raw sensor values (St Fagans front 1, short)",
    "a70_raw.ats": "FLIR A70 raw sensor values (SWT 0010)",
}

os.environ.setdefault("TD_DATA", os.path.join(ROOT, ".test-data"))   # before the program is loaded
import app as td_app  # noqa: E402


def need(*names):
    missing = [n for n in names if not os.path.exists(os.path.join(TESTDATA, n))]
    if missing:
        pytest.skip(f"test recording(s) not found in {TESTDATA}: {', '.join(missing)}")


class TD:
    """The program, fresh, with helpers for the tests."""

    def __init__(self, folder):
        self.folder = folder
        self.rec_dir = os.path.join(folder, "recordings")
        os.makedirs(self.rec_dir, exist_ok=True)
        self.client = td_app.app.test_client()

    def path(self, name, sub=""):
        """The test recording `name`, linked into this test's folder (optionally a sub-folder)."""
        need(name)
        d = os.path.join(self.rec_dir, sub) if sub else self.rec_dir
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        if not os.path.exists(p):
            os.symlink(os.path.realpath(os.path.join(TESTDATA, name)), p)
        return p

    def call(self, method, url, body=None, status=200):
        r = self.client.open(url, method=method, json=body)
        assert r.status_code == status, f"{method} {url} -> {r.status_code}: {r.get_data(as_text=True)[:500]}"
        return r.get_json() if r.is_json else r

    def get(self, url, status=200):
        return self.call("GET", url, status=status)

    def post(self, url, body=None, status=200):
        return self.call("POST", url, body or {}, status=status)

    def org(self, **body):
        return self.post("/api/org", body)

    def add(self, *paths, target=None):
        return self.post("/api/add", {"paths": list(paths), "target": target})

    def wait_jobs(self, timeout=180):
        t0 = time.time()
        while time.time() - t0 < timeout:
            jobs = self.get("/api/jobs")["jobs"]
            if not any(j["state"] in ("queued", "running") for j in jobs):
                return jobs
            time.sleep(0.2)
        raise AssertionError("jobs didn't finish")

    def last_job(self):
        return self.wait_jobs()[-1]

    def files(self):
        return self.get("/api/files")


@pytest.fixture
def td(tmp_path):
    from emergence import ats, settings as cfg
    from emergence import session
    data = str(tmp_path / "data")
    os.makedirs(data, exist_ok=True)
    td_app.jobs.cancel()
    # a clean slate
    td_app.DATA = data
    td_app.SETTINGS_PATH = os.path.join(data, "settings.json")
    td_app.state.update(files=[], current=None)
    td_app.recs.clear()
    td_app._ORG.update(projects=[], of={}, n=0, loaded=False)
    session.JOINS.clear()
    td_app.JOIN_CAM.clear()
    td_app.CAM_JOIN.clear()
    td_app._TIMES.clear()
    ats.TEMP["unit"] = "C"
    cfg.load(td_app.SETTINGS_PATH)
    td_app._apply_settings()
    t = TD(str(tmp_path))
    yield t
    t.wait_jobs()
    for r in list(td_app.recs.values()):
        try:
            r.src.close()
        except Exception:
            pass
    td_app.recs.clear()
