# PyInstaller recipe for the Windows program. Used by "Build Windows app.bat".
# Builds a folder "dist\Track and Detect" containing "Track and Detect.exe".
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas = [("static", "static"), ("emergence/tve-logo-print.png", "emergence")]
binaries, hiddenimports = [], []

# ffmpeg for MP4 export ships inside imageio-ffmpeg
d, b, h = collect_all("imageio_ffmpeg")
datas += d; binaries += b; hiddenimports += h

# PDF reports: reportlab's fonts and the modules it loads on demand
datas += collect_data_files("reportlab")
hiddenimports += collect_submodules("reportlab")

# the app imports these inside functions
hiddenimports += ["emergence.report", "emergence.settings", "emergence.render", "emergence.analysis",
                  "emergence.session", "emergence.ats"]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "PyQt5", "PySide6", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Track and Detect",
    icon="static/app.ico",
    console=False,          # no black window: the program runs in the browser
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Track and Detect", upx=False)
