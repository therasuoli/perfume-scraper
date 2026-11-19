import pytest
from pathlib import Path
from threading import Event

import perfume_scraper.core as core

STORES = Path(__file__).parents[1] / "data" / "perfume-online-stores.xlsx"


@pytest.mark.skipif(not STORES.exists(), reason='Store workbook is not bundled in this ZIP')
def test_store_source_regions_exist_and_load():
    all_sources = core.load_store_sources(STORES, "all")
    uae_sources = core.load_store_sources(STORES, "UAE")
    iran_sources = core.load_store_sources(STORES, "Iran")
    assert len(all_sources) == 62
    assert uae_sources and iran_sources
    assert len(all_sources) >= len(uae_sources) + len(iran_sources)


@pytest.mark.skipif(not STORES.exists(), reason='Store workbook is not bundled in this ZIP')
def test_selected_store_source_filters_by_domain():
    uae = core.load_store_sources(STORES, "UAE")
    target = uae[0]
    selected = core.load_store_sources(STORES, "UAE", target["url"])
    assert len(selected) == 1
    assert selected[0]["url"] == target["url"]


def test_scrape_progress_callback_contains_products(monkeypatch):
    class Response:
        text = '''<html><body><div class="product-card"><a href="/product/test"><h2 class="product-title">Test Perfume</h2></a><img data-src="/img/test.jpg"></div></body></html>'''
        content = text.encode()
        headers = {"content-type": "text/html"}
    monkeypatch.setattr(core, "_sitemap_urls", lambda *args, **kwargs: [])
    monkeypatch.setattr(core, "_get", lambda *args, **kwargs: Response())
    events = []
    items, stats = core.scrape_url("https://shop.test", limit=0, max_pages=2, delay=0,
                                 progress_callback=events.append, session=object())
    assert stats["pages_checked"] >= 1
    assert items and items[0]["name"] == "Test Perfume"
    assert events and events[0]["products_preview"]
    assert items[0]['image_url'] == 'https://shop.test/img/test.jpg'


def test_scrape_cancel_event_prevents_page_requests(monkeypatch):
    monkeypatch.setattr(core, "_sitemap_urls", lambda *args, **kwargs: [])
    called = []
    monkeypatch.setattr(core, "_get", lambda *args, **kwargs: called.append(args) or None)
    stop = Event()
    stop.set()
    items, stats = core.scrape_url("https://shop.test", max_pages=2, delay=0,
                                 session=object(), cancel_event=stop)
    assert not items
    assert stats["pages_checked"] == 0
    assert not called


@pytest.mark.skipif(not STORES.exists(), reason='Store workbook is not bundled in this ZIP')
def test_local_dashboard_serves_ui_and_source_json():
    import json
    import threading
    from urllib.request import urlopen
    from perfume_scraper.ui_server import DashboardHandler
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/", timeout=3) as response:
            html = response.read().decode("utf-8")
            assert response.status == 200
            assert "داشبورد استخراج عطر" in html
        with urlopen(base + "/api/sources?region=UAE", timeout=3) as response:
            payload = json.loads(response.read())
            assert payload["sources"]
            assert payload["regions"]
        with urlopen(base + "/api/status", timeout=3) as response:
            assert json.loads(response.read())["state"] in ("idle", "running", "starting", "finished", "failed", "cancelled")
        for asset in ("/app.js", "/style.css"):
            with urlopen(base + asset, timeout=3) as response:
                assert response.status == 200
                assert response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_dashboard_runner_creates_outputs_and_final_state(monkeypatch, tmp_path):
    import perfume_scraper.ui_server as ui

    class DummySession:
        def close(self):
            pass

    product = {
        "site": "Demo Shop", "name": "Demo Perfume", "brand": "Demo Brand",
        "price": "100", "currency": "USD", "product_url": "https://demo.test/p/1",
        "image_url": "https://demo.test/p/1.jpg", "description": "Demo item",
        "availability": "", "image_path": "", "source_type": "online_store",
    }
    monkeypatch.setattr(ui, "ROOT", tmp_path)
    monkeypatch.setattr(ui, "OUTPUT_ROOT", tmp_path / "run-output")
    monkeypatch.setattr(ui, "BRAND_BOOK", tmp_path / "missing-brand-book.xlsx")
    monkeypatch.setattr(ui, "_get_sources_for_job", lambda cfg: [{"name": "Demo Shop", "url": "https://demo.test", "source_type": "online_store"}])
    monkeypatch.setattr(ui, "create_session", lambda: DummySession())
    monkeypatch.setattr(ui, "scrape_url", lambda *args, **kwargs: ([dict(product)], {"pages_checked": 2, "products_found": 1, "errors": 0}))
    ui.CANCEL_EVENT.clear()
    ui.STATE.update({"logs": [], "source_results": [], "products": [], "sources_done": 0, "pages_checked": 0, "errors": 0})
    ui._worker_run({"mode": "all", "region": "all", "limit_per_site": 1, "max_pages": 2, "delay": 0, "format": "json", "download_images": False})
    state = ui._state_copy()
    assert state["state"] == "finished"
    assert state["products_found"] == 1
    assert state["source_results"][0]["status"] == "ok"
    assert (tmp_path / state["output_file"]).exists()
    outdir = tmp_path / state["output_dir"]
    assert (outdir / "run-report.json").exists()
    assert (outdir / "source-summary.csv").exists()


def test_manual_url_source_parsing():
    from perfume_scraper.ui_server import _get_sources_for_job
    parsed = _get_sources_for_job({"mode": "manual", "urls": "https://shop.one/perfume\nshop.two/catalog, https://shop.one/perfume"})
    assert len(parsed) == 2
    assert parsed[0]["url"] == "https://shop.one/perfume"
    assert parsed[1]["url"] == "https://shop.two/catalog"


def test_dashboard_download_zip_returns_output_bundle(monkeypatch, tmp_path):
    import threading, zipfile, io
    from urllib.request import urlopen
    from perfume_scraper.ui_server import DashboardHandler
    from http.server import ThreadingHTTPServer
    outdir=tmp_path / "run-output"
    outdir.mkdir()
    (outdir / "products.json").write_text("[]",encoding="utf-8")
    monkeypatch.setattr("perfume_scraper.ui_server.ROOT",tmp_path)
    monkeypatch.setattr("perfume_scraper.ui_server.OUTPUT_ROOT",outdir)
    server=ThreadingHTTPServer(("127.0.0.1",0),DashboardHandler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/download-zip",timeout=3) as response:
            assert response.status==200
            payload=zipfile.ZipFile(io.BytesIO(response.read()))
            assert "products.json" in payload.namelist()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_dashboard_includes_live_analytics_and_translation_toggle():
    from pathlib import Path
    html=(Path(__file__).parent.parent/'src'/'perfume_scraper'/'web'/'index.html').read_text(encoding='utf8')
    js=(Path(__file__).parent.parent/'src'/'perfume_scraper'/'web'/'app.js').read_text(encoding='utf8')
    assert 'trendChart' in html and 'healthChart' in html
    assert 'translateFa' in html and 'translate_fa' in js
