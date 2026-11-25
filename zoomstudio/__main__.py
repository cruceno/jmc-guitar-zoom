"""Entry point: ``uv run python -m zoomstudio``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PEDAL_LABEL = "pedal"
GUITARLAB_LABEL = "Guitar Lab"
A1_LIST = Path("cache") / "AllZDL7_2.lst"


def workspace_root() -> Path:
    """The folder that holds the zoom-studio repo and its sibling data folders."""
    return Path(__file__).resolve().parents[2]


def autosave_dir(root: Path | None = None) -> Path:
    """Where SAVE stores the pedal's previous content of a slot before overwriting it."""
    return (root or workspace_root()) / "patches" / "autosave"


def offerable_effect_ids(catalog: dict, a1_ids: set[int] | None, installed_label: str = PEDAL_LABEL) -> set[int] | None:
    """Effects the editor may offer: the A1 FOUR list plus every effect installed on the pedal.

    ``AllZDL7_2.lst`` omits OptComp and FD-DX1x12 although the pedal ships them.
    """
    if a1_ids is None:
        return None
    return set(a1_ids) | {i for i, e in catalog.items() if installed_label in e.sources}


def default_catalogs(root: Path | None = None) -> list[tuple[str, Path]]:
    root = root or workspace_root()
    found: list[tuple[str, Path]] = []
    pedal = sorted((root / "patches").glob("pedal-files-*"))
    if pedal:
        found.append((PEDAL_LABEL, pedal[-1]))  # names embed a timestamp: last = newest
    gl = root / "guitarlab" / "GL"
    if gl.is_dir():
        found.append((GUITARLAB_LABEL, gl))
    return found


def parse_catalog_arg(value: str) -> tuple[str, Path]:
    """``DIR`` or ``LABEL=DIR``; a bare DIR is labelled with its folder name."""
    label, sep, folder = value.partition("=")
    if sep and label and "/" not in label:
        return label, Path(folder)
    return Path(value).name, Path(value)


def find_a1_list(catalogs: list[tuple[str, Path]]) -> Path | None:
    for _, folder in catalogs:
        for base in (folder, folder.parent):
            if (base / A1_LIST).is_file():
                return base / A1_LIST
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zoomstudio", description="Zoom Studio - editor for the Zoom A1 FOUR")
    p.add_argument("--catalog", action="append", metavar="[LABEL=]DIR", default=[],
                   help="folder with .zd2 effect files (repeatable); a catalog labelled 'pedal' marks "
                        "effects as installed on the pedal. Default: newest patches/pedal-files-* and "
                        "guitarlab/GL next to the repository")
    p.add_argument("--offline", metavar="DIR", help="open a backup folder of NNN.zptc files instead of connecting")
    p.add_argument("--no-connect", action="store_true", help="do not connect to the pedal at start-up")
    p.add_argument("--screenshot", metavar="PATH", help=argparse.SUPPRESS)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from PySide6.QtWidgets import QApplication

    from zoomstudio.device import MidoTransport
    from zoomstudio.effects.catalog import a1four_effect_ids, load_catalog
    from zoomstudio.ui.main_window import MainWindow
    from zoomstudio.ui.fonts import install_spanish, register_fonts
    from zoomstudio.ui.theme import apply_dark_theme

    catalogs = [parse_catalog_arg(c) for c in args.catalog] or default_catalogs()
    catalogs = [(label, folder) for label, folder in catalogs if folder.is_dir()]
    catalog = load_catalog(*catalogs) if catalogs else {}
    a1_list = find_a1_list(catalogs)
    a1_ids = offerable_effect_ids(catalog, a1four_effect_ids(a1_list) if a1_list else None)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Zoom Studio")
    install_spanish(app)
    register_fonts()
    apply_dark_theme(app)

    window = MainWindow(catalog, a1_ids=a1_ids, transport_factory=MidoTransport.open,
                        installed_label=PEDAL_LABEL, backup_dir=autosave_dir(),
                        library_dir=workspace_root() / "patches")
    if not catalogs:
        window.statusBar().showMessage("No effect catalog found: pass --catalog DIR")
    if args.offline:
        window.load_offline(Path(args.offline))
    window.show()

    if args.screenshot:
        window.grab().save(args.screenshot)
        window.close()
        return 0
    if not args.offline and not args.no_connect:
        window.start_connect()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
