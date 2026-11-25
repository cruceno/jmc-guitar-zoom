"""Skip the tests marked ``zoom_files`` when the files from ``scripts/fetch_test_fixtures.py`` are not there."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # before anything imports PySide6: never open a real window

import pytest

from fixture_files import ZOOM_FILES, have_zoom_files


def pytest_collection_modifyitems(config, items):
    if have_zoom_files():
        return
    skip = pytest.mark.skip(reason=f"Zoom's files are not downloaded: run scripts/fetch_test_fixtures.py ({ZOOM_FILES})")
    for item in items:
        if "zoom_files" in item.keywords:
            item.add_marker(skip)
