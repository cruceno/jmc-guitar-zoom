# PyInstaller spec: onedir, windowed. Build from the repository root:
#   uv run pyinstaller --noconfirm --workpath build --distpath dist packaging/jmc-guitar-zoom.spec
# Output: dist/jmc-guitar-zoom/ (the AppImage and the Windows installer both package this folder).
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is injected by PyInstaller
NAME = "jmc-guitar-zoom"
# The exe icon applies on Windows only; on Linux the AppImage carries the PNG.
ICON = str(ROOT / "packaging" / "icons" / "app-icon.ico") if sys.platform == "win32" else None

# Package data read through Path(__file__): (source, folder inside the bundle).
datas = [
    (str(ROOT / "jmc_guitar_zoom/ui/design"), "jmc_guitar_zoom/ui/design"),  # fonts, icons, style.qss, tokens.json, app-icon.svg
    (str(ROOT / "jmc_guitar_zoom/effects/descriptions_es.json"), "jmc_guitar_zoom/effects"),
    (str(ROOT / "jmc_guitar_zoom/patches/template.zptc"), "jmc_guitar_zoom/patches"),
    (str(ROOT / "jmc_guitar_zoom/patches/empty.zptc"), "jmc_guitar_zoom/patches"),
    # Project licence and notices, next to the executable.
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE.md"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    # Licence texts of what the binaries carry, in licenses/.
    (str(ROOT / "packaging/licenses/LGPL-3.0.txt"), "licenses"),  # Qt / PySide6 (LGPLv3)
    (str(ROOT / "jmc_guitar_zoom/ui/design/fonts/OFL.txt"), "licenses"),  # Exo 2 (OFL 1.1)
    (str(ROOT / "jmc_guitar_zoom/ui/design/fonts/LICENSE-Roboto.txt"), "licenses"),  # Roboto (Apache 2.0)
]


def _dist_file(dist, wanted):
    """A licence file shipped inside an installed wheel (never hand-copied).

    ``wanted`` is a file name, or a path suffix (with a "/") when the wheel holds several files of that name.
    """
    for f in metadata.files(dist) or []:
        if (f.as_posix().endswith(wanted) if "/" in wanted else f.name == wanted):
            return str(f.locate())
    raise SystemExit(f"{wanted} not found in the installed {dist} distribution")


def _python_licence():
    """CPython's own licence (PSF), from the interpreter the bundle embeds; its folder differs per platform."""
    base = Path(sys.base_prefix)
    candidates = [base / "LICENSE.txt", base / "Lib" / "LICENSE.txt",
                  base / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "LICENSE.txt"]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise SystemExit(f"CPython's LICENSE.txt not found under {base}")


datas += [
    (_python_licence(), "licenses/python"),  # the embedded CPython interpreter (PSF License)
    (_dist_file("python-rtmidi", "LICENSE.md"), "licenses/python-rtmidi"),  # python-rtmidi / RtMidi (MIT)
    (_dist_file("mido", "LICENSE"), "licenses/mido"),  # mido (MIT)
    (_dist_file("construct", "LICENSE"), "licenses/construct"),  # construct (MIT)
    (_dist_file("crcmod", "LICENSE"), "licenses/crcmod"),  # crcmod (MIT)
    # numpy (BSD-3-Clause); the same file carries the licences of what its wheel bundles (OpenBLAS, LAPACK, ...)
    (_dist_file("numpy", ".dist-info/licenses/LICENSE.txt"), "licenses/numpy"),
    (_dist_file("pyinstaller", "COPYING.txt"), "licenses/pyinstaller"),  # PyInstaller bootloader (GPLv2 + exception)
]

# mido loads its backend by name at run time, so PyInstaller cannot see it. The audio tuner imports
# QtMultimedia only when it lists or opens an input (jmc_guitar_zoom/audio/capture.py).
HIDDEN_IMPORTS = ["mido.backends.rtmidi", "rtmidi", "PySide6.QtMultimedia"]

# Qt modules the app never imports (it uses QtCore, QtGui, QtWidgets, QtSvg, QtNetwork and QtMultimedia). QtSvg,
# QtNetwork, QtMultimedia (with its FFmpeg plugin) and the image-format plugins (svg, ico) stay.
EXCLUDES = [f"PySide6.{m}" for m in (
    "QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel", "QtWebSockets", "QtWebView",
    "QtQml", "QtQuick", "QtQuickWidgets", "QtQuickControls2", "QtQuick3D", "QtQuickTest",
    "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic", "Qt3DAnimation", "Qt3DExtras",
    "QtMultimediaWidgets", "QtSpatialAudio", "QtCharts", "QtGraphs", "QtDataVisualization",
    "QtPdf", "QtPdfWidgets", "QtDesigner", "QtHelp", "QtSql", "QtTest", "QtBluetooth", "QtNfc", "QtSensors",
    "QtSerialPort", "QtSerialBus", "QtPositioning", "QtLocation", "QtRemoteObjects", "QtScxml",
    "QtStateMachine", "QtTextToSpeech", "QtOpenGL", "QtOpenGLWidgets", "QtPrintSupport", "QtVirtualKeyboard",
    "QtHttpServer", "QtNetworkAuth", "QtConcurrent", "QtDBus", "QtXml", "QtUiTools",
)] + ["tkinter", "pytest", "unittest"]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],  # the package imports the root-level modules zoomzt2 and decode_preset
    datas=datas,
    hiddenimports=HIDDEN_IMPORTS,
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,  # windowed: no console on Windows
    icon=ICON,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)  # noqa: F821
