"""Check that an .ats file decodes correctly before analysing it.

    python check_file.py "C:\\path\\to\\front 2.ats"

Prints what was found in the file and saves three frames (start, middle,
end) as PNGs beside it. If they look like your footage, the file is fine.
"""
import os
import sys

import cv2
import numpy as np

from emergence.ats import ATSFile


def main(path):
    f = ATSFile(path)
    info = f.info()
    for k in ("camera", "width", "height", "frames", "units", "start"):
        print(f"{k:>8}: {info[k]}")
    print(f"  layout: first frame at byte {f.layout.first}, {f.layout.stride} bytes per frame")
    stem = os.path.splitext(path)[0]
    tiles = []
    for i in (0, f.n_frames // 2, f.n_frames - 1):
        a = f.frame(i)
        lo, hi = np.percentile(a, [1, 99.7])
        g = np.clip((a - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
        tiles.append(cv2.resize(g, (320, int(320 * f.height / f.width))))
        if f.units == "°C":
            print(f"  frame {i}: {a.min():.1f} to {a.max():.1f} °C, median {np.median(a):.1f} °C")
    out = stem + "_check.png"
    cv2.imwrite(out, np.hstack(tiles))
    print(f"\nSaved {out}: start, middle and end frames. They should look like your footage.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
