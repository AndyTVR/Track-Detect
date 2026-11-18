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

A start window asks what you'd like to do: **Open existing analysis
project**, **New analysis project**, **Open existing pre-survey template**
or **New pre-survey template**. **Skip** carries on with whatever is listed.

A **pre-survey template** is a project planned before the survey: its Site
Plan opens straight away, so you can find the site and place the cameras
and acoustic detectors where they will go. Each time the Site Plan is
closed, it's saved as the project's site plan template. On the night, add
the recordings to its cameras, or start a new survey from the template.

1. **Add recordings.** Click the folder button in the top bar. It offers:
   - **New analysis project…**: name a project (and Survey 1's date if you like),
     then add recordings straight into it;
   - **New pre-survey template…** and **Open pre-survey template…**, as in
     the start window;
   - **Open analysis project…**: every project you've made, with its surveys,
     cameras and recordings. **Open** lists all its recordings again (any
     that have been moved or deleted are skipped);
   - **Add files…**, also on the **Add Recording** button in the middle of
     the empty picture.

   In the Add dialog: choose individual `.ats` files, a whole survey folder,
   or paste paths, one per line (the box grows as you add lines, then
   scrolls). The first
   recording added opens straight away. Remove a file from the list with
   its **×** (the file itself isn't deleted). Each file shows its times and
   status.

   **Projects, surveys and cameras**: the list is organised
   **Project › Survey › Camera**. A project is a site, a survey is one visit
   or night there (Survey 1, Survey 2 …, each with an optional date), and
   each survey has numbered cameras (Camera 1, Camera 2 …), each with an
   optional name such as "Front elevation".
   - Under **Assign recordings**, the Add dialog asks where to put them:
     - **Leave unassigned**: they go in the **Unassigned** box at the top of
       the list, and can be assigned after upload.
     - **Assign files to New/Existing Project**: pick an existing project,
       survey and camera or make new ones (a new survey can be given its
       date), or choose **Sort automatically by file name**: files from one
       folder with the same name share a camera ("front 1", "front 2" →
       Camera: Front).
     - **Auto-assign from folder names**: the project, survey and camera
       come from the folders. Subfolders of a chosen folder are included.
       A date in a folder name (10.8.26, 10-08-2026 or 2026-08-10) becomes
       the survey's date. For example:
       - `St Fagans 10.8.26\front 1.ats` → project St Fagans, survey dated
         10/08/2026, Camera: Front (cameras come from the file names);
       - `BCT\19.10.26\rear 1.ats` → project BCT, survey dated 19/10/2026,
         Camera: Rear;
       - `Barn\24.8.26\Roof\rec 1.ats` → project Barn, survey dated
         24/08/2026, Camera: Roof.

       Projects with the same name, surveys with the same date and cameras
       with the same name are reused, so adding more files later puts them
       in the right place.
   - A project name can only be used once. If you type the name of a
     project that already exists, the dialog says so straight away and
     won't add until you pick the existing project or change the name.
     **Open analysis project** shows **Already open** for a project whose recordings
     are all listed.
   - **+ Project** (at the top of the list) starts a project with Survey 1
     and Camera 1. **+ Survey** and **+ Camera** add more.
   - **Drag** a recording onto a camera to move it there, or onto
     Unassigned to take it out. The **⤢** beside a recording does the same
     from a list. **+ Add files** on a camera adds recordings straight into
     it.
   - Click a project's or camera's name to rename it. Set or change a
     survey's date with its date box; it can be left blank.
   - The **⤢** on a camera moves the camera, with its recordings, to another
     survey. The bin deletes a project, survey or camera; its recordings go
     back to Unassigned (no files are deleted).
   - **Scan project**, **Scan survey** and **Scan camera** scan every
     recording in it; **Scan unassigned** scans the unassigned ones. Each
     uses its own ROIs.
   - A camera's recordings are **joined automatically** as soon as it has
     two or more (added with the Add dialog, or dragged onto it). **Join
     files** does the same by hand; it stitches the
     camera's consecutive recordings into one: they play, scan, plot and are
     reviewed as one continuous recording, in time order, shown at the top
     of the camera as **Joined**, with the files it's made from listed
     underneath. Nothing is written to the original files; the joined
     recording's work is saved beside the first file as
     `Joined recording <id>.ats.analysis.json` (and `.activity.npz`). If the
     camera wasn't recording between two files, the gap is kept at its real
     length: the activity there is a flat line at zero, it doesn't count
     towards the suggested level or the noise rating, and the picture shows
     "No recording here". Times stay true throughout. Scan camera, survey and
     project scan the joined recording instead of the separate files, and the
     camera buttons and "View this time on" use it too. **Separate files**
     goes back to the separate recordings (their own scans are kept), and
     that camera then isn't joined again automatically. A large spike at the
     end of each file (cameras often write a few very hot frames as they
     stop) is left out, as at the end of a single recording. Adding
     or removing a file from a joined camera starts its joined scan afresh,
     because the frames no longer line up. Files of different picture sizes
     can't be joined.
   - The **▾** beside a project, survey or camera folds it up (▸ opens it
     again); the button beside **Tree** folds or opens everything. Cameras
     start folded, showing just their buttons: click a camera's box to show
     it. The program remembers what you've opened or folded.
   - The Event Log names the camera you're looking at (camera, survey,
     project), or "Unassigned".
   - The **⚙** beside PROJECT holds the project's options: **Save project**
     (everything is saved as you go; this also writes `<project>.tdproject`
     beside its recordings, a project file to keep or share), **Rename**,
     **Site plan**, **New survey** (from the site plan, if there is
     one), **Open recordings folder**, **Close project** (takes its
     recordings off the list; reopen it from the folder button > Open
     project), **Reset all decisions** and **Delete project** (its
     recordings move to Unassigned; no files are deleted). Open project also
     has **Open a project file…** for a `.tdproject` file, for example from
     another computer; recordings that have moved are looked for beside the
     project file.
   - **Site Plan** (on each project) opens a satellite map of the site.
     Search for a place or postcode (or type latitude, longitude), then
     **Set site here** to pin the site. Pick a survey and enter its
     **Surveyor(s)**.
     - **Cameras**: **+ Add camera** adds a camera to the survey and puts it
       on the map (handy when planning before a survey); the box beside each
       camera's number names it. Each camera's and detector's details fold to
       one summary line with its ▸ / ▾ button; picking one on the map opens it.
       **Place on map** each camera, drag its numbered pin to
       where it stood, and drag the white dot at the end of its cone to turn
       it and set how far it reaches (or type the facing in degrees and the
       range in metres). Choose the camera and lens (FLIR A70 29°, 51° or
       95°; FLIR A700 14°, 24°, 42° or 80°; or another angle) and who set it
       up. Each camera shows its **pixel size** at that range, worked out
       as FLIR's FOV calculator does: the lens's spatial resolution (IFOV)
       × the range, using FLIR's datasheet figures for 640 × 480 (A70: 29°
       0.84, 51° 1.5, 95° 2.9 mrad; A700: 14° 0.38, 24° 0.67, 42° 1.2,
       80° 2.6 mrad). 1 mrad at 1 m is 1 mm. For another lens angle it
       falls back to 2 × range × tan(angle ÷ 2) ÷ 640. Also shown: the
       view's width and height (from FLIR's field of view for the lens) and
       the pixels covering a round 0.1 m target. The pixel size is labelled
       at the end of each cone. If a pixel is over **10 cm** at the camera's
       range, its cone turns red and a warning along the bottom of the map
       says detection can't be guaranteed where pixels are larger than the
       bats themselves.
     - **Acoustic detectors**: **+ Add detector** for each one, with its
       name, surveyor, model (common models are suggested as you type),
       serial number, a rough detection range (drawn as a dashed circle) and
       other info, then **Place on map** and drag its orange A1, A2… pin into
       place. A survey's detectors are also listed under it in the
       recordings list.

     Everything is saved as you go, with the projects.
     **Save as site plan template** makes the survey's cameras
     (names, positions, facing, range, lenses and surveyors) and acoustic
     detectors the plan for the project:
     every new survey starts with them, so a repeat visit needs no setting
     up. **Print site plan** prints the map with tables of the cameras and
     detectors (or saves it
     as a PDF: choose Save as PDF as the printer). The map needs an internet connection for the imagery (Esri
     World Imagery, or OpenStreetMap from the layers button); place names
     come from OpenStreetMap's Nominatim.
   - **Tree** shows everything as Project › Survey › Camera › recording.
     Click a recording there to open it.
   - The report's *Location* starts as the project name.
   - One camera records one file at a time, so its recordings shouldn't
     overlap in time. If two do, the camera shows an amber warning naming
     them, so you can check each is under the right camera.
2. **Draw the region of interest (ROI).** The ROI toolbar sits just under
   the Viewing Mode buttons. Click the picture of the shape you want:
   - **Polygon**: click round the roost features. A line follows your cursor
     from the last point, with a dashed line back to the start. Backspace
     removes the last point.
   - **Rectangle** or **Circle**: drag on the picture to draw it, drag the
     middle to move it, or drag an edge or corner handle to resize it, as
     many times as you like. When it's right, **click once anywhere on the
     picture** to set it (or press Enter, or click **Done**). **Cancel**
     puts back the outline it had before.

   For a polygon, **right-click** on the picture to finish (or press Enter,
   or click **Finish**). An open polygon is joined back to its first point
   automatically. **Cancel** (Esc) leaves the current ROI as it is. Keep the
   sky out, but leave a thin strip above the roofline. If the camera didn't
   move, tick *Use for every file from this camera*.

   **Several ROIs**: the button with the coloured dot (for example
   **● ROI 1 ▾**) opens the ROI list.
   - **+ Add ROI** adds another, each in its own colour. The selected ROI
     (the radio button) is the one the shape buttons draw.
   - Click a name to **rename** it, for example "Gable end" or "Eaves".
   - The **eye** shows or hides an ROI on the picture and in the Event Log.
   - **×** deletes an ROI and its events.

   With more than one ROI, each is outlined in its colour with its name on
   the picture.
3. **Scan.** Scan from the recordings list: **Scan camera**, **Scan
   survey**, **Scan project** or **Scan unassigned** (the buttons in the
   theme colour). Each recording is scanned with its own ROIs.
   - In the ROI menu (the button with the coloured dot), tick **Scan** for
     each ROI to include. All the ticked ROIs are scanned in one pass, so
     extra ROIs barely add time.
   - **Test ROI Scan** (on each camera) scans one randomly chosen minute of one
     of the camera's recordings, with its ROIs, counts the rises of more
     than 0.2 °C above that minute's background (the test level), and rates the background noise there: a quick scan can check if the ROI is affected by background
     movement without scanning the full recording. Nothing is saved. **View
     this minute** opens that stretch so you can see what's moving; **Test
     another minute** tries a different one.
   - Progress shows over the Event Log plot: the percentage, what's running
     and how many more are waiting, with **Cancel**. While the open
     recording is being scanned, its plot fills in as the scan goes.

   One pass builds the activity plot for the ROI. The scan always uses **Window Average (3×3) + Sliding Subtraction
   (5 frames)**, whichever mode is showing. Recordings scanned with older
   settings are flagged in the Detection panel so you can scan them again.
   A very large spike at the end of a recording is always left out of the
   analysis. This is typically someone walking up to the camera, or the
   camera being moved or switched off. The spike has to run to within 2 s of
   the end and be at least 3 times taller than anything else in the
   recording. It never becomes an event, and it doesn't affect the suggested
   level or set the plot's height. It's shaded grey on the plot and noted in
   the PDF report. The final frame of every recording is never used either.
4. **Set the detection level.** The level box, with **Suggested**, is at
   the top of the Event Log. With several ROIs, each ROI's trace is drawn in
   its colour; click an ROI's name above the plot to hide or show it. Each
   event card says which ROI it was found in. The activity plot has a dashed **blue
   line**. Spikes above it (amber) become numbered events, and anything below
   it (grey) is ignored. Drag the line up or down, type a level, or click
   **Suggested**. Events update straight away. Decisions you've already made
   The **suggested level** starts 0.2 °C above the ROI's background (the
   median of its trace): deliberately low, so faint passes aren't missed.
   Raise the line if it catches too much (insects, flicker).
   are kept, even if you move the line away and back.
   - Scroll on the plot to zoom, drag to pan, and click to jump to that
     moment.
   - **Time window**: drag either handle to show just part of the
     recording, or drag the shaded bar to slide that window along.
   - **Y-axis**: stops one tall spike flattening the others. These options
     only change the view, not which events are found.
     - **Default** sets the height from the suggested detection level:
       the line sits a quarter of the way up, so the background noise and
       small spikes are easy to see. Taller spikes are marked ▲. Click it to
       go back to this view at any time.
     - **Linear** automatically cuts off spikes more than twice
       the height of the next one down, marked ▲, so the rest stay clear.
       To change it, drag the handle on the **bar left of the plot**: down
       cuts off more, the top shows full height. **Back to automatic**
       returns to the Default view.
     - **Log** squeezes tall spikes down so small ones stay visible.
   - Use **Enlarge** for a bigger plot.
   - **Background noise between spikes**: above the plot, each scanned ROI
     gets a rating (**Low**, **Moderate** or **High**) of how busy its
     background is when no bat is passing. It is worked out from the frames
     outside events and below the line: the average level, how much it
     jitters (±), and how often it rises part-way towards the line. Open
     sky or a still wall rates Low. Something in the ROI that moves or
     changes, such as swaying branches, passing cloud, water or a warm
     surface cooling, rates Moderate or High: it pushes the suggested level
     up and can hide faint bats. If the noise comes and goes, a
     **Noisiest** button jumps to the worst 30 s so you can see what's
     causing it, and perhaps redraw the ROI to leave it out.
5. **Review each event.** Click a marker or event card. The app jumps to the
   event and plays within a window 3 s either side. Use the controls under
   the picture to watch it:

   | Button | Does |
   |---|---|
   | ⏮ / ⏭ | Go to the start or end play limit (keys `Home` / `End`) |
   | ◀ | Play backwards |
   | ◀❙ / ❙▶ | Step back or forward one frame (`←`/`→`; hold Shift to jump 1 s) |
   | ▶ | Play / pause (`Space`) |
   | Lock Play Limits to Current Event | Keep playback inside the selected event's window |
   | Speed | ¼× to 4× |
   | ‹ Prev event / Next event › | Step through the events |
   | ‹ Prev camera / Next camera › | The same moment on the other cameras of this survey: the picture stays at the same clock time, and play limits you've set move with it. Cameras with no recording at that time are skipped. The camera you're on is named between the buttons: click its name (or the camera at the top of the Event Log) to choose any camera. Clicking a camera's box in the Recordings list also shows it, even when its files are folded away; the camera showing is outlined. The list offers any camera from any survey or project with recordings listed. It opens at the same moment if that camera was recording then, otherwise at the start. |

   **Play limits**: the two blue markers under the progress bar set where
   playback starts and stops. Drag them to play any stretch you like; the
   shaded part between them is what plays. **Reset play limits** puts them
   back to the whole recording. While *Lock Play Limits to Current Event* is
   ticked and an event is selected, the markers follow that event. Dragging
   a marker unticks it.

   **The same moment on another camera**: an event opens on the camera that
   recorded it. If the recording is in a survey with other cameras, the
   selected event has a **View this time on** list. Pick another camera and
   the program opens that camera's recording covering the same time, puts
   the picture at the event's start and sets the play limits round it. A
   bar above the picture says what you're looking at, with **Back to
   Event N** to return. If that camera has no recording covering the time,
   it says so.

   Then choose a classification and **Confirm** or **Reject** the event.
   **Undo** clears your decision.

   To begin the review again, click **Reset decisions…** at the top of the
   Events list. It clears every Confirm, Reject and classification. You can
   also delete all comments, go back to the suggested detection level, and
   scan the recording again with your current settings. Files you've
   already exported are kept.
6. **Add comments.** Each event card lists its comments underneath. In the
   selected event, type in its comment box and click **Add comment** (or
   press Ctrl + Enter). The comment is pinned to the current moment, or to
   the start of the event if you're outside its window. Click a comment to
   jump to it, or × to delete it.
7. **Export event pack.** One click saves these files to `exports\`
   beside the recording:
   - the tracking still
   - the tracking clip
   - the trails clip (the moving-animal trails on their own)
   - a detection still and a detection clip, both using the blend type, opacity
     and range set in the app. The still is taken at the event's peak for an
     overlay. For a crossfade it's taken a Max Frame Interval's worth of frames
     (5 by default) after activity is first seen, so the trail has built up.
   - a still of the frame where each animal first appears

   **Export camera video** saves every recording from the open recording's
   camera, joined in time order, as one MP4 (just this recording if it isn't
   in a camera). Choose the Default thermal picture or Detection (with the
   blend and opacity showing now), and whether to show the ROI and the date
   and time. It uses the current palette and image clean-up, and goes to the
   exports folder, named after the project, survey and camera. Long
   recordings take a while, roughly as long as the footage or less;
   progress shows over the Event Log.

   **Save events CSV** writes a table of events for the report, with their
   comments. If there are any comments, it also writes `<name>_comments.csv`
   listing every comment with its time.

   **Create report** makes the survey report: a summary, the methodology,
   the activity plot, the ROIs, a table of events, and each event with its
   decision, classification, comments and stills. Choose **PDF** (ready to
   send) or **Word document (.docx)** (to edit before sending).

The **Viewing Mode** bar has four modes (keys `1`–`4`):
- **Default**: the plain thermal picture, with no filters.
- **Tracking**: the whole route is built up in one image.
- **Detection**: the thermal picture with moving animals shown as bright
  trails, in the current palette. Its ▾ menu holds **Trail length** (in
  frames), **Blend** and **Opacity**. Blend sets how the two are mixed:
  - **Overlay**: the trails are laid over the thermal picture, and the rest
    stays thermal. Opacity sets how solid the trails are.
  - **Crossfade**: the two whole pictures are mixed. 0% is thermal only and
    100% is trails only.

  Detection opens as **Crossfade at 80%** unless you save something else
  in Settings.

  The colour bar adjusts the thermal picture underneath.

- **Custom**: your own mix of filters. Pick a saved filter from the
  **Filter** dropdown. **Edit filters…** opens Settings > Custom filters,
  where you can:
  - start from scratch: tick any of Max Frame Interval, Sliding Subtraction
    and Max Continuous, and set their frames (Window Average is used only
    for scanning, as it blurs the picture);
  - tick **Blend Filter With Thermal** to lay the result over the thermal
    picture, at the opacity you choose (untick it to see the filter on
    its own);
  - name and save it.

  Some filters conflict, for example Max Continuous with Sliding
  Subtraction, which can leave the picture almost blank. The editor warns
  you about these. Custom filters change only what you see, never the
  scan.

**Detection settings** (the ▾ joined to the Detection button) has one
setting, **Frames**: how many frames each trail lasts. It sets Max Frame
Interval and Sliding Subtraction together (1–60; the default is 5). Longer persistence gives longer, brighter
trails. It changes the view straight away, and exports use it too. It
doesn't change the scan, which always uses Window Average + Sliding
Subtraction 5. It applies to every recording. To keep a change for next
time, save it in **Settings**.

**Palette & image** (the menu at the right of the Viewing Mode bar) holds
the palette and the image clean-up.

**Palette**: pick White hot, Black hot, Iron, Rainbow, Lava or Arctic.
Exports and the PDF report use it too.

**Image clean-up**: two tick-boxes, each with a Low / Medium / High
strength.
- **Detail enhancement** (on at Medium unless you change it in Settings)
  boosts local contrast, bringing out roof edges,
  vegetation and animals against smooth sky, even when one hot area takes up
  most of the colour range. It applies to all three modes.
  Higher strengths also boost noise.
- **Noise reduction** averages each pixel over recent frames, but only where
  nothing is moving, so the still background gets cleaner while bats stay
  sharp. It applies to Default and Detection. High removes the most grain but
  takes a moment longer to settle after you jump to a new point.

Exports and the PDF report use them too. **Neither ever changes the scan or
which events are found.**

Changes made in the Viewing Mode bar and its menus last until you close the program. Each
recording opens with the defaults from **Settings > Viewing**. Click *Use the
current view settings* there, then **Save settings**, to keep your current
view as the default.

**Visible range**: the colour bar on the right of the picture shows how
values map to colours. Drag the **top handle** to set the hottest value
shown (anything above is the top colour). Drag the **bottom handle** to set
the coldest value shown (anything below is the bottom colour). Narrowing
the range boosts contrast on small temperature differences. You can also
click a handle and use ↑/↓ (Shift for bigger steps). **Auto** sets the
range for each frame automatically. Each mode keeps its own range.
Exported clips and stills use the range you set.

Switching mode only changes what you see.

Each view sets its own colour scale. Other shortcuts: `n`/`p` move to the next or previous event.

## Settings

Click the **Settings** (cog) button in the top bar. Change what you need, then click **Save
settings** to keep it for next time. **Cancel** leaves everything as it was.
Settings are saved in `settings.json` in the program folder.

| Section | What you can set |
|---|---|
| Appearance | Colour scheme (Forest, the Thermal Vision Ecology greens, or Ocean, Teal, Heather, Slate) and Dark / Light mode. Changes preview straight away. |
| Viewing | The palette, detail enhancement, noise reduction, blend type and opacity, playback speed and frame persistence each recording opens with. *Use the current view settings* copies what's on screen now. |
| Custom filters | An advanced option: read the manual first. Create, name, change and delete the filters for the Custom viewing mode, with warnings when filters conflict. |
| Detection | Suggested-level sensitivity for raw-count recordings with no temperature scale (Low = fewer events, High = more; recordings in °C or °F always start 0.2 °C above the background), merge gap, shortest event kept, and the review window either side of an event. Changing these re-finds events straight away. Your decisions and comments are kept. *Reset detection to recommended* undoes them. |
| Exports | Default export folder, which items are ticked, overlays, timestamp text size, file-name order, video quality and slow-motion export (½ or ¼ speed). |
| Time & units | Pixel values as temperature or raw counts (the colour bar, plot, level and exports follow it; scanned recordings are converted), °C or °F, UK time or UTC, and a camera clock correction in seconds if a camera's clock was wrong. It applies to everything shown, exported and reported. Switching °C/°F converts scans already done; no rescan needed. |
| Classifications | Your own list for the Classification menu, for example species groups. |
| Review | Jump to the next unreviewed event after Confirm / Reject. Start playing when an event is selected. |
| Report details | Company, contact, analyst and camera for reports. |
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

## If a save file is damaged

Decisions, ROIs and scans are saved beside each recording
(`<name>.ats.analysis.json` and `.activity.npz`); projects, cameras and site
plans in `cameras.json`; settings in `settings.json`. If one of these can't be
read (for example it was half-written, or half-synced by Dropbox), the
program doesn't overwrite it: it keeps it as `<file>.damaged-<date-time>`,
notes it in `error_log.txt`, tells you, and starts that information again.
The kept copy can usually be repaired.

## Automated tests

`tests/` holds automated checks of the whole program (organising
recordings, scanning, reviewing, joining, temperatures, site plans, project
files, saving, reports). Run `tests/run_all.sh`, or `python -m pytest tests`
for the server checks alone; see `tests/README.md`. The beta build runs them
before compiling.

## Check a file decodes correctly

Drag an `.ats` file onto **Check a file.bat**. It prints the camera, size,
frame count and temperatures, and saves `<name>_check.png` showing the
start, middle and end frames. If those look like your footage, the program
reads that camera's files correctly.

## Known limits (prototype)

- The `.ats` reader was worked out from real files and doesn't use FLIR's
  SDK. It's tested on an RS8481 (1280×1024) recording. **Check A70 and A700
  files with "Check a file" before relying on them.**
- Frame times come from the time stamp the camera puts on every frame, so
  they're exact even if frames were dropped or the frame rate changed. The
  first time a recording is opened, the program reads every frame's stamp
  in the background (a few seconds for a long recording) and keeps them in
  `<name>.ats.times.npz` beside it, so later openings are instant. Every
  clock time and duration (on screen, in exports, CSVs and reports) uses
  them. A file without them gets its
  frame rate from when it finished recording (its "last modified" time).

- Times are shown in UK time: BST in summer and GMT in winter, changing on
  the official dates. Dates are shown as dd/mm/yyyy. This applies everywhere: the app, the picture overlay,
  exports and CSVs. The camera stores its start time in UTC, and the app
  converts it.
- Temperatures: A70/A700 "Temperature (Factory)" recordings come in two
  forms, and the program tells them apart from the range Research Studio
  saved in the file:
  - temperature stored directly, 0.01 K per value (read exactly);
  - raw sensor values (for example the St Fagans A700 and SWT A70
    recordings). These use one fixed calibration per camera model, so every
    recording from a camera is on the same scale: 0.01649 °C per value,
    taken from the SWT A70 recording 0010.ats, whose Research Studio
    temperatures are accurate. For the A70 that file also sets the zero
    point. The A700 stores raw values on a different base, so it uses the
    same scale with its zero point from St Fagans front 1 (Research Studio's
    reading, no correction). Temperature differences, which detection uses,
    are right; absolute values are approximate, so the level shows
    "°C, approx.".

  Files with no temperature information at all (RS8481 recordings saved as
  Counts) still show counts. Files saved in counts show as counts, which still works for
  detection.
- Bat tracking finds compact warm objects that move. Very slow or very
  distant bats, rain, and swaying vegetation can still need your eye. That's
  why every event waits for your decision.
