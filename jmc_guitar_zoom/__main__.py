"""Entry point: ``uv run python -m jmc_guitar_zoom``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jmc_guitar_zoom import __version__, paths

PEDAL_LABEL = "pedal"
GUITARLAB_LABEL = "Guitar Lab"
LIBRARY_LABEL = "Biblioteca"  # the app's own effects, downloaded from Zoom's channel
LIST_NAME = "AllZDL7_2.lst"
A1_LIST = Path("cache") / LIST_NAME


def workspace_root() -> Path:
    """The folder that holds the jmc-guitar-zoom repo and its sibling data folders."""
    return paths.source_root()


def library_dir(root: Path | None = None) -> Path:
    """The app's own effect library: the effects and lists the updater downloads (never Guitar Lab's folder)."""
    return (root or paths.data_root()) / "library" / "effects"


def autosave_dir(root: Path | None = None) -> Path:
    """Where SAVE stores the pedal's previous content of a slot before overwriting it."""
    return (root or paths.data_root()) / "patches" / "autosave"


def offerable_effect_ids(catalog: dict, a1_ids: set[int] | None, installed_label: str = PEDAL_LABEL) -> set[int] | None:
    """Effects the editor may offer: the A1 FOUR list plus every effect installed on the pedal.

    ``AllZDL7_2.lst`` omits OptComp and FD-DX1x12 although the pedal ships them.
    """
    if a1_ids is None:
        return None
    return set(a1_ids) | {i for i, e in catalog.items() if installed_label in e.sources}


def default_catalogs(root: Path | None = None) -> list[tuple[str, Path]]:
    explicit_root = root is not None
    root = root or paths.data_root()
    found: list[tuple[str, Path]] = []
    pedal = sorted((root / "patches").glob("pedal-files-*"))
    if pedal:
        found.append((PEDAL_LABEL, pedal[-1]))  # names embed a timestamp: last = newest
    library = library_dir(root)
    if library.is_dir() and any(p.suffix.lower() == ".zd2" for p in library.iterdir()):
        found.append((LIBRARY_LABEL, library))  # before Guitar Lab: the newest version wins either way
    # An explicit root (tests, tools) looks only at its own guitarlab/GL; the default also searches Wine/Bottles.
    gl = root / "guitarlab" / "GL" if explicit_root else paths.guitarlab_dir()
    if gl is not None and gl.is_dir():
        found.append((GUITARLAB_LABEL, gl))
    return found


def catalog_sources(explicit: list[tuple[str, Path]] | None = None, root: Path | None = None) -> list[tuple[str, Path]]:
    """The catalog folders in use now: the ``--catalog`` ones or the defaults, with the app library first when the
    command line named folders (the defaults already include it). Read again after a download.

    ``root`` goes to ``default_catalogs`` only when the caller gave one: without it the defaults also search the
    machine for Guitar Lab (``%APPDATA%\\GL``, Wine, Bottles), which is how the packaged app finds it."""
    found = list(explicit) if explicit else default_catalogs(root)
    library = library_dir(root or paths.data_root())
    if explicit and library.is_dir() and any(p.suffix.lower() == ".zd2" for p in library.iterdir()):
        found.insert(0, (LIBRARY_LABEL, library))
    return [(label, folder) for label, folder in found if folder.is_dir()]


def parse_catalog_arg(value: str) -> tuple[str, Path]:
    """``DIR`` or ``LABEL=DIR``; a bare DIR is labelled with its folder name."""
    label, sep, folder = value.partition("=")
    if sep and label and "/" not in label:
        return label, Path(folder)
    return Path(value).name, Path(value)


def find_a1_list(catalogs: list[tuple[str, Path]], library: Path | None = None) -> Path | None:
    """The model list: the library's own copy when the updater saved one, else Guitar Lab's cache."""
    if library is not None and (library / LIST_NAME).is_file():
        return library / LIST_NAME
    for _, folder in catalogs:
        for base in (folder, folder.parent):
            if (base / A1_LIST).is_file():
                return base / A1_LIST
    return None


def load_registry(catalogs: list[tuple[str, Path]], library: Path | None = None) -> dict:
    """The model registry from the first list that loads: the library's copy, then Guitar Lab's cache.

    A damaged list (a bad download, a hand-edited file) must never stop the app from starting."""
    from jmc_guitar_zoom.effects.models import load_models

    for path in dict.fromkeys(p for p in (find_a1_list(catalogs, library), find_a1_list(catalogs)) if p):
        try:
            found = load_models(path)
        except (OSError, ValueError):
            continue
        if found:
            return found
    return {}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jmc-guitar-zoom", description="JMC Guitar Zoom - unofficial editor for the Zoom A1 FOUR (not affiliated with Zoom Corporation)")
    p.add_argument("--catalog", action="append", metavar="[LABEL=]DIR", default=[],
                   help="folder with .zd2 effect files (repeatable); a catalog labelled 'pedal' marks "
                        "effects as installed on the pedal. Default: newest patches/pedal-files-* and "
                        "guitarlab/GL next to the repository")
    p.add_argument("--offline", metavar="DIR", help="open a backup folder of NNN.zptc files instead of connecting")
    p.add_argument("--no-connect", action="store_true", help="do not connect to the pedal at start-up")
    # Hidden: ``--self-check [PATH]``. A windowed Windows exe has no stdout, so PATH also receives the report.
    p.add_argument("--self-check", nargs="?", const="", default=None, metavar="PATH", help=argparse.SUPPRESS)
    p.add_argument("--screenshot", metavar="PATH", help=argparse.SUPPRESS)
    return p


def self_check(report_path: str | None = None) -> int:
    """Prove Qt, the bundled fonts and the MIDI backend load; opens no window and no port.

    The report goes to stdout (stderr on failure) and, when ``report_path`` is given, to that file as well."""
    lines: list[str] = []
    code = 0
    try:
        from PySide6.QtWidgets import QApplication

        paths.set_app_names()
        app = QApplication.instance() or QApplication(sys.argv[:1])
        from jmc_guitar_zoom.ui.fonts import register_fonts

        fonts = register_fonts()
        import mido
        import mido.backends.rtmidi  # noqa: F401 - the backend the app uses; mido would load it lazily
        import rtmidi

        apis = [rtmidi.get_api_name(api) for api in rtmidi.get_compiled_api()]
        if not apis:
            raise RuntimeError("python-rtmidi has no compiled MIDI API")
        try:
            ports = mido.get_output_names()
            outputs = ", ".join(ports) if ports else "none"
        except Exception as exc:  # noqa: BLE001 - no MIDI service on this machine (no ALSA sequencer): not a bundle fault
            outputs = f"unavailable ({type(exc).__name__}: {exc})"
        gl = paths.guitarlab_dir()
        lines = [
            f"jmc-guitar-zoom {__version__}",
            f"data folder: {paths.data_root()}",
            f"fonts registered: {len(fonts)}",
            f"MIDI backend: rtmidi ({', '.join(apis)})",
            f"MIDI outputs: {outputs}",
            f"Guitar Lab: {gl if gl else 'none'}",
        ]
        del app
    except Exception as exc:  # noqa: BLE001 - any load failure must be reported as a failed check
        lines = [f"self-check failed: {type(exc).__name__}: {exc}"]
        code = 1
    text = "".join(f"{line}\n" for line in lines)
    if report_path:
        try:
            Path(report_path).write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"self-check: cannot write {report_path}: {exc}", file=sys.stderr)
            code = 1
    stream = sys.stderr if code else sys.stdout
    if stream is not None:  # a windowed (no console) exe has no stdout/stderr
        stream.write(text)
    return code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_check is not None:
        return self_check(args.self_check or None)

    from PySide6.QtWidgets import QApplication

    from jmc_guitar_zoom.device import MidoTransport
    from jmc_guitar_zoom.effects.catalog import load_catalog
    from jmc_guitar_zoom.ui.main_window import MainWindow
    from jmc_guitar_zoom.ui.fonts import install_spanish, register_fonts
    from jmc_guitar_zoom.ui.theme import apply_dark_theme

    from jmc_guitar_zoom.library.updater import LibraryUpdater

    explicit = [parse_catalog_arg(c) for c in args.catalog]
    library = library_dir()
    catalogs = catalog_sources(explicit)
    catalog = load_catalog(*catalogs) if catalogs else {}
    registry = load_registry(catalogs, library)
    pedal_ids = {i for i, e in catalog.items() if PEDAL_LABEL in e.sources}  # the pedal ships some the list omits

    def reload_sources():
        """Catalog and model list after the updater saved new files (runs on the updater's thread: no widgets)."""
        sources = catalog_sources(explicit)
        return (load_catalog(*sources) if sources else {}), load_registry(sources, library)

    updater = LibraryUpdater(library, extra_dirs=[f for label, f in catalogs if label != LIBRARY_LABEL])

    paths.set_app_names()
    app = QApplication(sys.argv[:1])
    from jmc_guitar_zoom.ui import gc_guard

    gc_guard.install(app)  # cyclic GC only on this thread: a worker's collection crashed Shiboken (see gc_guard)
    app.setApplicationName("JMC Guitar Zoom")
    app.setOrganizationName("JMC Guitar Zoom")
    from PySide6.QtGui import QIcon

    from jmc_guitar_zoom.ui.tokens import DESIGN_DIR

    app.setWindowIcon(QIcon(str(DESIGN_DIR / "app-icon.svg")))
    from PySide6.QtCore import QStandardPaths

    from jmc_guitar_zoom.ui.config_migration import migrate_legacy_config

    migrate_legacy_config(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)))
    install_spanish(app)
    register_fonts()
    apply_dark_theme(app)

    window = MainWindow(catalog, models=registry, extra_ids=pedal_ids, transport_factory=MidoTransport.open,
                        installed_label=PEDAL_LABEL, backup_dir=autosave_dir(),
                        library_dir=paths.data_root() / "patches", updater=updater, reload_sources=reload_sources)
    if not catalogs:
        window.statusBar().showMessage("No se encontró un catálogo de efectos: indique --catalog DIR")
    if args.offline:
        window.load_offline(Path(args.offline))
    window.show()

    if args.screenshot:
        window.grab().save(args.screenshot)
        window.close()
        return 0
    if not args.offline and not args.no_connect:
        window.start_connect()
    window.start_update_check()  # at most once a day, only when online, quiet when it fails
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
