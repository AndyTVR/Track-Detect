# Track & Detect

*by Thermal Vision Ecology*

Opens FLIR `.ats` recordings directly, without Research Studio, and runs the
TVE bat-emergence method from the analysis manual with far fewer clicks.
Everything runs on your own computer. Nothing is uploaded.

## Install (once)

1. Install **Python 3.11 or newer** from python.org. In the installer, tick
   **"Add python.exe to PATH"**.
2. Double-click **Install.bat**. It sets up a private environment in this
   folder, which needs internet once and about 150 MB.

## Make a Windows program (.exe)

After Install.bat, double-click **Build Windows app.bat**. It needs internet
once and takes a few minutes. It:
- builds **Track and Detect.exe** in `dist\Track and Detect`
- puts a **Track and Detect** shortcut, with its own icon, on your desktop
- copies your current settings across
- makes **Track and Detect for Windows.zip** to give to colleagues. They
  unzip it anywhere and double-click Track and Detect.exe, with no Python or
  Install.bat needed.

The program opens in **its own window**, with its own taskbar button and
icon, and no black window behind it. It uses Microsoft Edge, which is part
of Windows 10 and 11, to show the app. Nothing else needs installing.
- Close the window, or click **Quit** in the top bar, to close the program.
  If a scan or export is still running, it finishes that first.
- If you'd rather use a normal browser tab, choose it in **Settings >
  Appearance > Open Track & Detect in**. In a tab, the program closes itself a
  few minutes after the tab is closed.
- Double-clicking it while it's already running just opens another tab.
- Settings and logs are kept in `%APPDATA%\Track and Detect`.

Run **Build Windows app.bat** again after any update to rebuild the program.

## Use

Double-click the **Track and Detect** desktop shortcut, or **Run Track and
Detect.bat**. The app opens in its own window. Closing that window, or
clicking **Quit** in the top bar, closes it.

1. **Add recordings.** Choose individual `.ats` files, a whole survey
   folder, or paste paths, one per line. Remove a file from the list with
   its **×**. Each file shows its status.
2. **Draw ROI.** Click **Draw ROI**, then pick a shape:
   - **Points**: click around the roost features. A line follows your cursor
     from the last point, with a dashed line back to the start.
     Backspace removes the last point.
   - **Rectangle** or **Circle**: a shape appears in the middle of the
     picture. Drag the middle to move it, drag an edge or corner handle to
     resize it, or drag on the picture to draw a new one.

   Click **Finish** (or press Enter) to save it, or **Cancel** (Esc) to leave
   the current ROI as it is. Keep the sky out, but leave a thin strip above
   the roofline. If the camera didn't move, tick *Use this ROI for every
   listed file from the same folder*.
3. **Scan recording** or **Analyse all listed.** One pass builds the
   activity plot for the ROI and shows progress as it goes. The scan always
   uses **Window Average (3×3) + Sliding Subtraction (5 frames)**, whichever
   mode is showing. Recordings scanned with older settings are flagged in
   the Detection panel so you can scan them again.
   A very large spike at the end of a recording is always left out of the
   analysis. This is typically someone walking up to the camera, or the
   camera being moved or switched off. The spike has to run to within 2 s of
   the end and be at least 3 times taller than anything else in the
   recording. It never becomes an event, and it doesn't affect the suggested
   level or set the plot's height. It's shaded grey on the plot and noted in
   the PDF report. The final frame of every recording is never used either.
4. **Set the detection level.** The activity plot has a dashed **blue
   line**. Spikes above it (amber) become numbered events, and anything below
   it (grey) is ignored. Drag the line up or down, type a level, or click
   **Suggested**. Events update straight away. Decisions you've already made
   are kept, even if you move the line away and back.
   - Scroll on the plot to zoom, drag to pan, and click to jump to that
     moment.
   - **Time window**: drag either handle to show just part of the
     recording, or drag the shaded bar to slide that window along.
   - **Y-axis**: stops one tall spike flattening the others. These options
     only change the view, not which events are found.
     - **Auto** (default) cuts off spikes more than twice the height of the
       next one down, marked ▲, so the rest stay clear. It looks at every
       spike in view, including ones below the line.
     - **Log** squeezes tall spikes down so small ones stay visible.
     - **Full height** shows everything as it is.
     - The slider sets your own cap.
   - Use **Enlarge** for a bigger plot.
5. **Review each event.** Click a marker or event card. The app jumps to the
   event and plays within a window 3 s either side. Untick *Stay in event
   window* to play past it. Use the controls under the picture to watch it:

   | Button | Does |
   |---|---|
   | ⏮ / ⏭ | Go to the start or end (keys `Home` / `End`) |
   | ◀ | Play backwards |
   | ◀❙ / ❙▶ | Step back or forward one frame (`←`/`→`; hold Shift to jump 1 s) |
   | ▶ | Play / pause (`Space`) |
   | Speed | ¼× to 4× |

   Then choose a classification and **Confirm** or **Reject** the event.
   **Undo** clears your decision.

   To begin the review again, click **Start over…** in the Detection panel.
   It clears every Confirm, Reject and classification, then rescans the
   recording with your current settings. You can also reset the detection
   level to the new suggested level, and delete all comments. Files you've
   already exported are kept.
6. **Add comments.** Each event card lists its comments underneath. In the
   selected event, type in its comment box and click **Add comment** (or
   press Ctrl + Enter). The comment is pinned to the current moment, or to
   the start of the event if you're outside its window. Comments at other
   times go in the **Other comments** panel. Click a comment to jump to it,
   or × to delete it.
7. **Export event pack.** One click saves these files to `exports\`
   beside the recording:
   - the flight-path still
   - the flight-path clip
   - the high-sensitivity clip
   - a blended still and a blended clip, both using the blend type, opacity
     and range set in the app. The still is taken at the event's peak for an
     overlay. For a crossfade it's taken a Max Frame Interval's worth of frames
     (5 by default) after activity is first seen, so the trail has built up.
   - a still of the frame where each animal first appears

   **Save events CSV** writes a table of events for the report, with their
   comments. If there are any comments, it also writes `<name>_comments.csv`
   listing every comment with its time.

The **Viewing Mode** panel has three modes:
- `1` **Thermal** (default): the plain thermal picture, with no filters.
- `2` **High Sensitivity Mode**: moving animals show as bright trails.
- `3` **Flight path**: the whole route is built up in one image.
- `4` **Blended**: a mix of the thermal and High Sensitivity pictures, in the
  current palette. Choose how to mix them with **Blend**:
  - **Overlay**: the trails are laid over the thermal picture, and the rest
    stays thermal. Opacity sets how solid the trails are.
  - **Crossfade**: the two whole pictures are mixed. 0% is thermal only and
    100% is High Sensitivity only.

  The colour bar adjusts the thermal picture underneath.

**Frame persistence** (the ▾ on the High Sensitivity Mode tab) sets how many frames the Max Frame Interval and Sliding
Subtraction filters use in High Sensitivity Mode (1–60; the default is
5 / 5). Longer persistence gives longer, brighter trails. It changes the view
straight away, and exports use it too. It doesn't change the scan, which
always uses Window Average + Sliding Subtraction 5. It applies to every
recording. To keep a change for next time, save it in **Settings**.

**Palette**: pick White hot, Black hot, Iron, Rainbow, Lava or Arctic
from the menu beside the Viewing Mode buttons. Exports and the PDF report
use it too.

**Image clean-up**: two tick-boxes beside the palette, each with a Low /
Medium / High strength.
- **Detail enhancement** boosts local contrast, bringing out roof edges,
  vegetation and animals against smooth sky, even when one hot area takes up
  most of the colour range. It applies to Thermal, Flight path and Blended.
  Higher strengths also boost noise.
- **Noise reduction** averages each pixel over recent frames, but only where
  nothing is moving, so the still background gets cleaner while bats stay
  sharp. It applies to Thermal and Blended. High removes the most grain but
  takes a moment longer to settle after you jump to a new point.

Neither applies to High Sensitivity Mode, so they're greyed out there.
Exports and the PDF report use them too. **Neither ever changes the scan or
which events are found.**

Changes made in the Viewing Mode bar last until you close the program. Each
recording opens with the defaults from **Settings > Viewing**. Click *Use the
current view settings* there, then **Save settings**, to keep your current
view as the default.

**Visible range**: the colour bar on the right of the picture shows how
values map to colours. Drag the **top handle** to set the hottest value
shown (anything above is the top colour). Drag the **bottom handle** to set
the coldest value shown (anything below is the bottom colour). Narrowing
the range boosts contrast on small temperature differences. You can also
click a handle and use ↑/↓ (Shift for bigger steps). **Auto** sets the
range for each frame automatically. Thermal and Flight path each keep their
own range. High Sensitivity Mode always sets contrast automatically from
each frame's highest and lowest values, so the colour bar is faded and
stays still in that mode. Exported clips and stills use the range you set.

Switching mode only changes what you see.

Each view sets its own colour scale. Other shortcuts: `n`/`p` move to the next or previous event.

## Settings

Click **Settings** in the top bar. Change what you need, then click **Save
settings** to keep it for next time. **Cancel** leaves everything as it was.
Settings are saved in `settings.json` in the program folder.

| Section | What you can set |
|---|---|
| Appearance | Colour scheme (Forest, the Thermal Vision Ecology greens, or Ocean, Teal, Heather, Slate) and Dark / Light mode. Changes preview straight away. |
| Viewing | The palette, detail enhancement, noise reduction, blend type and opacity, playback speed and frame persistence each recording opens with. *Use the current view settings* copies what's on screen now. |
| Detection | Suggested-level sensitivity (Low = fewer events, High = more), merge gap, shortest event kept, and the review window either side of an event. Changing these re-finds events straight away. Your decisions and comments are kept. *Reset detection to recommended* undoes them. |
| Exports | Default export folder, which items are ticked, overlays, timestamp text size, file-name order, video quality and slow-motion export (½ or ¼ speed). |
| Time & units | °C or °F, UK time or UTC, and a camera clock correction in seconds if a camera's clock was wrong. It applies to everything shown, exported and reported. Switching °C/°F converts scans already done; no rescan needed. |
| Classifications | Your own list for the Classification menu, for example species groups. |
| Review | Jump to the next unreviewed event after Confirm / Reject. Start playing when an event is selected. |
| Report details | Company, contact, analyst and camera for PDF reports. |
| Shortcuts | A list of keyboard shortcuts. |

At the bottom of the dialog:
- **Reset all to defaults** fills in the original settings; Save to use them.
- **Export settings…** saves a settings file.
- **Import settings…** loads one, so everyone on the team can analyse with
  the same set-up.

Amber always means "needs attention" (events still to review, warnings) in
every colour scheme. The detection line is always blue. Colour schemes
don't affect the thermal picture.

## What it saves next to each recording

| File | What it holds |
|---|---|
| `<name>.ats.layout.json` | Where frames sit in the file, so it opens instantly next time |
| `<name>.ats.analysis.json` | ROI, detection level, events, your decisions and comments |
| `<name>.ats.activity.npy` | The activity trace, so you don't need to rescan |

Delete these to start a recording from scratch. The `.ats` file itself is
never changed.

## Check a file decodes correctly

Drag an `.ats` file onto **Check a file.bat**. It prints the camera, size,
frame count and temperatures, and saves `<name>_check.png` showing the
start, middle and end frames. If those look like your footage, the program
reads that camera's files correctly.

## Known limits (prototype)

- The `.ats` reader was worked out from real files and doesn't use FLIR's
  SDK. It's tested on an RS8481 (1280×1024) recording. **Check A70 and A700
  files with "Check a file" before relying on them.**
- Times are shown in UK time: BST in summer and GMT in winter, changing on
  the official dates. Dates are shown as dd/mm/yyyy. This applies everywhere: the app, the picture overlay,
  exports and CSVs. The camera stores its start time in UTC, and the app
  converts it.
- Frame rate isn't stored anywhere the program can find. It defaults to
  16 Hz, as Research Studio shows. Change it in the top bar if a camera
  recorded at a different rate, because timestamps depend on it.
- Temperatures: A70/A700 "Temperature (Factory)" data is read as 0.01 K per
  count. Files saved in counts show as counts, which still works for
  detection.
- Bat tracking finds compact warm objects that move. Very slow or very
  distant bats, rain, and swaying vegetation can still need your eye. That's
  why every event waits for your decision.
