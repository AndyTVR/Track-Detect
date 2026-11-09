"""Build step: write build/beta.json with this build's version, date and
feedback address.

    python tools/stamp_beta.py --version 0.9.1 --email feedback@example.com
"""
import argparse
import datetime
import json
import os

ap = argparse.ArgumentParser()
ap.add_argument("--version", required=True)
ap.add_argument("--email", default="")
a = ap.parse_args()

with open("beta.json", encoding="utf-8") as fh:
    info = json.load(fh)
info["version"] = a.version.lstrip("vV")
info["build_date"] = datetime.date.today().isoformat()
if a.email:
    info["feedback_email"] = a.email
os.makedirs("build", exist_ok=True)
with open(os.path.join("build", "beta.json"), "w", encoding="utf-8") as fh:
    json.dump(info, fh, indent=1)
print(json.dumps(info, indent=1))
