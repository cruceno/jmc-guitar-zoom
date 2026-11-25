"""The effect library updater in the window: the calm notice, the update view, downloads, reload and errors.

No network: the channel is a fake fetcher with fixture lists and zips. The library folder is private to each test.
"""
import gc
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from update_support import (EFFECTS, FIXTURES, HALL_ID, NOW, RACKCOMP_ID, hall_newer, open_view, routes, startup_check,
                            window)
from test_ui_effects_manager import (AFTER, BEFORE, ON_PEDAL, PedalFiles, connected_window)
from updater_support import A1, COMP, FakeFetcher, effect, make_zip  # a model lists at least one effect, as the channel does

from jmc_guitar_zoom.effects.catalog import load_catalog
from jmc_guitar_zoom.library import updater as lib
from jmc_guitar_zoom.ui import strings as ST
from jmc_guitar_zoom.ui.settings import DAY_SECONDS, UpdateStore


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib"))


# ------------------------------------------------------------------ the start-up check and its notice


def test_a_startup_check_with_news_shows_a_calm_notice_with_a_button(qtbot, catalog, tmp_path):
    w, fetcher, _ = window(qtbot, tmp_path, catalog)
    w.show()
    assert startup_check(qtbot, w)
    assert w.update_notice.isVisibleTo(w) and w.update_notice_button.isVisibleTo(w)
    assert w.update_notice.full_text() == "Hay 2 efectos nuevos o actualizados para A1 FOUR"
    assert w.update_notice_button.text() == "Ver"
    assert sorted(fetcher.urls) == sorted([lib.EFFECTS_LIST_URL, lib.VERSIONS_LIST_URL])  # lists only: no zips


def test_the_notice_button_opens_the_update_view(qtbot, catalog, tmp_path):
    w, _, _ = window(qtbot, tmp_path, catalog)
    w.show()
    startup_check(qtbot, w)
    with qtbot.waitSignal(w.update_checked, timeout=5000):
        w.update_notice_button.click()
    assert w.update_toggle.isChecked() and w.update_panel.isVisibleTo(w)
    assert not w.update_notice.isVisibleTo(w)  # the news are on screen now


def test_the_notice_can_be_dismissed(qtbot, catalog, tmp_path):
    w, _, _ = window(qtbot, tmp_path, catalog)
    w.show()
    startup_check(qtbot, w)
    w.update_notice_dismiss.click()
    assert not w.update_notice.isVisibleTo(w) and not w.update_notice_button.isVisibleTo(w)


def test_no_notice_when_the_library_is_up_to_date(qtbot, catalog, tmp_path):
    w, _, _ = window(qtbot, tmp_path, catalog, route_table=routes({A1: [effect(COMP)]}))
    w.show()
    assert startup_check(qtbot, w)
    assert not w.update_notice.isVisibleTo(w)


def test_the_check_runs_at_most_once_a_day_and_only_when_online(qtbot, catalog, tmp_path):
    store = UpdateStore(None)
    w, fetcher, _ = window(qtbot, tmp_path, catalog, store=store)
    assert startup_check(qtbot, w)
    assert store.last_check == NOW  # recorded after a successful check
    fetcher.urls.clear()
    assert w.start_update_check() is False and fetcher.urls == []  # same day: throttled
    w._update_clock = lambda: NOW + DAY_SECONDS
    assert startup_check(qtbot, w) and fetcher.urls  # a day later it runs again


def test_nothing_is_requested_while_offline(qtbot, catalog, tmp_path):
    w, fetcher, _ = window(qtbot, tmp_path, catalog, online=False)
    assert w.start_update_check() is False and fetcher.urls == []
    assert w.update_notice.isHidden()


def test_a_failed_background_check_is_silent_and_is_not_recorded(qtbot, catalog, tmp_path):
    store = UpdateStore(None)
    w, _, _ = window(qtbot, tmp_path, catalog, route_table={}, store=store)
    w.show()
    assert startup_check(qtbot, w)
    assert store.last_check is None  # tried again at the next start
    assert not w.update_notice.isVisibleTo(w) and w.statusBar().currentMessage() == ST.READY


def test_without_an_updater_nothing_of_this_shows(qtbot, catalog):
    from jmc_guitar_zoom.ui.main_window import MainWindow

    w = MainWindow(dict(catalog))
    qtbot.addWidget(w)
    assert w.start_update_check() is False
    assert not w.update_action.isEnabled() and w.effects_panel.update_button.isHidden()


FIRMWARE_TEXT = ("Zoom publica firmware 1.02 para A1 FOUR (la pedalera tiene 1.01). "
                 "La actualización se hace con Guitar Lab o con el actualizador de Zoom en Windows o macOS.")


def pedal(w, version):
    w.apply_pedal_identity(SimpleNamespace(model=0x6E, member=0x11))
    w._set_pedal_firmware(version)


def test_a_newer_firmware_is_an_informational_notice_without_a_button(qtbot, catalog, tmp_path):
    w, _, _ = window(qtbot, tmp_path, catalog, route_table=routes({A1: [effect(COMP)]}))
    w.show()
    pedal(w, "1.01")
    startup_check(qtbot, w)
    assert w.update_notice.full_text() == FIRMWARE_TEXT
    assert "herramienta oficial" not in w.update_notice.full_text()
    assert w.update_notice.isVisibleTo(w) and not w.update_notice_button.isVisibleTo(w)


def test_the_same_firmware_without_the_update_flag_shows_no_notice(qtbot, catalog, tmp_path):
    table = routes({A1: [effect(COMP)]}, versions={A1: ("1.01", False)})
    w, _, _ = window(qtbot, tmp_path, catalog, route_table=table)
    w.show()
    pedal(w, "1.01")
    startup_check(qtbot, w)
    assert w.update_notice.isHidden() and w.update_notice.full_text() == ""


def test_the_update_flag_alone_shows_the_notice(qtbot, catalog, tmp_path):
    table = routes({A1: [effect(COMP)]}, versions={A1: ("1.01", True)})
    w, _, _ = window(qtbot, tmp_path, catalog, route_table=table)
    w.show()
    pedal(w, "1.01")
    startup_check(qtbot, w)
    assert w.update_notice.full_text().startswith("Zoom publica firmware 1.01 para A1 FOUR (la pedalera tiene 1.01).")


def test_the_firmware_notice_follows_the_pedal_connected_after_the_check(qtbot, catalog, tmp_path):
    w, _, _ = window(qtbot, tmp_path, catalog, route_table=routes({A1: [effect(COMP)]}))
    w.show()
    startup_check(qtbot, w)
    assert w.update_notice.isHidden()
    pedal(w, "1.01")
    assert w.update_notice.full_text() == FIRMWARE_TEXT
    w._set_pedal_firmware("1.02")
    assert w.update_notice.isHidden()


# ------------------------------------------------------------------ the update view


def test_the_menu_entry_opens_the_view_with_the_new_and_the_updated_effects(qtbot, catalog, tmp_path):
    w, _, _ = window(qtbot, tmp_path, catalog)
    w.show()
    menu_texts = [a.text() for a in w.library_button.menu().actions()]
    assert "Actualizar biblioteca de efectos…" in menu_texts
    view = open_view(qtbot, w)
    assert view.isVisibleTo(w) and not w.splitter.isVisible()
    assert view.new_names() == ["RACKCOMP"] and view.updated_names() == ["Hall"]
    assert view.download_button.isEnabled() and view.all_models.text() == "Todos los modelos"
    assert "RACKCOMP" in view.new_list.item(0).data(Qt_UserRole()).name
    card = view.updated_list.item(0).data(Qt_UserRole())
    assert (card.version, card.local_version, card.group) == ("1.60", "1.50", "REVERB")
    assert ST.update_card_line("REVERB", "1.60", "1.50", 18_000) == "Reverb · Versión 1.50 → 1.60 · 17,6 KB"
    assert view.scope_label.text() == "Efectos para A1 FOUR"


def Qt_UserRole():
    from jmc_guitar_zoom.ui.update_view import ROLE_UPDATE

    return ROLE_UPDATE


def test_the_all_models_checkbox_asks_for_every_model(qtbot, catalog, tmp_path):
    table = routes({A1: [effect(COMP)], "0x6E000000": [("0x01000020", "RACKCOMP.zip", "1.40")]} if False else None)
    w, _, _ = window(qtbot, tmp_path, catalog, route_table=table)
    w.show()
    view = open_view(qtbot, w)
    assert view.new_names() == ["RACKCOMP"]
    with qtbot.waitSignal(w.update_checked, timeout=5000):
        view.all_models.setChecked(True)
    assert view.scope_label.text() == "Efectos de todos los modelos"
    assert view.new_names() == ["RACKCOMP"]


def test_the_view_says_so_when_everything_is_up_to_date(qtbot, catalog, tmp_path):
    w, _, _ = window(qtbot, tmp_path, catalog, route_table=routes({A1: [effect(COMP)]}))
    w.show()
    view = open_view(qtbot, w)
    assert view.message() == ST.UPDATE_UP_TO_DATE and not view.download_button.isEnabled()


def test_the_view_shows_the_firmware_line_for_a_connected_older_pedal(qtbot, catalog, tmp_path):
    w, _, _ = window(qtbot, tmp_path, catalog)
    w.show()
    w.apply_pedal_identity(SimpleNamespace(model=0x6E, member=0x11))
    w._set_pedal_firmware("1.01")
    view = open_view(qtbot, w)
    assert view.firmware_label.isVisibleTo(w) and "firmware 1.02" in view.firmware_label.text() and "Guitar Lab" in view.firmware_label.text()


def test_the_effects_screen_button_leads_to_the_view(qtbot, monkeypatch, catalog, tmp_path):
    from update_support import options

    opts, _, _ = options(tmp_path, catalog)
    w = connected_window(qtbot, monkeypatch, dict(catalog), tmp_path, PedalFiles(BEFORE), **{k: v for k, v in opts.items() if k != "bank_dir"})
    w.show()
    w.open_effects_screen()
    assert w.effects_panel.update_button.isVisibleTo(w) and w.effects_panel.update_button.text() == "Actualizar biblioteca…"
    with qtbot.waitSignal(w.update_checked, timeout=5000):
        w.effects_panel.update_button.click()
    assert w.update_toggle.isChecked() and not w.effects_toggle.isChecked()


def test_the_view_closes_back_to_the_editor(qtbot, catalog, tmp_path):
    w, _, _ = window(qtbot, tmp_path, catalog)
    w.show()
    view = open_view(qtbot, w)
    view.close_button.click()
    assert not view.isVisibleTo(w) and w.splitter.isVisible() and w.library_button.isEnabled()


# ------------------------------------------------------------------ downloading


def test_a_download_reports_progress_saves_the_files_and_reloads_the_catalog(qtbot, catalog, tmp_path):
    w, _, library = window(qtbot, tmp_path, catalog)
    w.show()
    view = open_view(qtbot, w)
    seen = []
    original = view.set_progress
    view.set_progress = lambda done, total, name: (seen.append((done, total, name)), original(done, total, name))
    assert RACKCOMP_ID not in w.catalog and w.catalog[HALL_ID].version == "1.50"
    with qtbot.waitSignal(w.update_downloaded, timeout=5000):
        view.download_button.click()
    assert [(d, t) for d, t, _ in seen] == [(0, 2), (1, 2)]
    assert sorted(p.name for p in library.glob("*.zd2")) == ["HALL_160.zd2", "RACKCOMP_140.zd2"]
    # the catalog was reloaded in place: the editor catalog and the effects screen see the new effects
    assert RACKCOMP_ID in w.catalog and w.catalog[HALL_ID].version == "1.60"
    assert RACKCOMP_ID in w.allowed_ids and "RackComp" in w.catalog_panel.visible_names()
    assert w.catalog_panel.group_combo.findData("DYNAMICS") >= 0
    assert view.summary_label.text() == "Se descargaron 2 efectos." and view.pending() == []
    assert view.message() == ST.UPDATE_UP_TO_DATE and not view.failures_label.isVisibleTo(w)
    assert w.statusBar().currentMessage() == "Biblioteca actualizada: 2 efectos ya están en el catálogo"
    assert w.update_notice.isHidden()


def test_a_download_shows_the_new_effect_on_the_effects_screen_without_a_restart(qtbot, monkeypatch, catalog, tmp_path):
    from update_support import options

    opts, _, _ = options(tmp_path, catalog)
    w = connected_window(qtbot, monkeypatch, dict(catalog), tmp_path, PedalFiles(BEFORE), **{k: v for k, v in opts.items() if k != "bank_dir"})
    w.show()
    with qtbot.waitSignal(w.effects_panel.state_shown, timeout=5000):
        w.open_effects_screen()
    shown = lambda: w.effects_panel.available_names() + w.effects_panel.installed_names()  # noqa: E731
    assert "RACKCOMP.ZD2" not in shown()  # the pedal's list flags it, but nothing local describes it yet
    with qtbot.waitSignal(w.update_checked, timeout=5000):
        w.open_update_view()
    with qtbot.waitSignal(w.update_downloaded, timeout=5000):
        w.update_panel.download_button.click()
    w.update_panel.close_button.click()
    with qtbot.waitSignal(w.effects_panel.state_shown, timeout=5000):
        w.open_effects_screen()
    assert "RACKCOMP.ZD2" in shown()


def test_a_partial_failure_keeps_what_succeeded_and_names_what_failed(qtbot, catalog, tmp_path):
    bad = {lib.ZIP_BASE_URL + "HALL.zip": make_zip({"HALL.ZD2": b"not an effect"})}
    w, _, library = window(qtbot, tmp_path, catalog, route_table=routes(zips=bad))
    w.show()
    view = open_view(qtbot, w)
    with qtbot.waitSignal(w.update_downloaded, timeout=5000):
        view.download_button.click()
    assert [p.name for p in library.glob("*.zd2")] == ["RACKCOMP_140.zd2"]
    assert RACKCOMP_ID in w.catalog and w.catalog[HALL_ID].version == "1.50"
    assert view.summary_label.text() == "Se descargó 1 efecto; 1 efecto no se pudo descargar."
    assert view.failures_label.text() == "Hall: el archivo no es un efecto válido"
    assert view.updated_names() == ["Hall"] and view.new_names() == []  # the failed one stays to try again
    assert view.download_button.isEnabled()


def test_cancel_stops_after_the_effect_in_progress_and_keeps_what_was_saved(qtbot, catalog, tmp_path):
    table = routes()
    holder = {}

    class Cancelling(FakeFetcher):
        def __call__(self, url, max_bytes):
            body = super().__call__(url, max_bytes)
            if url.endswith(".zip"):
                holder["w"]._cancel_update_download()  # the user presses «Cancelar» during the first download
            return body

    fetcher = Cancelling(table)
    w, _, library = window(qtbot, tmp_path, catalog, fetcher=fetcher)
    holder["w"] = w
    w.show()
    view = open_view(qtbot, w)
    with qtbot.waitSignal(w.update_downloaded, timeout=5000):
        view.download_button.click()
    assert len(list(library.glob("*.zd2"))) == 1
    assert view.summary_label.text() == "Se descargó 1 efecto. La descarga se canceló."
    assert len(view.pending()) == 1


def test_the_buttons_follow_the_state_while_downloading(qtbot, catalog, tmp_path):
    w, _, _ = window(qtbot, tmp_path, catalog)
    w.show()
    view = open_view(qtbot, w)
    view.set_busy(True)
    assert view.cancel_button.isVisibleTo(w) and not view.download_button.isVisibleTo(w)
    assert not view.check_button.isEnabled() and not view.all_models.isEnabled()
    view.set_busy(False)
    assert not view.cancel_button.isVisibleTo(w) and view.download_button.isVisibleTo(w)


# ------------------------------------------------------------------ errors


def test_offline_the_view_shows_a_clear_message_and_nothing_crashes(qtbot, catalog, tmp_path):
    w, _, library = window(qtbot, tmp_path, catalog, route_table={})
    w.show()
    view = open_view(qtbot, w)
    assert view.message() == ST.UPDATE_ERROR_OFFLINE
    assert "conexión" in view.message() and not view.download_button.isEnabled() and view.check_button.isEnabled()
    assert not library.exists() or list(library.iterdir()) == []
    with qtbot.waitSignal(w.update_checked, timeout=5000):
        view.check_button.click()  # retry: still a message, still no crash
    assert view.message() == ST.UPDATE_ERROR_OFFLINE


def test_a_garbled_answer_is_a_message_not_a_crash(qtbot, catalog, tmp_path):
    table = routes()
    table[lib.EFFECTS_LIST_URL] = b"<html>captive portal</html>"
    w, _, _ = window(qtbot, tmp_path, catalog, route_table=table)
    w.show()
    assert open_view(qtbot, w).message() == ST.UPDATE_ERROR_OFFLINE


def test_closing_the_window_stops_the_updater_thread(qtbot, catalog, tmp_path):
    w, _, _ = window(qtbot, tmp_path, catalog)
    w.show()
    open_view(qtbot, w)
    thread = w._update_thread
    w.close()
    assert thread is not None and not thread.isRunning()


# ------------------------------------------------------------------ garbage collection only on the GUI thread


@pytest.fixture
def gc_guard_off():
    """Leave the collector as the suite's session guard set it, whatever a test installed."""
    from jmc_guitar_zoom.ui import gc_guard

    yield gc_guard
    gc_guard.install(QApplication.instance())


def test_install_turns_automatic_collection_off_and_the_timer_collects_on_the_gui_thread(qtbot, gc_guard_off, monkeypatch):
    """A collection started by a worker thread walks PySide wrappers the GUI thread is deleting: it crashed."""
    seen = []
    real = gc.collect
    monkeypatch.setattr(gc, "collect", lambda *a: seen.append(threading.current_thread()) or real(*a))
    gc.enable()
    timer = gc_guard_off.install(QApplication.instance(), interval_ms=10)
    assert not gc.isenabled()
    qtbot.waitUntil(lambda: bool(seen), timeout=2000)
    assert timer.isActive() and all(t is threading.main_thread() for t in seen)


def test_cycles_made_on_a_worker_thread_are_collected_later_on_the_gui_thread(qtbot, gc_guard_off):
    died_on = []

    class Cyclic:
        def __init__(self):
            self.me = self

        def __del__(self):
            died_on.append(threading.current_thread())

    gc_guard_off.install(QApplication.instance(), interval_ms=10)
    worker = threading.Thread(target=lambda: [Cyclic() for _ in range(50)])
    worker.start()
    worker.join()
    qtbot.waitUntil(lambda: len(died_on) == 50, timeout=2000)
    assert all(t is threading.main_thread() for t in died_on)


def test_installing_twice_keeps_one_timer(qtbot, gc_guard_off):
    app = QApplication.instance()
    first = gc_guard_off.install(app, interval_ms=10)
    second = gc_guard_off.install(app, interval_ms=10)
    assert second is not first and not first.isActive() and second.isActive()


def test_main_installs_the_guard_right_after_the_application_exists(qapp, monkeypatch):
    import jmc_guitar_zoom.__main__ as entry
    import jmc_guitar_zoom.ui.gc_guard as gc_guard
    import jmc_guitar_zoom.ui.main_window as main_window

    class Stop(Exception):
        pass

    def no_window(*a, **k):
        raise Stop

    installed = []
    monkeypatch.setattr(gc_guard, "install", lambda app, **k: installed.append(app))
    monkeypatch.setattr(main_window, "MainWindow", no_window)

    class SameApp:  # main() creates the application: hand it the one the suite already has
        def __new__(cls, argv):
            return qapp

        instance = staticmethod(QApplication.instance)

    monkeypatch.setattr("PySide6.QtWidgets.QApplication", SameApp)
    with pytest.raises(Stop):
        entry.main(["--no-connect"])
    assert installed == [qapp]


# ------------------------------------------------------------------ copy


def test_the_copy_is_neutral_spanish():
    assert ST.update_notice(1, "A1 FOUR") == "Hay un efecto nuevo o actualizado para A1 FOUR"
    assert ST.update_notice(3, "A1 FOUR") == "Hay 3 efectos nuevos o actualizados para A1 FOUR"
    assert ST.update_summary(0, 0, True) == "No se descargó ningún efecto. La descarga se canceló."
    assert ST.update_more_failures(3) == "y 3 más"
    for reason in ("bad_zip", "no_zd2", "many_zd2", "oversized", "id_mismatch", "version_mismatch", "exists"):
        assert ST.UPDATE_REASONS[reason]
    text = " ".join([ST.UPDATE_ERROR_OFFLINE, ST.UPDATE_BUTTON_TIP, *ST.UPDATE_REASONS.values()]).lower()
    assert " vos " not in text and "descargá" not in text and "podés" not in text
