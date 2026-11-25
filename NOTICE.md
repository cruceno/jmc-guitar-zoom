# JMC Guitar Zoom: notice

JMC Guitar Zoom is an **independent derivative** of [mungewell/zoom-zt2](https://github.com/mungewell/zoom-zt2)
(MIT License, Copyright (c) 2019 mungewell). The original scripts at the repository root (`zoomzt2.py`,
`decode_*.py`, `convert_*.py`, ...) are kept unchanged; the Qt application lives in `jmc_guitar_zoom/`. The
reverse engineering of the pedal's SysEx protocol and file formats in the upstream project is the base of this work
and is credited in `docs/protocol-a1four.md`. The upstream README is kept as
`docs/zoom-zt2-upstream-readme.md`.

## Not affiliated

This project is not affiliated with, endorsed by or supported by Zoom Corporation or by the upstream project and
its author. "Zoom", "A1 FOUR" and "Guitar Lab" are trademarks of their owners.

## AI-assisted development and upstream

This application was developed with AI assistance. The upstream author does not accept AI-generated contributions
(see `ai.md`), so **none of the changes made here are offered or submitted upstream**. The repository is published
as a separate project that keeps the MIT licence and the upstream credit, nothing more.

## Third-party components and fonts

See `THIRD_PARTY_NOTICES.md` for the dependencies (PySide6/Qt, mido, python-rtmidi, construct, crcmod) and the
bundled fonts (Exo 2, SIL OFL 1.1; Roboto, Apache 2.0; their licence files are in
`jmc_guitar_zoom/ui/design/fonts/`).

## Zoom's files

No file that belongs to Zoom is distributed here. The tests use synthetic fixtures; the library updater and
`scripts/fetch_test_fixtures.py` download from Zoom's public server, on the user's machine.
