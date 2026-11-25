#!/usr/bin/env python3
"""Download the Zoom files the optional ``zoom_files`` tests read, into the git-ignored ``tests/.zoom-fixtures/``.

Zoom's effect files (``.ZD2``) and Guitar Lab's effect list are Zoom's property, so the repository does not carry
them. This script fetches a small set from Zoom's public Guitar Lab channel, for your own use, with the app's own
updater (``jmc_guitar_zoom.library.updater``): the same URL confinement (https, the channel host, no ``..``), the same
size limits and the same verification (the ``.ZD2`` inside each zip must parse and carry the id and version the
list announced). Nothing is written outside the destination folder and nothing already there is overwritten.

    uv run python scripts/fetch_test_fixtures.py [--dest DIR]

Run it once to get the whole suite; the tests themselves never use the network. Without the files, the tests
marked ``zoom_files`` are skipped and everything else runs on synthetic fixtures (``tests/support``).

What it fetches: ``AllZDL7_2.lst`` and ``ModelVersion7_2.lst`` (the channel's lists) and the zips of the effects
below, found by effect id in the list, so a renamed zip does not break it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jmc_guitar_zoom.library import updater  # noqa: E402

DEFAULT_DEST = ROOT / "tests" / ".zoom-fixtures" / "effects"

# the effects the synthetic fixtures imitate (tests/support/zd2_factory.py), by id
WANTED = {
    0x01000010: "Comp", 0x01000020: "RackComp", 0x01000080: "OptComp", 0x01800030: "160 Comp",
    0x02000054: "Gt GEQ 7", 0x0400002C: "FD DLXR", 0x0500002A: "FD-DX1x12", 0x09000030: "Hall",
    0x14400190: "12Strings",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help=f"folder to fill (default: {DEFAULT_DEST})")
    dest = parser.parse_args(argv).dest

    client = updater.LibraryUpdater(dest)
    print(f"Reading Zoom's effect list from {updater.EFFECTS_LIST_URL}")
    try:
        result = client.check(all_models=True)  # saves both lists into dest
    except updater.UpdateError as exc:
        print(f"could not read the channel: {exc}", file=sys.stderr)
        return 1

    # one channel entry per wanted id (the check keeps the newest version of an id)
    todo = [entry for entry in result.pending if entry.effect_id in WANTED]
    held = {entry.effect_id for entry in result.current}
    missing = sorted(set(WANTED) - {e.effect_id for e in todo} - held)
    for effect_id in missing:
        print(f"  not on the channel any more: {WANTED[effect_id]} (0x{effect_id:08X}); its tests will adapt or skip")
    print(f"Fetching {len(todo)} effect zip(s); {len(held & set(WANTED))} already present")
    failures = 0
    report = client.download(todo, progress=lambda i, n, e: print(f"  [{i + 1}/{n}] {e.file_name} {e.version}"))
    for item in report.results:
        if item.ok:
            print(f"  saved {item.path.name}")
        elif item.reason in ("version_mismatch", "id_mismatch"):
            # the zip holds another version than the list announces; the updater refuses it, and so do we
            print(f"  skipped {item.entry.file_name}: {item.reason} (the channel's list and zip disagree)")
        else:
            failures += 1
            print(f"  FAILED {item.entry.file_name}: {item.reason}", file=sys.stderr)
    print(f"Done: {dest}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
