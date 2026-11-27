# Third-party notices

JMC Guitar Zoom is MIT licensed (see `LICENSE`). It uses the components below. None of them is modified or
redistributed in this repository, except the two font families, which are bundled with their licences. The release
packages (the AppImage and the Windows installer) do redistribute them: see "Release packages" below.

## Runtime dependencies (installed with pip / uv)

| Component | Licence | Notes |
|---|---|---|
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/) and Qt 6 | LGPL v3 (also GPL v2/3 and commercial) | Used under the LGPLv3. It is installed from PyPI and dynamically linked; the application does not modify it, and you can replace it by installing another PySide6 version. |
| [FFmpeg](https://ffmpeg.org), inside PySide6's Qt Multimedia | LGPL v2.1 or later | Qt Multimedia's media backend, which the audio tuner loads to read the sound card. It ships as shared libraries in the PySide6 wheel, unmodified. |
| [mido](https://github.com/mido/mido) | MIT | MIDI messages and ports. |
| [python-rtmidi](https://github.com/SpotlightKid/python-rtmidi) | MIT | MIDI backend (bundles RtMidi, MIT). |
| [construct](https://github.com/construct/construct) | MIT | Binary container parsing. |
| [crcmod](https://github.com/gsutter/crcmod) | MIT | CRC calculation used by the upstream scripts. |
| [NumPy](https://numpy.org) | BSD-3-Clause | Pitch analysis of the audio tuner. Its wheels bundle OpenBLAS and LAPACK (BSD-3-Clause) and, on Linux, the GNU Fortran runtime (GPLv3 with the GCC Runtime Library Exception); the texts are in NumPy's own `LICENSE.txt`. |

Development only: [pytest](https://pytest.org) (MIT) and [pytest-qt](https://github.com/pytest-dev/pytest-qt) (MIT).

## Bundled fonts (`jmc_guitar_zoom/ui/design/fonts/`)

- **Exo 2** (`Exo2-Variable.ttf`): Copyright 2013 The Exo 2 Project Authors
  (https://github.com/googlefonts/Exo-2.0). **SIL Open Font License 1.1**; the licence text is in `OFL.txt`.
- **Roboto** (`Roboto-Regular.ttf`, `Roboto-Medium.ttf`, `Roboto-Bold.ttf`): Copyright 2011 Google Inc.
  **Apache License 2.0**; the licence text is in `LICENSE-Roboto.txt`.

## Release packages

The AppImage and the Windows installer are built with [PyInstaller](https://pyinstaller.org) and carry, unmodified:
the CPython interpreter (PSF License), PySide6 and Qt 6 (LGPLv3) with Qt Multimedia's FFmpeg libraries (LGPL v2.1
or later, used here under the LGPLv3 text it allows), mido, python-rtmidi with RtMidi, construct and crcmod (MIT),
NumPy (BSD-3-Clause, with the bundled libraries its licence file lists), the two font families above, and PyInstaller's bootloader (GPLv2 with an exception that allows
distributing it with any program). Their licence texts are in the `licenses/` folder inside each package, next to
this project's `LICENSE`, `NOTICE.md` and this file.

Qt, PySide6 and FFmpeg stay dynamically linked: their shared libraries sit as separate files in the package folder (the
AppImage can be unpacked with `--appimage-extract`) and can be replaced with compatible builds. Their source code is
available from the Qt Project at <https://code.qt.io> and <https://download.qt.io>, and FFmpeg's at
<https://ffmpeg.org/download.html>. The AppImage itself is assembled
with [appimagetool](https://github.com/AppImage/appimagetool) (MIT), whose runtime starts it. The Windows installer
is made with [Inno Setup](https://jrsoftware.org/isinfo.php), whose licence allows distributing installers built
with it.

## Upstream project

The protocol code, the container formats and the scripts at the repository root (`zoomzt2.py`, `decode_*.py`,
`convert_*.py`, ...) come from [mungewell/zoom-zt2](https://github.com/mungewell/zoom-zt2), **MIT**, Copyright (c)
2019 mungewell. See `NOTICE.md`.

## Trademarks and Zoom's files

"Zoom", "A1 FOUR", "G1 FOUR", "G5n", "Guitar Lab" and other product names are trademarks of Zoom Corporation or of
their respective owners. They are used here only to say which hardware the software works with. This project is not
affiliated with, endorsed by or sponsored by Zoom Corporation.

**No Zoom file is distributed in this repository**: no effect binaries (`.ZD2`), no patches dumped from a pedal, no
`FLST_SEQ.ZT2`, no Guitar Lab lists or artwork, and no firmware. The tests use synthetic files. The library updater
of the application and `scripts/fetch_test_fixtures.py` download effect files and lists from Zoom's public server
(`www.zoom.co.jp/archive/GUITAR_LAB/`), on your machine and for your own use; whatever you download remains Zoom's
and is subject to Zoom's terms.
