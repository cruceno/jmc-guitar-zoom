import io
import zipfile

import pytest
from updater_support import A1, COMP, GEQ, HALL, FakeFetcher, effect, make_zip, standard_routes

from jmc_guitar_zoom.effects.catalog import load_zd2
from jmc_guitar_zoom.library import updater
from jmc_guitar_zoom.library.updater import EffectUpdate, LibraryUpdater


def entry(spec, version=None, kind="new"):
    return EffectUpdate(effect_id=int(spec[0], 16), file_name=spec[1], version=version or spec[2], kind=kind,
                        name=spec[1][:-4], group="", local_version=None)


def make(tmp_path, routes=None):
    fetcher = FakeFetcher(standard_routes() if routes is None else routes)
    return LibraryUpdater(tmp_path / "lib", fetcher=fetcher), fetcher


def route(spec, members, corrupt=False):
    return {updater.ZIP_BASE_URL + spec[1]: make_zip(members, corrupt)}


def test_a_good_zip_is_verified_and_saved_as_stem_and_version(tmp_path):
    up, _ = make(tmp_path)
    report = up.download([entry(COMP)])
    [r] = report.results
    assert r.ok and r.reason is None
    saved = tmp_path / "lib" / "COMP_140.zd2"
    assert r.path == saved and saved.read_bytes() == COMP[3].read_bytes()
    assert load_zd2(saved).effect_id == 0x1000010
    assert list((tmp_path / "lib").glob("*.part")) == []


def test_the_version_without_the_dot_names_the_file(tmp_path):
    up, _ = make(tmp_path)
    up.download([entry(HALL), entry(GEQ)])
    assert sorted(p.name for p in (tmp_path / "lib").glob("*.zd2")) == ["GTGEQ71U_120.zd2", "HALL_150.zd2"]


def test_an_effect_id_that_differs_from_the_list_is_refused(tmp_path):
    up, _ = make(tmp_path, standard_routes(zips=route(COMP, {"COMP.ZD2": HALL[3].read_bytes()})))
    [r] = up.download([entry(COMP)]).results
    assert not r.ok and r.reason == "id_mismatch"
    assert list((tmp_path / "lib").glob("*")) == []


def test_a_version_that_differs_from_the_list_is_refused(tmp_path):
    up, _ = make(tmp_path)
    [r] = up.download([entry(COMP, version="1.50")]).results  # the file says 1.40
    assert not r.ok and r.reason == "version_mismatch"
    assert list((tmp_path / "lib").glob("*.zd2")) == []


def test_a_path_in_the_member_name_is_ignored(tmp_path):
    zips = route(COMP, {"../../etc/evil/COMP.ZD2": COMP[3].read_bytes()})
    up, _ = make(tmp_path, standard_routes(zips=zips))
    [r] = up.download([entry(COMP)]).results
    assert r.ok
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == ["COMP_140.zd2"]
    assert r.path.parent == tmp_path / "lib"


def test_only_zd2_members_are_considered_and_the_extension_may_be_lowercase(tmp_path):
    zips = route(COMP, {"readme.txt": b"hi", "sub/comp.zd2": COMP[3].read_bytes()})
    up, _ = make(tmp_path, standard_routes(zips=zips))
    assert up.download([entry(COMP)]).results[0].ok


def test_two_zd2_members_are_refused(tmp_path):
    zips = route(COMP, {"A.ZD2": COMP[3].read_bytes(), "B.ZD2": COMP[3].read_bytes()})
    up, _ = make(tmp_path, standard_routes(zips=zips))
    [r] = up.download([entry(COMP)]).results
    assert not r.ok and r.reason == "many_zd2"
    assert list((tmp_path / "lib").glob("*.zd2")) == []


def test_an_oversized_member_is_refused(tmp_path):
    big = COMP[3].read_bytes() + b"\x00" * (updater.MAX_ZD2_BYTES + 1)
    up, _ = make(tmp_path, standard_routes(zips=route(COMP, {"COMP.ZD2": big})))
    [r] = up.download([entry(COMP)]).results
    assert not r.ok and r.reason == "oversized"


def test_a_zip_without_a_zd2_is_refused(tmp_path):
    up, _ = make(tmp_path, standard_routes(zips=route(COMP, {"notes.txt": b"x", "COMP.exe": b"MZ"})))
    [r] = up.download([entry(COMP)]).results
    assert not r.ok and r.reason == "no_zd2"


def test_a_corrupt_zip_is_refused(tmp_path):
    up, _ = make(tmp_path, standard_routes(zips=route(COMP, {"COMP.ZD2": COMP[3].read_bytes()}, corrupt=True)))
    [r] = up.download([entry(COMP)]).results
    assert not r.ok and r.reason == "bad_zip"


def test_a_member_that_is_not_a_zd2_is_refused(tmp_path):
    up, _ = make(tmp_path, standard_routes(zips=route(COMP, {"COMP.ZD2": b"this is not a zd2 file at all"})))
    [r] = up.download([entry(COMP)]).results
    assert not r.ok and r.reason == "bad_zd2"
    assert list((tmp_path / "lib").glob("*")) == []


def test_a_zip_over_the_size_limit_is_refused_by_the_fetcher_limit(tmp_path):
    routes = standard_routes(zips={updater.ZIP_BASE_URL + COMP[1]: b"PK" + b"\x00" * (updater.MAX_ZIP_BYTES + 1)})
    up, _ = make(tmp_path, routes)
    [r] = up.download([entry(COMP)]).results
    assert not r.ok and r.reason == "too_large"


def test_an_existing_file_is_never_overwritten_and_older_versions_stay(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "COMP_140.zd2").write_bytes(b"mine")
    (lib / "COMP_130.zd2").write_bytes(b"older")
    up, _ = make(tmp_path)
    [r] = up.download([entry(COMP)]).results
    assert not r.ok and r.reason == "exists"
    assert (lib / "COMP_140.zd2").read_bytes() == b"mine" and (lib / "COMP_130.zd2").read_bytes() == b"older"
    assert list(lib.glob("*.part")) == []


def test_a_newer_version_is_added_next_to_the_older_one(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "HALL_140.zd2").write_bytes(b"older")
    up, _ = make(tmp_path)
    assert up.download([entry(HALL, kind="updated")]).results[0].ok
    assert sorted(p.name for p in lib.glob("*.zd2")) == ["HALL_140.zd2", "HALL_150.zd2"]
    assert (lib / "HALL_140.zd2").read_bytes() == b"older"


def test_the_write_is_atomic_the_final_file_appears_only_complete(tmp_path, monkeypatch):
    seen = []
    real = updater._publish

    def spy(temp, final):
        seen.append((temp.name.endswith(".part"), temp.stat().st_size, final.exists()))
        return real(temp, final)

    monkeypatch.setattr(updater, "_publish", spy)
    up, _ = make(tmp_path)
    up.download([entry(COMP)])
    assert seen == [(True, COMP[3].stat().st_size, False)]  # complete in a temp name, final name still absent


def test_one_failure_keeps_what_succeeded(tmp_path):
    up, _ = make(tmp_path, standard_routes(zips=route(HALL, {"HALL.ZD2": b"junk"})))
    report = up.download([entry(COMP), entry(HALL), entry(GEQ)])
    assert [r.ok for r in report.results] == [True, False, True]
    assert (report.ok_count, report.failed_count) == (2, 1)
    assert sorted(p.name for p in (tmp_path / "lib").glob("*.zd2")) == ["COMP_140.zd2", "GTGEQ71U_120.zd2"]


def test_a_network_failure_is_one_entry_failure_not_a_crash(tmp_path):
    routes = standard_routes()
    routes[updater.ZIP_BASE_URL + HALL[1]] = updater.FetchError("sin red")
    up, _ = make(tmp_path, routes)
    report = up.download([entry(HALL), entry(COMP)])
    assert [r.reason for r in report.results] == ["network", None]


def test_progress_is_reported_per_entry_and_cancel_stops_before_the_next(tmp_path):
    up, fetcher = make(tmp_path)
    seen = []
    report = up.download([entry(COMP), entry(HALL), entry(GEQ)],
                         progress=lambda done, total, item: seen.append((done, total, item.file_name)),
                         cancelled=lambda: len(seen) >= 1)  # cancel once the first one started
    assert seen == [(0, 3, "COMP.zip")]
    assert report.cancelled and [r.ok for r in report.results] == [True]
    assert len(fetcher.urls) == 1


@pytest.mark.parametrize("name", ["../x.zip", "a/b.zip", "a\\b.zip", "x.zip/", "x.exe", ".zip", "a b.zip", "x.zip\n", "", "x" * 200 + ".zip"])
def test_a_file_name_that_is_not_plain_is_refused_before_any_request(tmp_path, name):
    up, fetcher = make(tmp_path)
    bad = EffectUpdate(0x1000010, name, "1.40", "new", "x", "", None)
    [r] = up.download([bad]).results
    assert not r.ok and r.reason == "bad_name"
    assert fetcher.urls == []


def test_valid_names_build_urls_only_under_the_channel():
    assert updater.zip_url("ANDLY_3S.zip") == "https://www.zoom.co.jp/archive/GUITAR_LAB/ZDLF3/ANDLY_3S.zip"
    for bad in ("../a.zip", "a/b.zip", "a.zip/..", "https://evil.example/a.zip"):
        with pytest.raises(updater.UpdateError):
            updater.zip_url(bad)


def test_an_invalid_version_is_refused(tmp_path):
    up, _ = make(tmp_path)
    [r] = up.download([entry(COMP, version="1.4")]).results
    assert not r.ok and r.reason == "bad_version"


def test_the_default_fetcher_refuses_a_url_outside_the_channel():
    with pytest.raises(updater.FetchError):
        updater.urllib_fetcher("https://example.com/a.zip", 100)
    with pytest.raises(updater.FetchError):
        updater.urllib_fetcher("http://www.zoom.co.jp/archive/GUITAR_LAB/AllZDL7_2.lst", 100)


def test_the_default_fetcher_sends_only_a_generic_user_agent_and_no_cookies(monkeypatch):
    sent = {}

    class Resp:
        status = 200

        def read(self, n=-1):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Opener:
        def open(self, request, timeout=None):
            sent["headers"] = dict(request.header_items())
            sent["timeout"] = timeout
            sent["url"] = request.full_url
            return Resp()

    monkeypatch.setattr(updater, "_build_opener", lambda: Opener())
    assert updater.urllib_fetcher(updater.EFFECTS_LIST_URL, 1000) == b"ok"
    assert sent["headers"] == {"User-agent": "jmc-guitar-zoom"} and sent["timeout"] and sent["url"] == updater.EFFECTS_LIST_URL
