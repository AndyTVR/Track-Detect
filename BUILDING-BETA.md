# Making a customer beta of Track & Detect

GitHub builds the customer version automatically on one of its Windows
machines. Each build:

1. **Scrambles the screen files.** The HTML, CSS and JavaScript are minified,
   and their names are scrambled.
2. **Compiles the Python into machine code** with Nuitka. The installed
   program contains no readable Python source.
3. **Wraps it in an installer**:
   `Track-and-Detect-Beta-<version>-Setup.exe`.

The installer is per-user, so it needs no administrator rights. It adds a
Start-menu entry, a desktop icon, and an uninstaller in Settings > Apps.

## One-time set-up

1. On GitHub, create a **private** repository, for example
   `track-and-detect`.
2. Put this folder in it. Either connect GitHub to Claude and ask Claude to
   push it, or use *Add file > Upload files* on the repository page and drag
   in everything in this folder, including the `.github` folder.
3. Feedback emails go to `enquiry@thermalvisionecology.co.uk`, which is set
   in `beta.json`. To send them somewhere else for one build without editing
   the file, open **Settings > Secrets and variables > Actions > Variables**
   and add a repository variable named `FEEDBACK_EMAIL` with the other
   address.

## Making a build

**Actions > Build customer beta > Run workflow.** Type a version number,
such as `0.9.1`, and click **Run workflow**. It takes about 15–30 minutes the
first time, and less after that.

When it's finished, open the run and download the installer from
**Artifacts**. GitHub delivers it as a zip, and the Setup .exe is inside.

To publish a downloadable release instead, push a tag such as `v0.9.1`. The
installer is then attached to a GitHub **Release** marked "Pre-release".

Use a new version number for every build you give to customers. Feedback
emails and PDF reports show the version, so you can tell which build a
customer has.

## What customers see

- **A Windows warning.** Because the program isn't code-signed, Windows may
  show "Windows protected your PC". Tell customers to click **More info >
  Run anyway**. A code-signing certificate removes this for the full release.
- **The beta licence.** It's shown in the installer, and again on first
  launch, where they must click *I accept*.
- **A "BETA" badge** in the top bar. Hovering over it shows the version and
  the trial end date. A countdown appears in the last 14 days.
- **A 90-day trial** from the first install on that computer. Reinstalling
  doesn't restart it. Each build also stops working 180 days after it was
  built, whatever happens.
- **Feedback.** The **Feedback** button lets customers report a bug,
  something not working, or a feature idea. It saves a small zip on their
  desktop and opens a ready-made email to `FEEDBACK_EMAIL` to attach it to.
  - The zip contains: what they typed, the software and Windows version,
    their settings, the error logs, and the type of recording (camera,
    resolution, frame rate).
  - It never contains recordings, images or file names.

## Changing the beta rules

Edit `beta.json`:
- `trial_days`: length of the trial.
- `hard_expiry_days`: days after a build is made before it stops working.
- `licence_version`: increase this to make everyone accept an updated
  licence.

Edit `LICENCE-BETA.txt` to change the licence wording. It's a draft, so have
it checked before the first customer build.

## Testing the beta screens without building

On your own copy, set `TD_BETA=1` before starting:

    set TD_BETA=1 && .venv\Scripts\python.exe app.py

That shows the licence, badge and trial exactly as customers see them.
