# Automated tests

Run them from the project folder:

    python -m pytest tests -q

They need the test recordings, which are too big for the repository. Put
them in a folder and point `TD_TESTDATA` at it (the default is
`/home/claude/td-testdata`):

| File | What it is |
|---|---|
| `synthetic.ats` | RS8481 counts, 160 frames, two bat passes |
| `rhino front 1.ats`, `rhino front 2.ats`, `rhino rear 1.ats` | RS8481 counts, 20 frames each |
| `a700_0.01K.ats` | FLIR A700, temperature stored as 0.01 K |
| `a700_raw.ats` | FLIR A700 raw sensor values (St Fagans front 1, short) |
| `a70_raw.ats` | FLIR A70 raw sensor values (SWT 0010) |

A test whose recording is missing is skipped, not failed. Each test works in
its own throwaway folder, so nothing real is changed.

`tests/ui_smoke.js` checks the page in a real browser (needs Node and
Playwright): start the program with `python app.py --port 8897 --no-browser`
(with `TD_DATA` set to an empty folder), then `node tests/ui_smoke.js`.
