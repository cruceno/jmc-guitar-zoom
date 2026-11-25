"""Keep the app's own effect library current from Zoom's public Guitar Lab channel. No Qt here.

The channel is three public files under ``https://www.zoom.co.jp/archive/GUITAR_LAB/``: ``AllZDL7_2.lst`` (per
model, the effects with ``type``, ``fileName`` and ``version``), ``ModelVersion7_2.lst`` (the current firmware per
model) and ``ZDLF3/<fileName>`` (a zip with the effect's ``.ZD2``). Both lists are JSON followed by garbage.

Everything fetched is untrusted. URLs are built only from the channel base and a validated file name; a zip is
read in memory with a size limit, only one ``.ZD2`` member is taken and its path is ignored, its bytes are parsed
and must carry the id and version the list announced, and the file is published atomically under a new name,
never over an existing file. The library keeps the names Guitar Lab's cache uses, ``<STEM>_<VVV>.zd2``, so the
catalog and ``flst.pedal_filename`` work on it unchanged.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping

from zoomstudio.effects.models import parse_models
from zoomstudio.effects.catalog import EffectInfo, load_catalog, load_zd2

BASE_URL = "https://www.zoom.co.jp/archive/GUITAR_LAB/"
EFFECTS_LIST_NAME = "AllZDL7_2.lst"
VERSIONS_LIST_NAME = "ModelVersion7_2.lst"
EFFECTS_LIST_URL = BASE_URL + EFFECTS_LIST_NAME
VERSIONS_LIST_URL = BASE_URL + VERSIONS_LIST_NAME
ZIP_BASE_URL = BASE_URL + "ZDLF3/"
USER_AGENT = "ZoomStudio"
TIMEOUT_SECONDS = 15
MAX_LIST_BYTES = 4_000_000  # the real effects list is about 0.5 MB
MAX_ZIP_BYTES = 2_000_000  # real zips are about 20 KB
MAX_ZD2_BYTES = 1_000_000  # real effect files are 13 to 50 KB

_FILE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}\.zip$")
_VERSION = re.compile(r"^[0-9]\.[0-9]{2}$")
_NUMBERS = re.compile(r"[0-9]+")  # ASCII digits only: \d also matches other scripts

Fetcher = Callable[[str, int], bytes]  # (url, max bytes) -> body; raises FetchError


class UpdateError(Exception):
    """The channel could not be read or its answer is not what the format says."""


class FetchError(UpdateError):
    """One request failed. ``code`` is ``network`` or ``too_large``."""

    def __init__(self, message: str, code: str = "network") -> None:
        super().__init__(message)
        self.code = code


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in _NUMBERS.findall(version))


def valid_file_name(name: object) -> bool:
    return isinstance(name, str) and _FILE_NAME.fullmatch(name) is not None and ".." not in name


def zip_url(file_name: str) -> str:
    """The URL of an effect zip. Only a plain ``NAME.zip`` is accepted: no slash, no ``..``, no scheme."""
    if not valid_file_name(file_name):
        raise UpdateError(f"invalid file name: {file_name!r}")
    return ZIP_BASE_URL + file_name


# ---------------------------------------------------------------- fetching


def _build_opener():
    """An opener with no cookie jar and no proxy credentials; a redirect may not leave the channel."""

    class Guard(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not within_channel(newurl):
                raise urllib.error.URLError(f"redirect outside the channel: {newurl}")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return urllib.request.build_opener(Guard())


def within_channel(url: str) -> bool:
    """True when ``url`` is https on the channel host and its decoded, normalised path stays under the base.

    A plain prefix test let ``…/GUITAR_LAB/../../other`` through (the server resolves the dots)."""
    base = urllib.parse.urlsplit(BASE_URL)
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.netloc != base.netloc:
        return False
    path = urllib.parse.unquote(parts.path)
    if any(segment in (".", "..") for segment in path.split("/")):
        return False
    return posixpath.normpath(path).startswith(base.path.rstrip("/") + "/") and path.startswith(base.path)


def urllib_fetcher(url: str, max_bytes: int) -> bytes:
    """HTTPS GET of a channel URL: a timeout, a generic User-Agent, nothing else sent, a hard size limit."""
    if not within_channel(url):
        raise FetchError(f"refused: outside the Guitar Lab channel: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with _build_opener().open(request, timeout=TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise FetchError(f"HTTP {status}")
            body = response.read(max_bytes + 1)
    except FetchError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:  # includes timeouts, TLS and DNS failures
        raise FetchError(str(exc)) from exc
    if len(body) > max_bytes:
        raise FetchError("the answer is larger than allowed", code="too_large")
    return body


# ---------------------------------------------------------------- parsing


@dataclass(frozen=True)
class RemoteEffect:
    effect_id: int
    file_name: str
    version: str


def _document(data: bytes) -> dict:
    """The JSON object at the start of a list; whatever follows it is ignored."""
    text = data.decode("utf-8", errors="replace").lstrip("﻿ \t\r\n")
    try:
        doc, _ = json.JSONDecoder().raw_decode(text)
    except ValueError as exc:
        raise UpdateError("the list is not JSON") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("models"), list):
        raise UpdateError("the list has no models")
    return doc


def _hex(value: object) -> int | None:
    try:
        return int(str(value), 16)
    except ValueError:
        return None


def parse_effect_list(data: bytes) -> dict[int, list[RemoteEffect]]:
    """Model id -> its effects. An entry with an unusable ``type``, ``fileName`` or ``version`` is left out."""
    return _parse_effects(data)[0]


def _parse_effects(data: bytes) -> tuple[dict[int, list[RemoteEffect]], int]:
    found: dict[int, list[RemoteEffect]] = {}
    skipped = 0
    for model in _document(data)["models"]:
        model_id = _hex(model.get("modelId")) if isinstance(model, dict) else None
        if model_id is None:
            continue
        entries = found.setdefault(model_id, [])
        for item in model.get("effects") or []:
            effect_id = _hex(item.get("type")) if isinstance(item, dict) else None
            name, version = (item.get("fileName"), item.get("version")) if isinstance(item, dict) else (None, None)
            if effect_id is None or not valid_file_name(name) or not isinstance(version, str) \
                    or not version_key(version):
                skipped += 1
                continue
            entries.append(RemoteEffect(effect_id, name, version))
    return found, skipped


def parse_version_list(data: bytes) -> dict[int, str]:
    """Model id -> the firmware version Zoom publishes."""
    return {mid: version for mid, (version, _flag) in _parse_versions(data).items()}


def _parse_versions(data: bytes) -> dict[int, tuple[str, bool]]:
    """Model id -> (published firmware version, ``update`` flag). Guitar Lab offers a firmware update from the flag."""
    out: dict[int, tuple[str, bool]] = {}
    for model in _document(data)["models"]:
        model_id = _hex(model.get("modelId")) if isinstance(model, dict) else None
        version = model.get("modelVersion") if isinstance(model, dict) else None
        if model_id is not None and isinstance(version, str) and version_key(version):
            out[model_id] = (version, model.get("update") is True)
    return out


# ---------------------------------------------------------------- results


@dataclass(frozen=True)
class EffectUpdate:
    """An effect the library lacks (``new``) or has in an older version (``updated``)."""

    effect_id: int
    file_name: str  # the zip name on the channel
    version: str
    kind: str  # "new" | "updated"
    name: str
    group: str  # known only for effects the library already has
    local_version: str | None
    size: int | None = None  # bytes of the newest local file, when there is one


@dataclass(frozen=True)
class FirmwareStatus:
    model_id: int
    remote: str
    current: str | None  # the connected pedal's version (None: unknown)
    newer: bool  # an update is on offer: the published version is greater than the pedal's, or the channel says so
    update: bool = False  # the channel's own ``update`` flag for this model


@dataclass
class CheckResult:
    new: list[EffectUpdate] = field(default_factory=list)
    updated: list[EffectUpdate] = field(default_factory=list)
    current: list[EffectUpdate] = field(default_factory=list)  # up to date: kind "current"
    firmware: FirmwareStatus | None = None
    firmware_versions: dict[int, str] = field(default_factory=dict)  # every model's published firmware
    firmware_updates: set[int] = field(default_factory=set)  # models whose ``update`` flag is set
    skipped: int = 0  # list entries that could not be used

    @property
    def pending(self) -> list[EffectUpdate]:
        return self.new + self.updated


@dataclass(frozen=True)
class DownloadResult:
    entry: EffectUpdate
    ok: bool
    reason: str | None = None  # a code: bad_name, bad_version, network, too_large, bad_zip, no_zd2, many_zd2,
    #                           oversized, bad_zd2, id_mismatch, version_mismatch, exists, write_failed
    path: Path | None = None


@dataclass
class DownloadReport:
    results: list[DownloadResult] = field(default_factory=list)
    cancelled: bool = False

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)


# ---------------------------------------------------------------- files


def _publish(temp: Path, final: Path) -> bool:
    """Give ``temp`` its final name without ever replacing a file: False when ``final`` already exists."""
    try:
        os.link(temp, final)  # fails if the target exists, and the content appears whole
    except FileExistsError:
        return False
    except OSError:  # a file system without hard links: the check-then-rename gap is the best left
        if final.exists():
            return False
        os.rename(temp, final)
        return True
    temp.unlink(missing_ok=True)
    return True


def _write_atomic(path: Path, data: bytes) -> None:
    """Replace a small file (a saved list) in one step."""
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def library_name(file_name: str, version: str) -> str:
    """``ANDLY_3S.zip`` + ``1.10`` -> ``ANDLY_3S_110.zd2`` (Guitar Lab's cache naming)."""
    return f"{file_name[:-4]}_{version.replace('.', '')}.zd2"


def _extract_zd2(data: bytes) -> bytes:
    """The bytes of the one ``.ZD2`` member. Raises ``_Refused`` with the reason code."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            members = [m for m in archive.infolist()
                       if not m.is_dir() and PurePosixPath(m.filename.replace("\\", "/")).name.lower().endswith(".zd2")]
            if not members:
                raise _Refused("no_zd2")
            if len(members) > 1:
                raise _Refused("many_zd2")
            member = members[0]
            if member.file_size > MAX_ZD2_BYTES:
                raise _Refused("oversized")
            with archive.open(member) as stream:
                body = stream.read(MAX_ZD2_BYTES + 1)  # the header may lie about the size
    except _Refused:
        raise
    except Exception as exc:  # noqa: BLE001 - BadZipFile, zlib.error, encrypted or unsupported members: damaged
        raise _Refused("bad_zip") from exc
    if len(body) > MAX_ZD2_BYTES:
        raise _Refused("oversized")
    return body


class _Refused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------- the updater


class LibraryUpdater:
    """Checks the channel against the local effects and downloads what is missing into ``library_dir``."""

    def __init__(self, library_dir: Path, fetcher: Fetcher | None = None,
                 extra_dirs: Iterable[Path] = ()) -> None:
        self.library_dir = Path(library_dir)
        self.fetcher: Fetcher = fetcher or urllib_fetcher
        self.extra_dirs = [Path(d) for d in extra_dirs]  # other folders whose effects count as already held

    def local_catalog(self) -> dict[int, EffectInfo]:
        """The effects held now, by id with the newest version, from the library and the extra folders."""
        folders = [p for p in [self.library_dir, *self.extra_dirs] if p.is_dir()]
        return load_catalog(*folders) if folders else {}

    def _get(self, url: str, limit: int) -> bytes:
        try:
            return self.fetcher(url, limit)
        except FetchError:
            raise
        except UpdateError:
            raise
        except Exception as exc:  # noqa: BLE001 - an injected fetcher may raise anything
            raise FetchError(str(exc)) from exc

    def check(self, model_id: int | None = None, all_models: bool = False, firmware: str | None = None,
              local: Mapping[int, EffectInfo] | None = None) -> CheckResult:
        """Download the two lists and compare them with the local effects.

        ``model_id``: the pedal to look at (new effects are the ones it can run). ``all_models``: every model.
        ``firmware``: the connected pedal's version, for the firmware status. The lists are saved into the
        library only after both parsed; nothing else is written."""
        try:
            effects_raw = self._get(EFFECTS_LIST_URL, MAX_LIST_BYTES)
            versions_raw = self._get(VERSIONS_LIST_URL, MAX_LIST_BYTES)
            remote, skipped = _parse_effects(effects_raw)
            firmware_info = _parse_versions(versions_raw)
        except UpdateError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UpdateError(str(exc)) from exc
        if not parse_models(effects_raw):  # the app's own reader must take the list before it is saved
            raise UpdateError("la lista de efectos no tiene ningún modelo utilizable")
        self._save_lists(effects_raw, versions_raw)

        held = dict(local) if local is not None else self.local_catalog()
        wanted: dict[int, RemoteEffect] = {}
        for mid, entries in remote.items():
            if not all_models and mid != model_id:
                continue
            for item in entries:
                best = wanted.get(item.effect_id)
                if best is None or version_key(item.version) > version_key(best.version):
                    wanted[item.effect_id] = item
        result = CheckResult(skipped=skipped, firmware_versions={m: v for m, (v, _f) in firmware_info.items()},
                             firmware_updates={m for m, (_v, flag) in firmware_info.items() if flag})
        for item in sorted(wanted.values(), key=lambda e: (e.file_name.lower(), e.effect_id)):
            have = held.get(item.effect_id)
            stem = item.file_name[:-4]
            if have is None:
                result.new.append(EffectUpdate(item.effect_id, item.file_name, item.version, "new", stem, "", None))
            elif version_key(item.version) > version_key(have.version):
                size = have.path.stat().st_size if have.path is not None and have.path.is_file() else None
                result.updated.append(EffectUpdate(item.effect_id, item.file_name, item.version, "updated",
                                                   have.name or stem, have.group, have.version, size))
            else:
                result.current.append(EffectUpdate(item.effect_id, item.file_name, item.version, "current",
                                                   have.name or stem, have.group, have.version))
        if model_id is not None and model_id in firmware_info:
            remote_version, flag = firmware_info[model_id]
            greater = bool(firmware) and version_key(firmware) != () and \
                version_key(remote_version) > version_key(firmware)
            result.firmware = FirmwareStatus(model_id, remote_version, firmware or None, greater or flag, flag)
        return result

    def _save_lists(self, effects_raw: bytes, versions_raw: bytes) -> None:
        try:
            self.library_dir.mkdir(parents=True, exist_ok=True)
            _write_atomic(self.library_dir / EFFECTS_LIST_NAME, effects_raw)
            _write_atomic(self.library_dir / VERSIONS_LIST_NAME, versions_raw)
        except OSError as exc:
            raise UpdateError(f"the lists could not be saved: {exc}") from exc

    def download(self, entries: Iterable[EffectUpdate], progress: Callable[[int, int, EffectUpdate], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> DownloadReport:
        """Fetch, verify and save each entry. A failed entry never stops the others; ``cancelled`` is asked
        before each one, and ``progress(done, total, entry)`` is called as each one starts."""
        items = list(entries)
        report = DownloadReport()
        for index, item in enumerate(items):
            if cancelled is not None and cancelled():
                report.cancelled = True
                break
            if progress is not None:
                progress(index, len(items), item)
            report.results.append(self._download_one(item))
        return report

    def _download_one(self, item: EffectUpdate) -> DownloadResult:
        def fail(reason: str) -> DownloadResult:
            return DownloadResult(item, False, reason)

        if not valid_file_name(item.file_name):
            return fail("bad_name")
        if not _VERSION.fullmatch(item.version):
            return fail("bad_version")
        try:
            zipped = self._get(zip_url(item.file_name), MAX_ZIP_BYTES)
        except FetchError as exc:
            return fail(exc.code)
        except UpdateError:
            return fail("bad_name")
        try:
            body = _extract_zd2(zipped)
        except _Refused as refused:
            return fail(refused.reason)
        final = self.library_dir / library_name(item.file_name, item.version)
        try:
            self.library_dir.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=self.library_dir, prefix=f".{final.name}.", suffix=".part")
        except OSError:
            return fail("write_failed")
        temp = Path(name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
            try:
                info = load_zd2(temp)
            except Exception:  # noqa: BLE001 - the parser's own errors are many; the file is simply not a ZD2
                return fail("bad_zd2")
            if info.effect_id != item.effect_id:
                return fail("id_mismatch")
            if version_key(info.version) != version_key(item.version):
                return fail("version_mismatch")
            if not _publish(temp, final):
                return fail("exists")
            return DownloadResult(item, True, None, final)
        except OSError:
            return fail("write_failed")
        finally:
            temp.unlink(missing_ok=True)
