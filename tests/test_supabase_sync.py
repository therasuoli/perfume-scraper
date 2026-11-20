from perfume_scraper.supabase_sync import to_payload, sync_products

def test_scraped_fields_are_mapped_into_payload():
    row = to_payload({
        "name": "Rose Perfume", "brand": "Rose House", "product_url": "https://shop.test/products/rose",
        "image_url": "https://img.test/rose.jpg", "short_description": "short",
        "long_description": "long", "description": "fallback", "site": "shop.test",
        "price": "12", "currency": "AED"
    })
    assert row["id"]
    assert row["payload"]["name"] == "Rose Perfume"
    assert row["payload"]["brand"] == "Rose House"
    assert row["payload"]["image_url"] == "https://img.test/rose.jpg"
    assert row["payload"]["short_description"] == "short"
    assert row["payload"]["long_description"] == "long"
    assert row["payload"]["product_url"] == "https://shop.test/products/rose"

def test_sync_requires_supabase_secrets(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    try:
        sync_products([])
    except RuntimeError as exc:
        assert "SUPABASE_URL" in str(exc)
    else:
        assert False, "Should require credentials"
