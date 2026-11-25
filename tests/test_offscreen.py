def test_the_suite_runs_on_the_offscreen_platform(qapp):
    from PySide6.QtGui import QGuiApplication

    assert QGuiApplication.platformName() == "offscreen"
