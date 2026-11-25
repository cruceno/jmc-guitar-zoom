"""Shared fixtures of the updater tests: remote lists, zips and a fake fetcher. No network is ever touched."""
import io
import json
import zipfile
from pathlib import Path

from zoomstudio.library import updater

FIX = Path(__file__).parents[1] / "effects" / "fixtures"
A1 = "0x6E001100"
G5N = "0x6E000000"
GARBAGE = b"\r\n   \r\n\x00"

# real effects of the repository fixtures: (type, zip name, version, source file)
COMP = ("0x01000010", "COMP.zip", "1.40", FIX / "COMP.ZD2")
HALL = ("0x09000030", "HALL.zip", "1.50", FIX / "HALL.ZD2")
GEQ = ("0x02000054", "GTGEQ71U.zip", "1.20", FIX / "GTGEQ71U.ZD2")


def effect(spec):
    return {"type": spec[0], "fileName": spec[1], "version": spec[2]}


def effects_lst(models: dict[str, list[dict]], garbage: bytes = GARBAGE) -> bytes:
    doc = {"zdl_url": "http://example.invalid/", "models": [
        {"modelId": mid, "modelName": mid, "editor": True, "effects": effs} for mid, effs in models.items()]}
    return json.dumps(doc).encode() + garbage


def versions_lst(versions: dict[str, str], garbage: bytes = GARBAGE) -> bytes:
    """``versions``: model id -> version, or (version, update flag)."""
    pairs = {mid: (v if isinstance(v, tuple) else (v, False)) for mid, v in versions.items()}
    doc = {"models": [{"modelId": mid, "modelVersion": v, "update": u} for mid, (v, u) in pairs.items()]}
    return json.dumps(doc).encode() + garbage


def make_zip(members: dict[str, bytes], corrupt: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    data = buf.getvalue()
    return data[: len(data) // 2] if corrupt else data


class FakeFetcher:
    """Answers by URL; records every URL asked. A missing URL or an exception value is a network failure."""

    def __init__(self, routes: dict[str, bytes | Exception] | None = None) -> None:
        self.routes = routes or {}
        self.urls: list[str] = []

    def __call__(self, url: str, max_bytes: int) -> bytes:
        self.urls.append(url)
        answer = self.routes.get(url)
        if answer is None:
            raise updater.FetchError(f"no route for {url}")
        if isinstance(answer, Exception):
            raise answer
        if len(answer) > max_bytes:
            raise updater.FetchError("too large", code="too_large")
        return answer


def standard_routes(models=None, versions=None, zips=None) -> dict[str, bytes]:
    models = models if models is not None else {A1: [effect(COMP), effect(HALL), effect(GEQ)]}
    routes = {updater.EFFECTS_LIST_URL: effects_lst(models),
              updater.VERSIONS_LIST_URL: versions_lst(versions if versions is not None else {A1: "1.02"})}
    for spec in (COMP, HALL, GEQ):
        routes[updater.ZIP_BASE_URL + spec[1]] = make_zip({spec[1].replace(".zip", ".ZD2"): spec[3].read_bytes()})
    routes.update(zips or {})
    return routes
