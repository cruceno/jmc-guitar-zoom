"""The «Afinación y octavación» screen: live tuner from the audio input, guided assistant and the painted bridge."""
import json
import re

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPushButton, QWidget

from audio_signals import pluck, silence, sine
from test_ui_tuner import ON, pedal, sent_sysex  # noqa: F401 (pedal is a fixture)
from test_ui_tuner import catalog  # noqa: F401 (the fixture the pedal one needs)
from jmc_guitar_zoom.audio.capture import InputDevice
from jmc_guitar_zoom.audio.intonation import Round, Step, Stats, StringResult, Verdict
from jmc_guitar_zoom.ui import intonation as intonation_module
from jmc_guitar_zoom.ui import strings as S
from jmc_guitar_zoom.ui.glass import BackdropRoot
from jmc_guitar_zoom.ui.intonation import BridgeView, DotPlot, IntonationScreen
from jmc_guitar_zoom.ui.main_window import MainWindow
from jmc_guitar_zoom.ui.settings import IntonationStore

E2 = 82.41
DEVICES = [InputDevice("dev1", "PreSonus AudioBox USB", 2, 48000, True),
           InputDevice("dev2", "Micrófono integrado", 4, 44100)]


class FakeAudio(QObject):
    """Has the interface of ``AudioInput``; tests push synthetic samples through ``samples``."""

    samples = Signal(object)
    failed = Signal(str)

    def __init__(self, sample_rate: int = 48000, ok: bool = True) -> None:
        super().__init__()
        self.sample_rate = sample_rate
        self.running = False
        self.started: list[tuple[str, int]] = []
        self.stops = 0
        self._ok = ok

    def start(self, device_id: str, channel: int) -> bool:
        self.started.append((device_id, channel))
        self.running = self._ok
        return self._ok

    def stop(self) -> None:
        self.stops += 1
        self.running = False

    def push(self, data: np.ndarray, block: int = 960) -> None:
        for i in range(0, data.size, block):
            self.samples.emit(data[i:i + block])


def make_screen(qtbot, devices=DEVICES, audio=None, store=None, rounds=None, tolerance=None):
    audio = audio if audio is not None else FakeAudio()
    store = store if store is not None else IntonationStore()
    if rounds is not None:
        store.save(rounds=rounds)
    if tolerance is not None:
        store.save(tolerance=tolerance)
    root = BackdropRoot()
    qtbot.addWidget(root)
    screen = IntonationScreen(root, devices=lambda: list(devices), audio=audio,
                              store=store)
    screen.open_screen()
    return screen, audio


def play_note(audio, hz: float) -> None:
    audio.push(pluck(hz, 1.6)[0])
    audio.push(silence(0.4))


def play_round(audio, fretted_cents: float, harmonic_cents: float = 0.0, open_hz: float = E2) -> None:
    """The open string, the harmonic and the fretted note ``fretted_cents`` away from the harmonic."""
    harmonic = 2 * open_hz * 2 ** (harmonic_cents / 1200)
    play_note(audio, open_hz)
    play_note(audio, harmonic)
    play_note(audio, harmonic * 2 ** (fretted_cents / 1200))


def play_string(audio, fretted_cents, harmonic_cents: float = 0.0) -> None:
    """Every round of the string: ``fretted_cents`` is one value per round (or one for all the rounds of a screen)."""
    for cents in fretted_cents:
        play_round(audio, cents, harmonic_cents)


def inject(screen, offsets, number: int = 6) -> None:
    """A finished string whose rounds have exactly these fretted-vs-harmonic offsets (no audio involved)."""
    rounds = tuple(Round(E2, 2 * E2, 2 * E2 * 2 ** (d / 1200)) for d in offsets)
    screen.session.results[number] = StringResult(number, Stats(rounds))
    screen.session.string, screen.session.step = number, Step.RESULT
    screen.tolerance_combo.setCurrentIndex(0)  # the screen redraws on a tolerance change


# ------------------------------------------------------------------ live tuner


def test_the_live_tuner_shows_note_octave_cents_frequency_and_stable(qtbot):
    screen, audio = make_screen(qtbot)
    audio.push(sine(440 * 2 ** (2.4 / 1200), 1.2))
    assert screen.note_text() == "A4"
    cents = re.fullmatch(r"([+−]\d,\d) cents", screen.cents_text())
    assert cents is not None
    assert float(cents[1].replace(",", ".").replace("−", "-")) == pytest.approx(2.4, abs=0.6)
    assert re.fullmatch(r"44\d,\d\d Hz", screen.frequency_text())
    assert screen.stable_text() == S.INTONATION_STABLE
    assert screen.meter.cents == pytest.approx(2.4, abs=0.6)


def test_silence_clears_the_live_tuner(qtbot):
    screen, audio = make_screen(qtbot)
    audio.push(sine(440, 1.2))
    audio.push(silence(0.6))
    assert screen.note_text() == S.INTONATION_NO_NOTE
    assert screen.cents_text() == "" and screen.stable_text() == ""


def test_a_clipping_input_warns_to_lower_the_gain(qtbot):
    screen, audio = make_screen(qtbot)
    audio.push(sine(220, 0.6, amplitude=1.0))
    assert screen.level_message() == S.INTONATION_CLIPPING
    assert screen.level_meter.clipping


def test_a_note_below_minus_40_dbfs_asks_for_more_gain(qtbot):
    screen, audio = make_screen(qtbot)
    audio.push(sine(220, 0.8, amplitude=0.006))
    assert screen.level_message() == S.INTONATION_LOW_LEVEL
    assert screen.level_meter.level_db == pytest.approx(-44.4, abs=0.5)


def test_a_good_level_shows_no_warning(qtbot):
    screen, audio = make_screen(qtbot)
    audio.push(sine(220, 0.8, amplitude=0.3))
    assert screen.level_message() == ""


# ------------------------------------------------------------------ guided assistant


def test_the_assistant_opens_on_string_6_round_1_with_its_defaults(qtbot):
    screen, _ = make_screen(qtbot)
    assert screen.session.string == 6 and screen.session.step is Step.OPEN and screen.session.rounds == 5
    assert [c.text() for c in screen.string_chips.values()] == ["6 Mi", "5 La", "4 Re", "3 Sol", "2 Si", "1 Mi"]
    assert screen.tolerance_combo.currentText() == "±1" and screen.session.tolerance == 1.0
    assert screen.scale_combo.currentText() == "648 mm (25,5\")"
    assert screen.rounds_combo.currentText() == "5"
    assert screen.progress_text() == "Ronda 1 de 5 · Al aire"
    assert screen.instruction_text() == "Toque la cuerda 6 al aire y déjela sonar."
    assert screen.reminder_text() == "Pulse siempre con la misma fuerza, suave."
    assert screen.hint_text() == S.INTONATION_HINT
    assert screen.spread_text() == screen.mean_text() == screen.cross_text() == ""


def test_the_open_string_or_harmonic_toggle_is_gone(qtbot):
    screen, _ = make_screen(qtbot)
    texts = [b.text() for b in screen.findChildren(QPushButton)]
    assert "Cuerda al aire" not in texts and "Armónico del traste 12" not in texts
    assert not hasattr(S, "INTONATION_REFERENCE_OPEN") and not hasattr(S, "INTONATION_REFERENCE_HARMONIC")


def test_the_rounds_selector_offers_3_to_10_and_restarts_the_string(qtbot):
    store = IntonationStore()
    screen, _ = make_screen(qtbot, store=store)
    assert [screen.rounds_combo.itemText(i) for i in range(screen.rounds_combo.count())] == [str(n) for n in range(3, 11)]
    screen.rounds_combo.setCurrentIndex(0)
    assert screen.session.rounds == 3 and store.rounds == 3
    assert screen.progress_text() == "Ronda 1 de 3 · Al aire"
    screen.rounds_combo.setCurrentIndex(7)
    assert screen.session.rounds == 10 and store.rounds == 10
    assert screen.progress_text() == "Ronda 1 de 10 · Al aire"


def test_the_rounds_choice_is_remembered(qtbot, private_intonation):
    screen, _ = make_screen(qtbot, store=IntonationStore(private_intonation))
    screen.rounds_combo.setCurrentIndex(4)  # 7 rounds
    again, _ = make_screen(qtbot, store=IntonationStore(private_intonation))
    assert again.session.rounds == 7 and again.rounds_combo.currentText() == "7"
    assert again.progress_text() == "Ronda 1 de 7 · Al aire"


def test_choosing_a_chip_selects_that_string(qtbot):
    screen, _ = make_screen(qtbot)
    screen.string_chips[3].click()
    assert screen.session.string == 3 and screen.session.step is Step.OPEN
    assert screen.instruction_text() == "Toque la cuerda 3 al aire y déjela sonar."


def test_the_progress_line_and_instruction_follow_the_notes_of_each_round(qtbot):
    screen, audio = make_screen(qtbot, rounds=3)
    play_note(audio, E2)
    assert screen.progress_text() == "Ronda 1 de 3 · Armónico 12"
    assert screen.instruction_text() == "Toque el armónico del traste 12 de la cuerda 6 y déjelo sonar."
    play_note(audio, 2 * E2)
    assert screen.progress_text() == "Ronda 1 de 3 · Traste 12"
    assert screen.instruction_text() == "Pise la cuerda 6 en el traste 12, sin apretar de más, y déjela sonar."
    play_note(audio, 2 * E2)
    assert screen.progress_text() == "Ronda 2 de 3 · Al aire"
    assert screen.instruction_text() == "Toque la cuerda 6 al aire y déjela sonar."


def test_a_note_that_is_not_the_expected_one_is_refused_with_a_hint_for_each_guard(qtbot):
    screen, audio = make_screen(qtbot, rounds=3)
    play_note(audio, E2)
    play_note(audio, E2)  # the open string again where the harmonic goes
    assert screen.message_text() == ("Esa nota no es el armónico del traste 12 (la octava de la cuerda al aire): "
                                     "toque el armónico de la cuerda 6.")
    assert screen.progress_text() == "Ronda 1 de 3 · Armónico 12"
    play_note(audio, 2 * E2)
    assert screen.message_text() == ""  # a note that is being captured is the right one
    play_note(audio, E2)  # the open string again where the fretted note goes
    assert screen.message_text() == "Esa nota no es la octava de la cuerda al aire: pise la cuerda 6 en el traste 12."
    play_note(audio, 2 * E2)
    play_note(audio, 2 * E2 * 1.2)  # round 2: an open string far from round 1
    assert screen.message_text() == ("Esa nota no es la cuerda 6 al aire como en la ronda 1: "
                                     "toque la cuerda 6 al aire sin cambiar la afinación.")
    assert screen.progress_text() == "Ronda 2 de 3 · Al aire"


def test_a_detuned_open_string_suggests_tuning_first(qtbot):
    screen, audio = make_screen(qtbot)
    play_note(audio, E2 * 2 ** (8 / 1200))
    assert screen.session.step is Step.HARMONIC
    assert re.fullmatch(r"La cuerda está \d,\d cents desafinada: conviene afinarla antes de medir\.",
                        screen.info_text())


def test_a_tuned_open_string_shows_no_detune_line(qtbot):
    screen, audio = make_screen(qtbot)
    play_note(audio, E2)
    assert screen.session.step is Step.HARMONIC and screen.info_text() == ""


def test_the_capture_progress_bar_follows_the_session(qtbot):
    screen, audio = make_screen(qtbot)
    assert screen.progress_bar.value() == 0
    audio.push(pluck(E2, 2.0)[0][:int(48000 * 0.9)])
    assert screen.session.progress > 0
    assert screen.progress_bar.value() == round(screen.session.progress * 100)


@pytest.mark.parametrize("offsets, arrow, verdict, chip, words", [
    ([4.0, 4.0, 4.0], "down", Verdict.SHARP, "sharp", "alto: aleje la selleta del mástil unos"),
    ([-4.0, -4.0, -4.0], "up", Verdict.FLAT, "flat", "bajo: acerque la selleta al mástil unos"),
    ([0.0, 0.0, 0.0], "ok", Verdict.OK, "ok", "En tolerancia: la selleta 6 está bien."),
    ([-4.0, 0.0, 4.0], "unsure", Verdict.UNSURE, "unsure", "No concluyente: la dispersión (±"),
])
def test_a_guided_run_reaches_the_verdict_by_itself(qtbot, offsets, arrow, verdict, chip, words):
    screen, audio = make_screen(qtbot, rounds=3, tolerance=2.0)
    play_string(audio, offsets)
    result = screen.session.results[6]
    assert screen.session.step is Step.RESULT and result.verdict(2.0) is verdict
    assert screen.progress_text() == "Resultado"
    assert words in screen.instruction_text()
    assert screen.bridge.arrow(6) == arrow
    assert screen.chip_state(6) == chip
    assert all(screen.bridge.arrow(n) is None for n in (5, 4, 3, 2, 1))


def test_the_advice_gives_the_mean_cents_and_the_saddle_move_with_decimal_commas(qtbot):
    screen, audio = make_screen(qtbot, rounds=3)
    play_string(audio, [4.0, 4.0, 4.0])
    text = screen.instruction_text()
    shift = re.search(r"está (\d,\d) cents alto: aleje la selleta del mástil unos (\d,\d) mm, "
                      r"afine la cuerda y mida de nuevo\.", text)
    assert shift is not None
    cents = float(shift[1].replace(",", "."))
    assert cents == pytest.approx(screen.session.results[6].offset, abs=0.06)
    assert float(shift[2].replace(",", ".")) == pytest.approx(cents * 648 * 0.693147 / 1200, abs=0.06)


def test_the_unsure_text_quotes_the_spread_and_the_mean_and_does_not_advise_a_move(qtbot):
    screen, _ = make_screen(qtbot)
    inject(screen, [2.0, 0.5, 3.5])
    assert screen.instruction_text() == ("No concluyente: la dispersión (±3,7 cents) es comparable al desvío (+2,0 cents). "
                                         "Repita la medición o mejore el toque; no mueva la selleta todavía.")
    assert "selleta del mástil" not in screen.instruction_text()


def test_the_stats_show_the_touch_repeatability_the_mean_with_its_interval_and_the_rounds(qtbot):
    screen, _ = make_screen(qtbot)
    inject(screen, [3.0, 3.2, 2.8])
    assert screen.spread_text() == "Toque (desvío estándar): al aire ±0,0 · armónico ±0,0 · traste 12 ±0,2 cents"
    assert screen.mean_text() == "Desvío: +3,0 ± 0,5 cents (95 %, 3 rondas)"
    assert screen.cross_text() == ""


def test_the_cross_check_warning_shows_when_the_harmonic_and_the_open_string_disagree(qtbot):
    screen, _ = make_screen(qtbot)
    rounds = tuple(Round(E2, 2 * E2 * 2 ** (2.4 / 1200), 2 * E2 * 2 ** (2.4 / 1200)) for _ in range(3))
    screen.session.results[6] = StringResult(6, Stats(rounds))
    screen.session.step = Step.RESULT
    screen.tolerance_combo.setCurrentIndex(0)
    assert screen.cross_text() == ("El armónico y la cuerda al aire no coinciden (+2,4 cents): "
                                   "revise la afinación o el toque.")


def test_the_stats_appear_while_the_rounds_are_being_taken(qtbot):
    screen, audio = make_screen(qtbot, rounds=3)
    play_round(audio, 1.0)
    assert screen.spread_text() == "" and screen.mean_text() == ""  # one round: no spread and no interval yet
    assert screen.plot.interval(0) is not None and screen.plot.interval(0)[1] is None
    play_round(audio, 1.0)
    assert screen.spread_text().startswith("Toque (desvío estándar): al aire ±")
    assert screen.mean_text() == ""  # two rounds: a spread, but no interval yet
    play_round(audio, 1.0)
    assert re.fullmatch(r"Desvío: \+\d,\d ± \d,\d cents \(95 %, 3 rondas\)", screen.mean_text())


def test_the_dot_plot_shows_a_dot_per_take_the_mean_with_its_interval_and_the_tolerance(qtbot):
    screen, _ = make_screen(qtbot)
    inject(screen, [3.0, 3.2, 2.8])
    plot = screen.plot
    assert plot.row_names() == ("Traste 12 − armónico", "Traste 12 − 2×aire", "Armónico − 2×aire")
    assert plot.dots(0) == pytest.approx((3.0, 3.2, 2.8), abs=1e-6)
    assert plot.dots(1) == pytest.approx((3.0, 3.2, 2.8), abs=1e-6)  # the open string was perfect: same offsets
    assert plot.dots(2) == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
    mean, half = plot.interval(0)
    assert mean == pytest.approx(3.0, abs=1e-6) and half == pytest.approx(4.303 * 0.2 / 3 ** 0.5, abs=1e-6)
    assert plot.interval(2) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert plot.tolerance == 0.5  # inject() picks the first tolerance
    screen.tolerance_combo.setCurrentIndex(2)
    assert plot.tolerance == 2.0
    plot.resize(420, 130)
    plot.grab()  # paints without raising


def test_the_dot_plot_is_empty_before_any_round(qtbot):
    screen, _ = make_screen(qtbot)
    assert [screen.plot.dots(i) for i in range(3)] == [(), (), ()]
    assert [screen.plot.interval(i) for i in range(3)] == [None, None, None]
    screen.plot.resize(420, 130)
    screen.plot.grab()


def test_repeat_last_take_goes_back_one_note_even_across_a_round(qtbot):
    screen, audio = make_screen(qtbot, rounds=3)
    assert screen.repeat_button.text() == "Repetir última toma" and not screen.repeat_button.isEnabled()
    play_note(audio, E2)
    play_note(audio, 2 * E2)
    assert screen.repeat_button.isEnabled() and screen.progress_text() == "Ronda 1 de 3 · Traste 12"
    screen.repeat_button.click()
    assert screen.progress_text() == "Ronda 1 de 3 · Armónico 12"
    assert screen.instruction_text() == "Toque el armónico del traste 12 de la cuerda 6 y déjelo sonar."
    play_note(audio, 2 * E2)
    play_note(audio, 2 * E2)
    assert screen.progress_text() == "Ronda 2 de 3 · Al aire"
    screen.repeat_button.click()  # back to the fretted note of round 1
    assert screen.progress_text() == "Ronda 1 de 3 · Traste 12"
    screen.repeat_button.click()
    screen.repeat_button.click()
    assert screen.progress_text() == "Ronda 1 de 3 · Al aire" and not screen.repeat_button.isEnabled()


def test_measure_again_restarts_the_string_from_round_1(qtbot):
    screen, audio = make_screen(qtbot, rounds=3)
    play_string(audio, [4.0, 4.0, 4.0])
    screen.remeasure_button.click()
    assert screen.session.step is Step.OPEN and screen.session.string == 6 and screen.session.round == 1
    assert screen.progress_text() == "Ronda 1 de 3 · Al aire"
    assert 6 in screen.session.results  # the measure stays until it is replaced


def test_next_string_moves_on_and_the_last_one_says_all_are_in_tolerance(qtbot):
    screen, audio = make_screen(qtbot)
    screen.next_button.click()
    assert screen.session.string == 5
    ok = tuple(Round(E2, 2 * E2, 2 * E2) for _ in range(3))
    screen.session.results.update({n: StringResult(n, Stats(ok)) for n in range(1, 7)})
    screen.next_button.click()
    assert screen.message_text() == S.INTONATION_ALL_OK


def test_the_verdict_shown_follows_the_current_tolerance(qtbot):
    screen, _ = make_screen(qtbot)
    inject(screen, [1.6, 1.8, 1.4])  # mean 1.6 ± 0.5
    assert screen.chip_state(6) == "sharp" and screen.bridge.arrow(6) == "down"
    screen.tolerance_combo.setCurrentIndex(1)  # ±1
    assert screen.chip_state(6) == "sharp"
    screen.tolerance_combo.setCurrentIndex(2)  # ±2: the interval (1.1 to 2.1) crosses the edge
    assert screen.session.tolerance == 2.0
    assert screen.chip_state(6) == "unsure" and screen.bridge.arrow(6) == "unsure"
    assert screen.session.results[6].offset == pytest.approx(1.6, abs=1e-6)  # nothing measured is replaced


def test_the_scale_changes_the_advised_saddle_move(qtbot):
    screen, _ = make_screen(qtbot)
    inject(screen, [12.0, 12.2, 11.8])
    before = re.search(r"unos (\d,\d) mm", screen.instruction_text())[1]
    screen.scale_combo.setCurrentIndex(0)  # 628 mm
    after = re.search(r"unos (\d,\d) mm", screen.instruction_text())[1]
    assert float(after.replace(",", ".")) < float(before.replace(",", "."))


# ------------------------------------------------------------------ bridge


def test_the_bridge_shows_an_arrow_per_verdict_with_its_offset(qtbot):
    bridge = BridgeView()
    qtbot.addWidget(bridge)
    bridge.set_results({6: (2.1, Verdict.SHARP), 5: (-3.0, Verdict.FLAT), 4: (0.2, Verdict.OK)}, active=3)
    assert [bridge.arrow(n) for n in (6, 5, 4, 3)] == ["down", "up", "ok", None]
    assert bridge.offset_label(6) == "+2,1" and bridge.offset_label(5) == "−3,0"
    assert bridge.offset_label(3) == ""
    assert bridge.active_string == 3
    bridge.resize(700, 260)
    bridge.grab()  # paints without raising


def test_an_unsure_string_shows_a_neutral_mark_and_no_arrow(qtbot):
    bridge = BridgeView()
    qtbot.addWidget(bridge)
    bridge.set_results({6: (2.0, Verdict.UNSURE), 5: (0.0, Verdict.OK)}, active=6)
    assert bridge.arrow(6) == "unsure" and bridge.arrow_length(6) == 0.0 and bridge.arrow(5) == "ok"
    assert bridge.offset_label(6) == "+2,0"
    bridge.resize(700, 260)
    bridge.grab()


def test_a_longer_arrow_for_a_bigger_offset(qtbot):
    bridge = BridgeView()
    qtbot.addWidget(bridge)
    bridge.set_results({6: (1.5, Verdict.SHARP), 5: (6.0, Verdict.SHARP), 4: (50.0, Verdict.SHARP)}, active=None)
    assert bridge.arrow_length(6) < bridge.arrow_length(5) < bridge.arrow_length(4) <= BridgeView.MAX_ARROW


def test_the_screen_marks_the_active_string_on_the_bridge(qtbot):
    screen, _ = make_screen(qtbot)
    assert screen.bridge.active_string == 6
    screen.string_chips[2].click()
    assert screen.bridge.active_string == 2


# ------------------------------------------------------------------ input device


def test_the_default_device_and_channel_1_are_opened_first(qtbot):
    screen, audio = make_screen(qtbot)
    assert audio.started == [("dev1", 0)]
    assert [screen.device_combo.itemText(i) for i in range(2)] == ["PreSonus AudioBox USB", "Micrófono integrado"]
    assert [screen.channel_combo.itemText(i) for i in range(screen.channel_combo.count())] == ["Canal 1", "Canal 2"]


def test_the_device_and_channel_choice_is_passed_to_the_input_and_remembered(qtbot):
    store = IntonationStore()
    screen, audio = make_screen(qtbot, store=store)
    screen.device_combo.setCurrentIndex(1)
    assert audio.started[-1] == ("dev2", 0)
    assert screen.channel_combo.count() == 4
    screen.channel_combo.setCurrentIndex(2)
    assert audio.started[-1] == ("dev2", 2)
    again, audio2 = make_screen(qtbot, store=store)
    assert audio2.started == [("dev2", 2)]
    assert again.device_combo.currentText() == "Micrófono integrado" and again.channel_combo.currentText() == "Canal 3"


def test_the_remembered_choice_survives_a_new_store_on_the_same_file(qtbot, private_intonation):
    screen, _ = make_screen(qtbot, store=IntonationStore(private_intonation))
    screen.device_combo.setCurrentIndex(1)
    screen.tolerance_combo.setCurrentIndex(0)
    screen.rounds_combo.setCurrentIndex(5)  # 8 rounds
    screen.scale_combo.setCurrentIndex(3)
    again, audio = make_screen(qtbot, store=IntonationStore(private_intonation))
    assert audio.started == [("dev2", 0)]
    assert again.session.tolerance == 0.5 and again.session.rounds == 8
    assert again.scale_combo.currentText() == "650 mm (clásica)" and again.rounds_combo.currentText() == "8"


def test_the_screen_uses_the_remembered_file_by_default(qtbot, private_intonation):
    root = BackdropRoot()
    qtbot.addWidget(root)
    screen = IntonationScreen(root, devices=lambda: list(DEVICES), audio=FakeAudio())
    screen.open_screen()
    screen.device_combo.setCurrentIndex(1)
    assert json.loads(private_intonation.read_text(encoding="utf-8"))["device"] == "dev2"


def test_a_remembered_device_that_is_gone_falls_back_to_the_first_one(qtbot):
    store = IntonationStore()
    store.save(device="gone", channel=3)
    screen, audio = make_screen(qtbot, store=store)
    assert audio.started == [("dev1", 0)]
    assert screen.device_combo.currentText() == "PreSonus AudioBox USB"


def test_the_refresh_button_lists_the_devices_again(qtbot):
    listed = list(DEVICES[:1])
    audio = FakeAudio()
    root = BackdropRoot()
    qtbot.addWidget(root)
    screen = IntonationScreen(root, devices=lambda: list(listed), audio=audio, store=IntonationStore())
    screen.open_screen()
    assert screen.device_combo.count() == 1
    listed.append(DEVICES[1])
    screen.refresh_button.click()
    assert screen.device_combo.count() == 2 and screen.device_combo.currentText() == "PreSonus AudioBox USB"


def test_without_input_devices_the_assistant_is_off_and_says_why(qtbot):
    screen, audio = make_screen(qtbot, devices=[])
    assert screen.status_text() == "No hay entradas de audio disponibles"
    assert not screen.assistant_box.isEnabled()
    assert audio.started == []
    assert not screen.device_combo.isEnabled() and not screen.channel_combo.isEnabled()


def test_an_input_that_cannot_be_opened_is_reported(qtbot):
    screen, audio = make_screen(qtbot, audio=FakeAudio(ok=False))
    assert screen.status_text() == S.INTONATION_INPUT_FAILED
    audio.failed.emit("dev1")
    assert screen.status_text() == S.INTONATION_INPUT_FAILED


def test_closing_the_screen_stops_the_input(qtbot):
    screen, audio = make_screen(qtbot)
    screen.close_screen()
    assert not audio.running and audio.stops >= 1


def test_the_tracker_follows_the_sample_rate_of_the_input(qtbot):
    audio = FakeAudio(sample_rate=44100)
    screen, _ = make_screen(qtbot, audio=audio)
    audio.push(sine(440, 1.2, sr=44100))
    assert screen.note_text() == "A4"


# ------------------------------------------------------------------ the remembered choice file


def test_the_store_defaults_when_the_file_is_missing_or_corrupt(tmp_path):
    defaults = (None, 0, 1.0, 648.0, 5)
    for content in (None, "{not json", "[]", json.dumps({"tolerance": 9, "scale_mm": "x", "channel": -1,
                                                          "rounds": "many", "device": 4})):
        path = tmp_path / "intonation.json"
        path.unlink(missing_ok=True)
        if content is not None:
            path.write_text(content, encoding="utf-8")
        store = IntonationStore(path)
        assert (store.device, store.channel, store.tolerance, store.scale_mm, store.rounds) == defaults


@pytest.mark.parametrize("stored, expected", [(3, 3), (7, 7), (10, 10), (1, 3), (0, 3), (99, 10), (True, 5),
                                              (6.5, 5), (None, 5), ("8", 5)])
def test_the_stored_rounds_are_clamped_to_3_to_10_and_bad_values_are_the_default(tmp_path, stored, expected):
    path = tmp_path / "intonation.json"
    path.write_text(json.dumps({"rounds": stored}), encoding="utf-8")
    assert IntonationStore(path).rounds == expected


def test_the_store_writes_and_reads_every_key(tmp_path):
    path = tmp_path / "sub" / "intonation.json"
    IntonationStore(path).save(device="d", channel=1, tolerance=2.0, scale_mm=635.0, rounds=8)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "device": "d", "channel": 1, "tolerance": 2.0, "scale_mm": 635.0, "rounds": 8}
    again = IntonationStore(path)
    assert (again.device, again.channel, again.tolerance, again.scale_mm, again.rounds) == ("d", 1, 2.0, 635.0, 8)


def test_the_store_ignores_the_old_reference_key_and_rejects_it_on_save(tmp_path):
    path = tmp_path / "intonation.json"
    path.write_text(json.dumps({"reference": "harmonic", "rounds": 4}), encoding="utf-8")
    store = IntonationStore(path)
    assert store.rounds == 4 and not hasattr(store, "reference")
    with pytest.raises(KeyError):
        store.save(reference="open")


def test_the_store_never_raises_when_it_cannot_write(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    store = IntonationStore(blocker / "intonation.json")  # its folder is a file
    store.save(device="d")
    assert store.device == "d"


# ------------------------------------------------------------------ main window


@pytest.fixture
def fakes(monkeypatch):
    audio = FakeAudio()
    monkeypatch.setattr(intonation_module, "list_input_devices", lambda: list(DEVICES))
    monkeypatch.setattr(intonation_module, "AudioInput", lambda parent=None: audio)
    return audio


def test_the_button_opens_and_closes_the_screen_without_a_pedal(qtbot, catalog, fakes):
    w = MainWindow(catalog)
    qtbot.addWidget(w)
    assert w.intonation_button.isEnabled() and w.intonation_button.isCheckable()
    assert w.intonation_button.accessibleName() == "Afinación y octavación"
    assert w.intonation_button.toolTip() == "Afinación y octavación con la placa de audio (O)"
    w.intonation_button.click()
    assert w.intonation_panel.isVisibleTo(w) and not w.splitter.isVisibleTo(w)
    assert fakes.started == [("dev1", 0)]
    assert not w.edit_button.isEnabled() and not w.library_button.isEnabled()
    w.intonation_button.click()
    assert not w.intonation_panel.isVisibleTo(w) and w.splitter.isVisibleTo(w)
    assert fakes.stops >= 1 and w.edit_button.isEnabled()


def test_the_key_o_and_the_close_chip_toggle_the_screen(qtbot, catalog, fakes):
    w = MainWindow(catalog)
    qtbot.addWidget(w)
    assert w.intonation_shortcut.key().toString() == "O"
    w.intonation_shortcut.activated.emit()
    assert w.intonation_button.isChecked() and w.intonation_panel.isVisibleTo(w)
    assert w.intonation_panel.exit_button.text() == "Cerrar" and w.intonation_panel.exit_button.key == "O"
    w.intonation_panel.exit_button.click()
    assert not w.intonation_button.isChecked() and not w.intonation_panel.isVisibleTo(w)
    w.intonation_shortcut.activated.emit()
    w.intonation_shortcut.activated.emit()
    assert not w.intonation_button.isChecked()


def test_the_screen_locks_the_other_screens_and_the_editor(qtbot, catalog, fakes):
    w = MainWindow(catalog)
    qtbot.addWidget(w)
    w.intonation_button.click()
    assert not w.bank_button.isEnabled() and not w.effects_toggle.isEnabled()
    assert not w.update_toggle.isEnabled() and not w.open_file_button.isEnabled()
    assert not w.save_button.isEnabled() and not w.discard_button.isEnabled()
    w.intonation_button.click()
    assert w.bank_button.isEnabled() and w.effects_toggle.isEnabled()


@pytest.mark.parametrize("other", ["bank", "effects"])
def test_the_screen_cannot_open_over_another_screen(qtbot, catalog, fakes, other):
    w = MainWindow(catalog)
    qtbot.addWidget(w)
    if other == "bank":
        w.bank_button.setChecked(True)
    else:
        w.effects_toggle.setChecked(True)
    assert not w.intonation_button.isEnabled()
    w.intonation_shortcut.activated.emit()
    assert not w.intonation_button.isChecked()


def test_the_screen_and_the_pedal_tuner_exclude_each_other_and_never_start_the_pedal_tuner(qtbot, pedal, fakes):
    w, transport = pedal
    w.intonation_button.click()
    assert w.intonation_panel.isVisibleTo(w) and not w.tuner_button.isEnabled()
    assert ON not in sent_sysex(transport)
    w.intonation_button.click()
    assert w.tuner_button.isEnabled()
    w.tuner_button.click()
    qtbot.waitUntil(lambda: ON in sent_sysex(transport), timeout=3000)
    assert not w.intonation_button.isEnabled()
    w.intonation_shortcut.activated.emit()
    assert not w.intonation_button.isChecked()
    w.tuner_button.click()
    w.close()


def test_closing_the_window_stops_the_input(qtbot, catalog, fakes):
    w = MainWindow(catalog)
    qtbot.addWidget(w)
    w.intonation_button.click()
    stops = fakes.stops
    w.close()
    assert fakes.stops > stops and not fakes.running


def test_the_pedal_tuner_still_opens_as_before(qtbot, pedal):
    w, transport = pedal
    assert w.tuner_button.isEnabled() and not w.intonation_button.isChecked()
    w.tuner_button.click()
    qtbot.waitUntil(lambda: ON in sent_sysex(transport), timeout=3000)
    assert w.tuner_panel.isVisibleTo(w) and not w.splitter.isVisibleTo(w)
    assert w.tuner_button.isChecked() and not w.bank_button.isEnabled()
    w.tuner_button.click()
    w.close()


def test_the_screen_is_a_widget_of_the_window(qtbot, catalog, fakes):
    w = MainWindow(catalog)
    qtbot.addWidget(w)
    assert isinstance(w.intonation_panel, QWidget) and not w.intonation_panel.isVisibleTo(w)


# ------------------------------------------------------------------ header room and the library menu


@pytest.fixture
def themed(qapp):
    from jmc_guitar_zoom.ui.fonts import register_fonts
    from jmc_guitar_zoom.ui.theme import apply_dark_theme

    register_fonts()
    apply_dark_theme(qapp)
    yield
    qapp.setStyleSheet("")


def offline_window(qtbot, themed, fakes, width):
    from jmc_guitar_zoom.effects.catalog import load_catalog
    from ui_replies import FIXTURES

    w = MainWindow(load_catalog(("pedal", FIXTURES / "catalog")))
    qtbot.addWidget(w)
    w.load_offline(FIXTURES / "backup")
    w.resize(width, 900)
    w.show()
    return w


def test_in_the_approved_1440_header_the_button_gives_way_and_nothing_else_changes(qtbot, themed, fakes):
    w = offline_window(qtbot, themed, fakes, 1440)
    assert not w.intonation_button.isVisibleTo(w)
    assert w.tuner_button.text() == S.TUNER and w._header_level == 1  # the old level 1: only the caption is gone
    w.intonation_shortcut.activated.emit()
    assert w.intonation_panel.isVisibleTo(w) and w.intonation_action.isChecked()
    w.intonation_shortcut.activated.emit()
    assert not w.intonation_panel.isVisibleTo(w)


def test_the_library_menu_entry_opens_and_closes_the_screen_and_follows_the_button_rule(qtbot, themed, fakes):
    w = offline_window(qtbot, themed, fakes, 1440)
    assert w.intonation_action.text().startswith("Afinación y octavación…")
    assert w.intonation_action.isEnabled() and w.intonation_action in w.library_button.menu().actions()
    w.intonation_action.trigger()
    assert w.intonation_panel.isVisibleTo(w) and w.intonation_button.isChecked()
    w.intonation_action.trigger()
    assert not w.intonation_panel.isVisibleTo(w) and not w.intonation_action.isChecked()
    w.bank_button.setChecked(True)
    assert not w.intonation_action.isEnabled()


def test_in_a_wide_window_the_button_is_visible_and_key_o_works(qtbot, themed, fakes):
    w = offline_window(qtbot, themed, fakes, 2000)
    assert w.intonation_button.isVisibleTo(w) and w._header_level == 0
    w.intonation_shortcut.activated.emit()
    assert w.intonation_button.isChecked() and w.intonation_panel.isVisibleTo(w)
    w.intonation_button.click()
    assert not w.intonation_panel.isVisibleTo(w)


EXIT_SCRIPT = """
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
app = QApplication([])
from jmc_guitar_zoom.ui.glass import BackdropRoot
from jmc_guitar_zoom.ui.intonation import IntonationScreen
from jmc_guitar_zoom.ui.settings import IntonationStore
root = BackdropRoot()
IntonationScreen(root, devices=lambda: [], store=IntonationStore())
root.close()
root.deleteLater()
app.processEvents()
"""


def test_the_screen_lets_the_interpreter_exit_cleanly():
    # a lambda capturing the screen in a child button's signal made Python segfault after Qt at exit: every test
    # still passed, then the run died with exit code 139 (pytest cannot see it in-process)
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(root)}
    result = subprocess.run([sys.executable, "-c", EXIT_SCRIPT], cwd=root, env=env, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-400:]


def test_a_rounded_zero_never_shows_a_minus_sign():
    assert S.decimal(-0.04, 1, signed=True) == "+0,0"
    assert S.decimal(-0.04) == "0,0"
    assert S.decimal(-0.06, 1, signed=True) == "−0,1"
