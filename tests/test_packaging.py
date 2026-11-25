"""Fast checks on the packaging files; they need no build."""

import re
from pathlib import Path

import pytest

from jmc_guitar_zoom import __version__

ROOT = Path(__file__).resolve().parents[1]
SPEC = (ROOT / "packaging" / "jmc-guitar-zoom.spec").read_text(encoding="utf-8")
ISS = (ROOT / "packaging" / "windows" / "jmc-guitar-zoom.iss").read_text(encoding="utf-8")
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release.yml"
WORKFLOW = WORKFLOW_PATH.read_text(encoding="utf-8")
APPIMAGE_SCRIPT = (ROOT / "packaging" / "linux" / "build_appimage.sh").read_text(encoding="utf-8")


def _data_reads() -> list[Path]:
    """Every file the package reads next to its own modules via ``Path(__file__)``."""
    found = []
    for module in (ROOT / "jmc_guitar_zoom").rglob("*.py"):
        text = module.read_text(encoding="utf-8")
        for name in re.findall(r"with_name\(\"([^\"]+)\"\)", text):
            found.append(module.with_name(name))
    return found


def test_the_package_reads_some_data_files():
    assert {p.name for p in _data_reads()} >= {"descriptions_es.json", "template.zptc", "empty.zptc"}


@pytest.mark.parametrize("path", _data_reads(), ids=lambda p: p.name)
def test_every_data_file_the_package_reads_exists_and_is_bundled(path):
    assert path.exists()
    rel = path.relative_to(ROOT).as_posix()
    assert rel in SPEC, f"{rel} is not named in the PyInstaller spec"


def test_the_design_folder_the_ui_reads_is_bundled_and_has_the_app_icon():
    assert "jmc_guitar_zoom/ui/design" in SPEC
    assert (ROOT / "jmc_guitar_zoom" / "ui" / "design" / "app-icon.svg").is_file()
    for name in ("app-icon.png", "app-icon.ico"):
        assert (ROOT / "packaging" / "icons" / name).is_file()


@pytest.mark.parametrize("name", ["LICENSE", "NOTICE.md", "THIRD_PARTY_NOTICES.md"])
def test_the_notices_are_bundled(name):
    assert (ROOT / name).is_file()
    assert name in SPEC


def test_the_spec_names_the_hidden_imports_of_the_midi_backend():
    for module in ("mido.backends.rtmidi", "rtmidi"):
        assert f'"{module}"' in SPEC


def test_the_spec_keeps_qtsvg():
    excludes = SPEC.split("EXCLUDES", 1)[1].split("]", 1)[0]
    assert '"QtSvg"' not in excludes
    assert '"QtNetwork"' not in excludes  # the library updater's module imports it


def test_the_installer_and_the_workflow_agree_on_the_artifact_names():
    assert "JMC_Guitar_Zoom-{#AppVersion}-Setup" in ISS
    assert "JMC_Guitar_Zoom-*-Setup.exe" in WORKFLOW
    assert "JMC_Guitar_Zoom-${VERSION}-x86_64.AppImage" in APPIMAGE_SCRIPT
    assert "JMC_Guitar_Zoom-*-x86_64.AppImage" in WORKFLOW
    assert "/DAppVersion=" in WORKFLOW
    assert "dist/jmc-guitar-zoom" in WORKFLOW.replace("\\", "/")


def test_the_installer_is_per_user_by_default_and_has_a_fixed_app_id():
    assert "PrivilegesRequired=lowest" in ISS
    assert "PrivilegesRequiredOverridesAllowed=dialog" in ISS
    assert re.search(r"AppId=\{\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}", ISS)
    assert "LicenseFile=" in ISS


def _job(name: str) -> str:
    """The text of one top-level job of the workflow (the workflow has no YAML parser dependency to test with)."""
    body = WORKFLOW.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  (\w+):\n", body)
    return dict(zip(parts[1::2], parts[2::2]))[name]


def test_the_workflow_has_the_three_triggers_and_the_three_jobs():
    head = WORKFLOW.split("\njobs:\n", 1)[0]
    for trigger in ("push:", "pull_request:", "workflow_dispatch:"):
        assert re.search(rf"(?m)^  {trigger}", head)
    assert re.search(r"tags:\s*\n\s*- 'v\*'", head)
    jobs = re.findall(r"(?m)^  (\w+):\n", WORKFLOW.split("\njobs:\n", 1)[1])
    assert jobs == ["linux", "windows", "release"]
    assert re.search(r"(?m)^permissions:\n  contents: read$", head)
    release = _job("release")
    assert "needs: [linux, windows]" in release
    assert "if: startsWith(github.ref, 'refs/tags/v')" in release
    assert "contents: write" in release
    assert "contents: write" not in _job("linux") + _job("windows")
    assert "runs-on: ubuntu-22.04" in _job("linux")
    assert "runs-on: windows-latest" in _job("windows")


def test_every_action_is_pinned_to_a_major_version():
    uses = re.findall(r"uses:\s*(\S+)", WORKFLOW)
    assert uses
    assert all(re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+", u) for u in uses), uses


def test_appimagetool_is_pinned_with_a_sha256():
    assert re.search(r"APPIMAGETOOL_URL=\"https://github.com/AppImage/appimagetool/releases/download/\d+\.\d+\.\d+/", APPIMAGE_SCRIPT)
    assert re.search(r"APPIMAGETOOL_SHA256=\"[0-9a-f]{64}\"", APPIMAGE_SCRIPT)
    assert "sha256sum" in APPIMAGE_SCRIPT


def test_the_tag_check_compares_against_the_app_version():
    assert "jmc_guitar_zoom.__version__" in WORKFLOW
    assert __version__ in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
