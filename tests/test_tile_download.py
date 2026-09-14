"""Tests fuer den Tile-Download: ungueltige Antworten, Abbruch, Reconnect, Reissleine.

Ohne Netz: Session.get, der MVT-Parser und time.sleep werden ersetzt.
Ausfuehren: .venv/bin/python -m pytest
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import geopandas as gpd
import pytest
from shapely.geometry import Point

import mapillary_coverage.mapillary as mc

GOOD = (200, {"Content-Type": "application/x-protobuf"}, b"\x1a\x00")
HTML = (200, {"Content-Type": "text/html; charset=utf-8"}, b"<!DOCTYPE html><html></html>")
LOGGER = logging.getLogger("test-coverage")
SINCE = datetime(2020, 1, 1, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, status, headers, content):
        self.status_code = status
        self.headers = headers
        self.content = content


def _tile_cache(tmp_path, bundesland="DE-TT", n=20, y=0):
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    (cache / f"{bundesland}_tiles.json").write_text(json.dumps([{"x": i, "y": y, "z": 14} for i in range(n)]))
    return str(cache)


def _feature():
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [9.0, 48.0]},
        "properties": {"captured_at": int(time.time() * 1000)},
    }


@pytest.fixture
def net(monkeypatch):
    """responder(tile_x, tile_y) -> (status, headers, content); zaehlt Requests und Reconnects."""
    state = {"calls": 0, "reconnects": 0, "responder": lambda x, y: GOOD, "on_reconnect": None, "latency": 0.0}

    def fake_get(self, url, timeout=None):
        state["calls"] += 1
        # Kuenstliche Latenz als Busy-Wait (time.sleep ist abgeschaltet): ohne sie
        # waere der Pool mit allen Tiles fertig, bevor ein Abbruch greifen kann.
        started = time.perf_counter()
        while time.perf_counter() - started < state["latency"]:
            pass
        z, x, y = url.split("?")[0].rsplit("/", 3)[-3:]
        return FakeResponse(*state["responder"](int(x), int(y)))

    def fake_reconnect(logger, timeout=420):
        state["reconnects"] += 1
        if state["on_reconnect"]:
            state["on_reconnect"]()
        return True

    monkeypatch.setattr(mc.requests.Session, "get", fake_get)
    monkeypatch.setattr(mc, "vt_bytes_to_geojson", lambda raw, x, y, z, layer=None: {"features": [_feature()]})
    monkeypatch.setattr(mc.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(mc, "reconnect_vpn", fake_reconnect)
    return state


def _run(tmp_path, cache, **kwargs):
    out = tmp_path / "out"
    params = dict(
        tile_cache_folder=cache,
        output_folder=str(out),
        mapillary_access_token="t",
        min_capture_dt_utc=SINCE,
        logger=LOGGER,
        tqdm_enabled=False,
        retry_pause=0,
    )
    params.update(kwargs)
    return mc.process_bundesland("DE-TT", **params), out / "mapillary_coverage_DE-TT_latest.parquet"


def test_vollstaendiger_lauf_wird_exportiert(tmp_path, net):
    timestamp, parquet = _run(tmp_path, _tile_cache(tmp_path, n=20))
    assert timestamp is not None
    assert len(gpd.read_parquet(parquet)) == 20
    assert net["reconnects"] == 0


def test_html_antwort_wird_nicht_geparst_und_serie_bricht_ab(tmp_path, net, monkeypatch):
    net["responder"] = lambda x, y: HTML
    net["latency"] = 0.005
    monkeypatch.setattr(mc, "vt_bytes_to_geojson", lambda *a, **k: pytest.fail("HTML darf nie geparst werden"))

    timestamp, parquet = _run(tmp_path, _tile_cache(tmp_path, n=60), max_workers=1, abort_after=5)

    assert timestamp is None and not parquet.exists()
    assert net["reconnects"] == 2  # vor beiden Retry-Runden
    assert net["calls"] < 30  # 3 Runden x ~5 statt 60 Tiles x 4 Versuche


def test_reissleine_haelt_luecken_zurueck(tmp_path, net):
    # jede zehnte Tile dauerhaft ungueltig - verstreut, also keine Serie
    net["responder"] = lambda x, y: HTML if x % 10 == 0 else GOOD

    timestamp, parquet = _run(tmp_path, _tile_cache(tmp_path, n=100))

    assert timestamp is None and not parquet.exists()  # 10 % > 2 %
    assert net["reconnects"] == 0


def test_einzelne_luecke_unter_der_grenze_wird_exportiert(tmp_path, net):
    net["responder"] = lambda x, y: HTML if x == 7 else GOOD

    timestamp, parquet = _run(tmp_path, _tile_cache(tmp_path, n=100))

    assert timestamp is not None and len(gpd.read_parquet(parquet)) == 99


def test_reconnect_rettet_den_nachlauf(tmp_path, net):
    state = {"blocked": True}
    net["responder"] = lambda x, y: HTML if state["blocked"] else GOOD
    net["on_reconnect"] = lambda: state.update(blocked=False)

    timestamp, parquet = _run(tmp_path, _tile_cache(tmp_path, n=40), abort_after=5)

    assert net["reconnects"] == 1
    assert timestamp is not None and len(gpd.read_parquet(parquet)) == 40


def test_reconnect_ohne_konfiguration_ist_noop(monkeypatch):
    monkeypatch.delenv("GLUETUN_CONTROL_URL", raising=False)
    monkeypatch.delenv("GLUETUN_API_KEY", raising=False)
    monkeypatch.setattr(mc.requests, "put", lambda *a, **k: pytest.fail("ohne Konfiguration nichts senden"))
    assert mc.reconnect_vpn(LOGGER) is False


def test_pipeline_behaelt_altes_datum_fuer_nicht_exportiertes_land(tmp_path, net, monkeypatch):
    cache = _tile_cache(tmp_path, "DE-AA", n=5, y=1)
    _tile_cache(tmp_path, "DE-BB", n=5, y=2)
    net["responder"] = lambda x, y: HTML if y == 1 else GOOD

    ml_out, meta_out = tmp_path / "ml", tmp_path / "meta"
    ml_out.mkdir()
    old = ml_out / "mapillary_coverage_DE-AA_latest.parquet"
    gpd.GeoDataFrame({"a": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326").to_parquet(old)
    ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    os.utime(old, (ten_days_ago, ten_days_ago))

    laender = tmp_path / "bl.geojson"
    gpd.GeoDataFrame({"id": ["DE-AA", "DE-BB"]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326").to_file(
        laender, driver="GeoJSON"
    )
    monkeypatch.setattr(mc, "get_settings", lambda: None)

    result = mc.run_mapillary_download_pipeline(
        processing_config={
            "freshness_timezone": "Europe/Berlin",
            "freshness_lookback_months": 30,
            "max_file_age_days": 4,
            "ml_output_folder": str(ml_out),
            "output_folder": str(meta_out),
        },
        mapillary_config={"access_token": "t"},
        tiles_config={"cache_folder": cache},
        reference_config={"bundeslaender_geojson": str(laender)},
        tqdm_enabled=False,
        emit=None,
    )

    assert result["processed"] == ["DE-BB"]
    assert result["incomplete"] == ["DE-AA"]
    assert os.path.getmtime(old) == pytest.approx(ten_days_ago)  # alte Datei unangetastet
    meta = json.load(open(meta_out / "ml_metadata.json", encoding="utf-8"))
    assert set(meta["bundeslaender"]) == {"DE-AA", "DE-BB"}  # AA bleibt mit altem Datum drin
    assert meta["last_run_incomplete"] == ["DE-AA"]
    old_day = datetime.fromtimestamp(ten_days_ago, tz=timezone.utc).date().isoformat()
    assert meta["ml_data_from"].startswith(old_day[:8])
