import mido
import pytest

from jmc_guitar_zoom import __version__
from jmc_guitar_zoom.__main__ import build_parser, main


def test_self_check_prints_the_report_and_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(mido, "get_output_names", lambda: ["Zoom A1 FOUR MIDI 1"])
    assert main(["--self-check"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"jmc-guitar-zoom {__version__}"
    assert out[1].startswith("data folder: ")
    assert int(out[2].rsplit(": ", 1)[1]) >= 1
    assert out[3].startswith("MIDI backend: rtmidi (") and out[3] != "MIDI backend: rtmidi ()"
    assert out[4] == "MIDI outputs: Zoom A1 FOUR MIDI 1"
    assert out[5].startswith("Guitar Lab: ")


def test_self_check_fails_with_an_error_line_when_midi_does_not_load(monkeypatch, capsys):
    import rtmidi

    def boom():
        raise ImportError("no rtmidi")

    monkeypatch.setattr(rtmidi, "get_compiled_api", boom)  # the bundled backend itself is broken
    assert main(["--self-check"]) == 1
    captured = capsys.readouterr()
    assert "self-check failed" in captured.err and "no rtmidi" in captured.err
    assert captured.out == ""


def test_self_check_flag_is_hidden_from_help(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--help"])
    assert "--self-check" not in capsys.readouterr().out


def test_self_check_with_a_path_also_writes_the_same_report_to_that_file(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(mido, "get_output_names", lambda: ["Zoom A1 FOUR MIDI 1"])
    report = tmp_path / "report.txt"
    assert main(["--self-check", str(report)]) == 0
    out = capsys.readouterr().out
    assert report.read_text(encoding="utf-8") == out
    assert out.splitlines()[0] == f"jmc-guitar-zoom {__version__}"


def test_self_check_failure_is_also_written_to_the_report_file(monkeypatch, capsys, tmp_path):
    import rtmidi

    def boom():
        raise ImportError("no rtmidi")

    monkeypatch.setattr(rtmidi, "get_compiled_api", boom)
    report = tmp_path / "report.txt"
    assert main(["--self-check", str(report)]) == 1
    assert "self-check failed: ImportError: no rtmidi" in report.read_text(encoding="utf-8")
    assert "self-check failed" in capsys.readouterr().err


def test_self_check_flag_without_a_path_does_not_swallow_the_next_option(monkeypatch, capsys):
    monkeypatch.setattr(mido, "get_output_names", lambda: [])
    assert build_parser().parse_args(["--self-check", "--no-connect"]).no_connect is True


def test_self_check_fails_when_rtmidi_has_no_compiled_api(monkeypatch, capsys):
    import rtmidi

    monkeypatch.setattr(rtmidi, "get_compiled_api", lambda: [])
    assert main(["--self-check"]) == 1
    assert "no compiled MIDI API" in capsys.readouterr().err


def test_a_machine_without_midi_is_reported_but_does_not_fail_the_check(monkeypatch, capsys):
    # GitHub's Linux runners have no /dev/snd/seq: the bundle is fine, the system just has no MIDI service
    def no_sequencer():
        raise SystemError("MidiInAlsa::initialize: error creating ALSA sequencer client object.")

    monkeypatch.setattr(mido, "get_output_names", no_sequencer)
    assert main(["--self-check"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[3].startswith("MIDI backend: rtmidi (")
    assert out[4] == "MIDI outputs: unavailable (SystemError: MidiInAlsa::initialize: error creating ALSA sequencer client object.)"
