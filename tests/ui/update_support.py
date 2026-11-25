"""A window wired to a fake effect channel: no network, a private library folder, an in-memory daily throttle."""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "library"))

from updater_support import A1, COMP, G5N, HALL, FakeFetcher, effect, make_zip, standard_routes  # noqa: E402

from zoomstudio.effects.catalog import load_catalog  # noqa: E402
from zoomstudio.effects.models import A1_FOUR, PedalModel, load_models  # noqa: E402
from zoomstudio.library import updater as lib  # noqa: E402
from zoomstudio.library.updater import LibraryUpdater  # noqa: E402
from zoomstudio.ui.main_window import MainWindow  # noqa: E402
from zoomstudio.ui.settings import UpdateStore  # noqa: E402

FIXTURES = HERE / "fixtures"
EFFECTS = HERE.parent / "effects" / "fixtures"
RACKCOMP = ("0x01000020", "RACKCOMP.zip", "1.40", EFFECTS / "RACKCOMP.ZD2")  # not in the window's catalog: new
RACKCOMP_ID = 0x1000020
HALL_ID = 0x9000030
NOW = 1_000_000.0


def hall_newer() -> bytes:
    """The fixture Hall (1.50) with its version bumped to 1.60: a real, parseable newer file."""
    return HALL[3].read_bytes().replace(b"1.50", b"1.60", 1)


def routes(models=None, versions=None, zips=None) -> dict:
    """A1 FOUR: Hall 1.60 (updated), RackComp 1.40 (new), Comp 1.40 (up to date); firmware 1.02."""
    hall = ("0x09000030", "HALL.zip", "1.60", None)
    models = models if models is not None else {A1: [effect(COMP), effect(hall), effect(RACKCOMP)]}
    zipped = {lib.ZIP_BASE_URL + "HALL.zip": make_zip({"HALL.ZD2": hall_newer()}),
              lib.ZIP_BASE_URL + "RACKCOMP.zip": make_zip({"RACKCOMP.ZD2": RACKCOMP[3].read_bytes()})}
    zipped.update(zips or {})
    base = standard_routes(models, versions if versions is not None else {A1: "1.02", G5N: "3.00"}, zipped)
    return base


def registry(catalog) -> dict:
    return {A1_FOUR: PedalModel(A1_FOUR, "A1 FOUR", frozenset(catalog))}


def options(tmp_path, catalog, route_table=None, online=True, clock=NOW, store=None, fetcher=None):
    """The MainWindow keyword arguments of a window with an updater; ``catalog`` is copied (the window edits it)."""
    library = tmp_path / "library"
    fetcher = fetcher or FakeFetcher(routes() if route_table is None else route_table)
    updater = LibraryUpdater(library, fetcher=fetcher, extra_dirs=[FIXTURES / "catalog", EFFECTS / "lib"])

    def reload_sources():
        sources = [("Biblioteca", library), ("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib")]
        saved = library / "AllZDL7_2.lst"
        return load_catalog(*[(label, f) for label, f in sources if f.is_dir()]), (
            load_models(saved) if saved.is_file() else {})

    return dict(models=registry(catalog), bank_dir=tmp_path / "bank", updater=updater, reload_sources=reload_sources,
                update_store=store if store is not None else UpdateStore(None), online=lambda: online,
                update_clock=lambda: clock), fetcher, library


def window(qtbot, tmp_path, catalog, **kw) -> tuple:
    opts, fetcher, library = options(tmp_path, catalog, **kw)
    w = MainWindow(dict(catalog), **opts)
    qtbot.addWidget(w)
    return w, fetcher, library


def startup_check(qtbot, w) -> bool:
    with qtbot.waitSignal(w.update_checked, timeout=5000, raising=False) as blocker:
        started = w.start_update_check()
    return started and blocker.signal_triggered


def open_view(qtbot, w):
    with qtbot.waitSignal(w.update_checked, timeout=5000):
        w.update_action.trigger()
    return w.update_panel


UPDATE_STATES = ["update-notice", "update-view", "update-downloading", "update-summary", "update-offline"]


def update_state(qtbot, tmp_path, catalog, state: str) -> MainWindow:
    """The windows of the update flow, for the clip and compact audits (each state is one thing a user meets)."""
    if state == "update-summary":  # six failures: the list is cut after four with «y 2 más»
        specs = [(f"0x0100004{n}", f"FX{n}.zip", "1.00") for n in range(6)]
        junk = {lib.ZIP_BASE_URL + s[1]: make_zip({"X.ZD2": b"junk"}) for s in specs}
        w, _, _ = window(qtbot, tmp_path, catalog,
                         route_table=routes({A1: [effect(s) for s in specs]}, zips=junk))
        w.show()
        view = open_view(qtbot, w)
        with qtbot.waitSignal(w.update_downloaded, timeout=5000):
            view.download_button.click()
        return w
    w, _, _ = window(qtbot, tmp_path, catalog, route_table={} if state == "update-offline" else None)
    w.show()
    if state == "update-notice":
        startup_check(qtbot, w)
        return w
    view = open_view(qtbot, w)
    if state == "update-downloading":
        view.set_busy(True)
        view.set_progress(1, 2, "RACKCOMP")
    return w
