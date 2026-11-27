"""The «Calibración» screen: four steps (relief, action, pickups, intonation) around the audio tuner."""
import json

import numpy as np
import pytest

from audio_signals import SR, pluck, silence
from test_ui_intonation import DEVICES, FakeAudio, play_round
from test_ui_tuner import catalog  # noqa: F401 (the fixture the main window needs)
from jmc_guitar_zoom.audio.intonation import Step
from jmc_guitar_zoom.calibration import FENDER_STYLE, GIBSON_STYLE
from jmc_guitar_zoom.ui import intonation as intonation_module
from jmc_guitar_zoom.ui import strings as S
from jmc_guitar_zoom.ui.glass import BackdropRoot
from jmc_guitar_zoom.ui.intonation import IntonationScreen
from jmc_guitar_zoom.ui.main_window import MainWindow
from jmc_guitar_zoom.ui.settings import CalibrationStore, IntonationStore

OPEN = {6: 82.407, 5: 110.0, 4: 146.832, 3: 195.998, 2: 246.942, 1: 329.628}


def make(qtbot, calibration=None, rounds=3):
    audio = FakeAudio()
    calibration = calibration if calibration is not None else CalibrationStore()
    store = IntonationStore()
    store.save(rounds=rounds)
    root = BackdropRoot()
    qtbot.addWidget(root)
    screen = IntonationScreen(root, devices=lambda: list(DEVICES), audio=audio, store=store,
                              calibration=calibration)
    screen.open_screen()
    return screen, audio


def ring(audio, hz, peak=0.5, dur=1.6, seed=1):
    audio.push(pluck(hz, dur, peak=peak, seed=seed)[0])
    audio.push(silence(0.4))


def modulated(f0, depth_cents, rate_hz, dur=2.5):
    t = np.arange(int(dur * SR)) / SR
    bend = 2 ** (depth_cents * np.sin(2 * np.pi * rate_hz * t) / 1200)
    x = np.zeros_like(t)
    for n in range(1, 10):
        x += (1.0 / n) * np.exp(-t * (0.5 + 0.2 * n)) * np.sin(2 * np.pi * np.cumsum(n * f0 * bend) / SR)
    return (0.5 * x / np.max(np.abs(x))).astype(np.float32)


# ------------------------------------------------------------------ the step bar


def test_the_step_bar_has_the_four_steps_in_order_with_the_recommended_order_line(qtbot):
    screen, _ = make(qtbot)
    assert [screen.step_buttons[n].text() for n in (1, 2, 3, 4)] == [
        "1 Curvatura del mástil", "2 Acción", "3 Pastillas", "4 Octavación"]
    assert screen.order_text() == ("Orden recomendado: curvatura → acción → pastillas → octavación. "
                                   "La octavación va última porque las otras la cambian.")
    assert screen.title.text().lower() == "calibración"


def test_the_first_time_it_opens_on_step_1_and_each_step_shows_only_its_page(qtbot):
    screen, _ = make(qtbot)
    assert screen.step == 1 and screen.step_buttons[1].isChecked()
    pages = {1: screen.relief, 2: screen.action, 3: screen.pickups, 4: screen.assistant_box}
    screen.show()
    for step in (1, 2, 3, 4, 1):
        screen.step_buttons[step].click()
        assert screen.step == step
        for number, page in pages.items():
            assert page.isVisibleTo(screen) == (number == step)
        assert screen.bridge.isVisibleTo(screen) == (step == 4)
        assert screen.preset_combo.isVisibleTo(screen) == (step != 4)
        # the input bar and the live tuner serve every step: the retune after each adjustment uses them
        assert screen.device_combo.isVisibleTo(screen) and screen.meter.isVisibleTo(screen)
        assert screen.level_meter.isVisibleTo(screen)


def test_the_last_step_is_remembered_between_openings_and_in_the_file(qtbot, tmp_path):
    path = tmp_path / "calibration.json"
    screen, _ = make(qtbot, CalibrationStore(path))
    screen.go_to_step(3)
    assert json.loads(path.read_text(encoding="utf-8"))["step"] == 3
    again, _ = make(qtbot, CalibrationStore(path))
    assert again.step == 3
    assert again.step_buttons[3].isChecked()


def test_bad_values_in_the_calibration_file_are_the_defaults(tmp_path):
    path = tmp_path / "calibration.json"
    bad = {"step": 9, "preset": "Nada", "custom": {"relief_mm": "x", "action_bass_mm": -3, "radius_in": 1e9,
                                                      "pickups": "no", "pickup_targets": {"p90": [1]}}}
    path.write_text(json.dumps(bad), encoding="utf-8")
    store = CalibrationStore(path)
    assert store.step == 1 and store.preset == "Estilo Fender (simple)"
    assert store.custom.relief_mm == 0.25 and store.custom.action_bass_mm == 1.8 and store.custom.radius_in == 9.5
    assert store.custom.pickups == FENDER_STYLE.pickups
    path.write_text("[1, 2", encoding="utf-8")
    assert CalibrationStore(path).step == 1


# ------------------------------------------------------------------ presets


def test_the_preset_row_offers_the_three_styles_and_remembers_the_choice(qtbot, tmp_path):
    path = tmp_path / "calibration.json"
    screen, _ = make(qtbot, CalibrationStore(path))
    assert [screen.preset_combo.itemText(i) for i in range(3)] == [
        "Estilo Fender (simple)", "Estilo Gibson (humbucker)", "Personalizado"]
    assert screen.relief.target_spin.value() == pytest.approx(0.25)
    screen.preset_combo.setCurrentIndex(1)
    assert screen.relief.target_spin.value() == pytest.approx(0.30)
    assert screen.action.radius_spin.value() == pytest.approx(12)
    assert CalibrationStore(path).preset == "Estilo Gibson (humbucker)"
    again, _ = make(qtbot, CalibrationStore(path))
    assert again.preset_combo.currentText() == "Estilo Gibson (humbucker)"
    assert again.relief.target_spin.value() == pytest.approx(0.30)


def test_editing_a_target_moves_to_personalizado_with_those_values_and_remembers_them(qtbot, tmp_path):
    path = tmp_path / "calibration.json"
    screen, _ = make(qtbot, CalibrationStore(path))
    screen.relief.target_spin.setValue(0.40)
    assert screen.preset_combo.currentText() == "Personalizado"
    assert screen.action.bass_target_spin.value() == pytest.approx(FENDER_STYLE.action_bass_mm)  # the rest is kept
    screen.preset_combo.setCurrentIndex(1)  # a built-in again: Gibson values
    assert screen.relief.target_spin.value() == pytest.approx(0.30)
    screen.preset_combo.setCurrentIndex(2)  # the user's own values come back
    assert screen.relief.target_spin.value() == pytest.approx(0.40)
    reloaded = CalibrationStore(path)
    assert reloaded.preset == "Personalizado" and reloaded.current().relief_mm == pytest.approx(0.40)


# ------------------------------------------------------------------ step 1: relief


def test_the_relief_panel_explains_the_method_and_the_safety_rule(qtbot):
    screen, _ = make(qtbot)
    panel = screen.relief
    assert panel.method_text() == ("Ponga una cejilla en el traste 1, pise la cuerda 6 en el traste donde el mástil "
                                   "se une al cuerpo y mida con una galga la luz entre la cuerda y el traste 7 u 8.")
    assert panel.safety_text() == "Si la tuerca del alma no gira con facilidad, no la fuerce: consulte a un luthier."
    assert (panel.measured_spin.minimum(), panel.measured_spin.maximum(), panel.measured_spin.singleStep()) == (
        pytest.approx(-0.01), 2.0, 0.01)
    assert panel.measured_value() is None and panel.neck_view.turn() is None
    assert panel.advice_text() == "Ingrese la luz medida en milímetros."


@pytest.mark.parametrize("measured,turn,text", [
    (0.50, "clockwise", "Hay 0,25 mm de más: apriete la tuerca del alma (sentido horario), como máximo 1/8 de vuelta; "
                        "afine y espere unos minutos antes de medir de nuevo."),
    (0.05, "counterclockwise", "Faltan 0,20 mm: afloje la tuerca del alma (sentido antihorario), como máximo 1/8 de "
                               "vuelta; afine y espere unos minutos antes de medir de nuevo."),
    (0.27, None, "Curvatura correcta: 0,27 mm (objetivo 0,25 mm)."),
])
def test_the_relief_advice_and_the_nut_turn_follow_the_measure(qtbot, measured, turn, text):
    screen, _ = make(qtbot)
    screen.relief.measured_spin.setValue(measured)
    assert screen.relief.advice_text() == text
    assert screen.relief.neck_view.turn() == turn
    assert screen.relief.neck_view.bow_mm == pytest.approx(measured)
    assert screen.relief.neck_view.target_mm == pytest.approx(0.25)


def test_a_zero_relief_is_a_measure_not_an_empty_field(qtbot):
    screen, _ = make(qtbot)
    screen.relief.measured_spin.setValue(0.0)
    assert screen.relief.measured_value() == 0.0 and screen.relief.neck_view.turn() == "counterclockwise"
    screen.relief.measured_spin.setValue(screen.relief.measured_spin.minimum())
    assert screen.relief.measured_value() is None and screen.relief.neck_view.turn() is None


def test_changing_the_target_recomputes_the_relief_advice(qtbot):
    screen, _ = make(qtbot)
    screen.relief.measured_spin.setValue(0.50)
    screen.relief.target_spin.setValue(0.50)
    assert screen.relief.neck_view.turn() is None and screen.relief.advice_text().startswith("Curvatura correcta")


# ------------------------------------------------------------------ step 2: action


def test_the_action_panel_explains_the_method_and_needs_strings_6_and_1(qtbot):
    screen, _ = make(qtbot)
    panel = screen.action
    assert panel.method_text() == ("Mida en el traste 12, desde el borde superior del traste hasta la parte inferior "
                                   "de la cuerda. Las cuerdas 6 y 1 son necesarias; las demás son opcionales.")
    assert sorted(panel.spins) == [1, 2, 3, 4, 5, 6]
    assert panel.radius_spin.value() == pytest.approx(9.5)
    assert all(panel.advice_text(n) == "" and panel.saddles.arrow(n) is None for n in range(1, 7))
    assert panel.rule_text() == "La selleta se mueve unas 2 veces el error medido en el traste 12."


def test_each_measured_string_gets_advice_with_the_2x_rule_and_an_arrow(qtbot):
    screen, _ = make(qtbot)
    panel = screen.action
    panel.spins[6].setValue(2.4)   # target 1.8 -> 0.6 too high
    panel.spins[1].setValue(1.0)   # target 1.6 -> 0.6 too low
    panel.spins[3].setValue(1.7)   # interpolated target 1.68 -> ok
    assert panel.advice_text(6) == "Baje la selleta unos 1,20 mm (2 × 0,60)."
    assert panel.advice_text(1) == "Suba la selleta unos 1,20 mm (2 × 0,60)."
    assert panel.advice_text(3) == "En objetivo (1,68 mm)."
    assert [panel.saddles.arrow(n) for n in (6, 1, 3, 4)] == ["lower", "raise", "ok", None]
    assert panel.advice_text(4) == ""  # not measured: no advice


def test_the_saddle_arc_text_and_drawing_follow_the_radius(qtbot):
    screen, _ = make(qtbot)
    panel = screen.action
    assert panel.arc_text() == ('Perfil de selletas para radio 9,5": cuerdas 4 y 3 +1,35 mm, '
                                'cuerdas 5 y 2 +0,90 mm respecto de 6 y 1')
    assert panel.saddles.profile(4) == pytest.approx(1.35, abs=0.01) and panel.saddles.profile(6) == 0.0
    panel.radius_spin.setValue(12)
    assert panel.arc_text().startswith('Perfil de selletas para radio 12": cuerdas 4 y 3 +')
    assert panel.saddles.profile(4) < 1.35
    assert screen.preset_combo.currentText() == "Personalizado"


# ------------------------------------------------------------------ step 3: pickups


def test_the_pickup_positions_come_from_the_preset_and_the_target_from_its_type(qtbot):
    screen, _ = make(qtbot)
    panel = screen.pickups
    assert [panel.position_combo.itemText(i) for i in range(panel.position_combo.count())] == [
        "Mástil", "Medio", "Puente"]
    assert (panel.bass_target_spin.value(), panel.treble_target_spin.value()) == (pytest.approx(3.2), pytest.approx(2.4))
    screen.preset_combo.setCurrentIndex(1)
    assert [panel.position_combo.itemText(i) for i in range(panel.position_combo.count())] == ["Mástil", "Puente"]
    assert (panel.bass_target_spin.value(), panel.treble_target_spin.value()) == (pytest.approx(2.4), pytest.approx(1.6))


def test_pickup_advice_and_arrows_per_side(qtbot):
    screen, _ = make(qtbot)
    panel = screen.pickups
    assert panel.advice_text("bass") == "" and panel.view.arrow("bass") is None
    panel.bass_spin.setValue(4.0)    # target 3.2: too close
    panel.treble_spin.setValue(1.5)  # target 2.4: too far... measured lower than target: raise
    assert panel.advice_text("bass") == "Lado graves: baje la pastilla (mide 4,0 mm, objetivo 3,2 mm)."
    assert panel.advice_text("treble") == "Lado agudos: suba la pastilla (mide 1,5 mm, objetivo 2,4 mm)."
    assert (panel.view.arrow("bass"), panel.view.arrow("treble")) == ("lower", "raise")
    panel.treble_spin.setValue(2.4)
    assert panel.advice_text("treble") == "Lado agudos: en objetivo (2,4 mm)." and panel.view.arrow("treble") == "ok"


def test_a_pickup_target_edit_is_a_custom_value(qtbot):
    screen, _ = make(qtbot)
    screen.pickups.bass_target_spin.setValue(2.8)
    assert screen.preset_combo.currentText() == "Personalizado"
    assert screen.calibration.current().target_for("neck").bass_mm == pytest.approx(2.8)
    assert screen.calibration.current().target_for("neck").treble_mm == pytest.approx(2.4)


def run_balance(audio, screen, peaks, rounds=3, position_index=None):
    """Press «Medir balance» and play every round: ``peaks`` is the amplitude of each string."""
    screen.pickups.balance_button.click()
    for _ in range(rounds):
        for number in (6, 5, 4, 3, 2, 1):
            ring(audio, OPEN[number], peak=peaks[number], seed=number)


def test_the_balance_rounds_ask_for_each_string_and_chart_the_levels(qtbot):
    screen, audio = make(qtbot, rounds=3)
    screen.go_to_step(3)
    panel = screen.pickups
    panel.balance_button.click()
    assert panel.instruction_text() == "Ronda 1 de 3 · Toque la cuerda 6 al aire"
    ring(audio, OPEN[6], peak=0.5)
    assert panel.instruction_text() == "Ronda 1 de 3 · Toque la cuerda 5 al aire"
    for number in (5, 4, 3, 2, 1):
        ring(audio, OPEN[number], peak=0.5 if number > 3 else 0.25, seed=number)
    assert panel.instruction_text() == "Ronda 2 de 3 · Toque la cuerda 6 al aire"
    assert sorted(panel.levels.levels) == [1, 2, 3, 4, 5, 6]


def test_a_finished_balance_gives_relative_levels_spread_and_the_bass_vs_treble_advice(qtbot):
    screen, audio = make(qtbot, rounds=3)
    screen.go_to_step(3)
    peaks = {6: 0.5, 5: 0.5, 4: 0.5, 3: 0.25, 2: 0.25, 1: 0.25}  # the treble side 6 dB under the bass side
    run_balance(audio, screen, peaks)
    panel = screen.pickups
    values = panel.chart.values()
    assert sorted(values) == [1, 2, 3, 4, 5, 6]
    assert all(values[n][0] == pytest.approx(3.0, abs=1.0) for n in (6, 5, 4))
    assert all(values[n][0] == pytest.approx(-3.0, abs=1.0) for n in (3, 2, 1))
    assert all(values[n][1] is not None and values[n][1] < 1.0 for n in values)  # three rounds: an SD exists
    assert panel.balance_text().startswith("Los graves suenan ") and panel.balance_text().endswith(
        "dB más que los agudos: baje la pastilla del lado graves o suba la del lado agudos.")
    assert panel.instruction_text() == ""
    assert panel.balance_button.text() == "Medir balance"


def test_a_balanced_pickup_says_so(qtbot):
    screen, audio = make(qtbot, rounds=3)
    screen.go_to_step(3)
    run_balance(audio, screen, {n: 0.4 for n in OPEN})
    assert screen.pickups.balance_text().startswith("Balance entre graves y agudos correcto (")


def test_a_note_that_is_not_the_asked_string_is_refused_and_not_counted(qtbot):
    screen, audio = make(qtbot, rounds=3)
    screen.go_to_step(3)
    panel = screen.pickups
    panel.balance_button.click()
    ring(audio, OPEN[3])  # asked for string 6
    assert panel.message_text() == "Esa nota no es la cuerda 6 al aire: toque la cuerda 6 sin pisar."
    assert panel.levels.levels == {} and panel.instruction_text() == "Ronda 1 de 3 · Toque la cuerda 6 al aire"
    ring(audio, OPEN[6])
    assert panel.message_text() == "" and sorted(panel.levels.levels) == [6]


def test_two_measured_positions_are_compared(qtbot):
    screen, audio = make(qtbot, rounds=3)
    screen.go_to_step(3)
    panel = screen.pickups
    loud = {n: 0.5 for n in OPEN}
    quiet = {n: 0.25 for n in OPEN}  # 6 dB under
    run_balance(audio, screen, loud)
    assert panel.positions_text() == ""  # one position: nothing to compare
    panel.position_combo.setCurrentIndex(2)  # bridge
    run_balance(audio, screen, quiet)
    text = panel.positions_text()
    assert text.startswith("Posiciones, respecto de la más fuerte: Mástil +0,0 dB · Puente −")
    assert text.endswith("Suena más bajo en: puente; suba esa pastilla.")


def test_the_magnetic_pull_check_is_quiet_for_a_clean_note(qtbot):
    screen, audio = make(qtbot)
    screen.go_to_step(3)
    panel = screen.pickups
    panel.magnet_button.click()
    assert panel.instruction_text() == "Pise la cuerda 6 en el traste 15 y déjela sonar"
    audio.push(pluck(OPEN[6] * 2 ** (15 / 12), 2.5, seed=1)[0])
    audio.push(silence(0.5))
    assert panel.magnetic_text() == "Sin ondulación apreciable."
    assert panel.instruction_text() == ""


def test_the_magnetic_pull_check_warns_when_the_note_wobbles(qtbot):
    screen, audio = make(qtbot)
    screen.go_to_step(3)
    panel = screen.pickups
    panel.magnet_button.click()
    audio.push(modulated(OPEN[6], 3.0, 4.0))
    audio.push(silence(0.5))
    text = panel.magnetic_text()
    assert text.startswith("La nota ondula ") and text.endswith(
        " cents: la pastilla puede estar demasiado cerca; baje el lado graves.")
    assert panel.instruction_text() == ""


def test_the_pickup_audio_helpers_need_an_input(qtbot):
    audio = FakeAudio()
    root = BackdropRoot()
    qtbot.addWidget(root)
    screen = IntonationScreen(root, devices=lambda: [], audio=audio, store=IntonationStore(),
                              calibration=CalibrationStore())
    screen.open_screen()
    assert not screen.pickups.balance_button.isEnabled() and not screen.pickups.magnet_button.isEnabled()
    assert screen.relief.measured_spin.isEnabled() and screen.action.spins[6].isEnabled()


# ------------------------------------------------------------------ step 4 and the other steps do not mix


def test_step_4_still_runs_the_intonation_rounds(qtbot):
    screen, audio = make(qtbot, rounds=3)
    screen.go_to_step(4)
    assert screen.session.string == 6 and screen.session.step is Step.OPEN
    for _ in range(3):
        play_round(audio, 0.0)
    assert screen.session.results[6].offset == pytest.approx(0.0, abs=0.8)
    assert screen.chip_state(6) == "ok"


def test_notes_played_in_the_other_steps_never_feed_the_intonation_session(qtbot):
    screen, audio = make(qtbot, rounds=3)
    for step in (1, 2, 3):
        screen.go_to_step(step)
        play_round(audio, 0.0)
    assert screen.session.results == {} and screen.session.step is Step.OPEN and screen.session.progress == 0


def test_the_unsure_mark_on_the_bridge_is_big_and_off_the_string_line():
    from jmc_guitar_zoom.ui.intonation import BridgeView
    assert BridgeView.UNSURE_RADIUS >= 14
    # the mark is centred beside the string, not on it: its ring clears the string line (3 px wide at most)
    assert BridgeView.UNSURE_DX >= BridgeView.UNSURE_RADIUS + 3


# ------------------------------------------------------------------ the entry points


@pytest.fixture
def fakes(monkeypatch):
    audio = FakeAudio()
    monkeypatch.setattr(intonation_module, "list_input_devices", lambda: list(DEVICES))
    monkeypatch.setattr(intonation_module, "AudioInput", lambda parent=None: audio)
    return audio


def test_the_entry_points_are_named_calibracion_and_key_o_still_opens_it(qtbot, catalog, fakes):
    w = MainWindow(catalog)
    qtbot.addWidget(w)
    assert w.intonation_button.accessibleName() == "Calibración"
    assert w.intonation_button.toolTip() == "Calibración: curvatura, acción, pastillas y octavación (O)"
    assert w.intonation_action.text().startswith("Calibración…")
    assert w.intonation_shortcut.key().toString() == "O"
    w.intonation_shortcut.activated.emit()
    assert w.intonation_panel.isVisibleTo(w) and w.intonation_panel.step == 1
    w.intonation_shortcut.activated.emit()
    assert not w.intonation_panel.isVisibleTo(w)
