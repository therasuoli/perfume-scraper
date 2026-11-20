import pytest
import json
from pathlib import Path
from bs4 import BeautifulSoup
from perfume_scraper.core import _product_from_jsonld, load_sources, normalize, create_session, _split_description, _clean_text, enrich_product_details

WORKBOOK=Path(__file__).parents[1]/'data'/'perfume-brands-by-country.xlsx'

@pytest.mark.skipif(not WORKBOOK.exists(), reason='Source workbook is not bundled in this ZIP')
def test_workbook_has_eight_iranian_sources():
    sources=load_sources(WORKBOOK,'iranian')
    assert len(sources)==8
    assert any('toofunatr.com' in x['url'] for x in sources)

@pytest.mark.skipif(not WORKBOOK.exists(), reason='Source workbook is not bundled in this ZIP')
def test_all_sources_includes_brand_sites_and_iranian_shops():
    sources=load_sources(WORKBOOK,'all')
    assert len(sources)>8
    assert any(x['source_type']=='brand' for x in sources)
    assert any(x['source_type']=='iranian_store' for x in sources)

def test_jsonld_product_extraction():
    item=_product_from_jsonld({'@type':'Product','name':'Test Perfume','brand':{'@type':'Brand','name':'Test Brand'},'image':'/p.jpg','offers':{'price':'100','priceCurrency':'IRR'}},'https://shop.test/p/','shop.test')
    assert item['name']=='Test Perfume'
    assert item['brand']=='Test Brand'
    assert item['price']=='100'
    assert item['image_url']=='https://shop.test/p.jpg'
    assert item['short_description']==''
    assert item['long_description']==''

def test_normalize():
    assert normalize('CHANEL') == 'chanel'
    assert normalize('Chloé') == 'chlo'


def test_create_session_has_retrying_http_adapters():
    session = create_session()
    try:
        assert 'PerfumeResearchBot' in session.headers['User-Agent']
        assert session.get_adapter('https://').max_retries.total == 3
        assert session.get_adapter('http://').max_retries.total == 3
    finally:
        session.close()


def test_description_split_and_html_cleanup():
    raw='<p>Perfume <strong>description</strong> with details</p>'
    assert _clean_text(raw)=='Perfume description with details'
    short, long = _split_description('A' * 400)
    assert len(short)==320 and len(long)==400


def test_enrich_product_detail_page_extracts_descriptions_image_and_brand(monkeypatch):
    class FakeResponse:
        headers = {"content-type": "text/html; charset=utf-8"}
        text = """<html><head><meta name="description" content="Short SEO description"></head>
        <body><h1>Full Perfume Title</h1><div class="product-description"><p>Long perfume description with notes and story, longer than twenty characters.</p></div>
        <img class="product-image" data-src="/assets/product.webp"><span class="product-brand">Test House</span></body></html>"""
    monkeypatch.setattr("perfume_scraper.core._get", lambda *args, **kwargs: FakeResponse())
    product = {"site":"Demo", "name":"Perfume", "product_url":"https://demo.test/p/", "image_url":"", "brand":"", "description":"", "short_description":"", "long_description":""}
    count = enrich_product_details(object(), [product], max_details=1)
    assert count == 1
    assert product["name"] == "Full Perfume Title"
    assert product["short_description"] == "Short SEO description"
    assert "Long perfume description" in product["long_description"]
    assert product["image_url"] == "https://demo.test/assets/product.webp"
    assert product["brand"] == "Test House"


def test_translate_products_keeps_original_and_marks_unavailable(monkeypatch):
    from perfume_scraper.core import translate_products
    monkeypatch.delenv('LIBRETRANSLATE_URL', raising=False)
    rows=[{'name':'Test perfume','description':'A floral fragrance'}]
    count=translate_products(rows)
    assert count == 0
    assert rows[0]['description'] == 'A floral fragrance'
    assert rows[0]['description_fa'] == ''
    assert rows[0]['translation_status'] == 'unavailable'


def test_smart_category_uses_family_or_notes():
    from perfume_scraper.core import classify_product
    assert classify_product({'family':'Amber'})['category']=='Amber'
    assert classify_product({'name':'Oud Wood','notes':['Oud','Sandalwood']})['category']=='woody'

def test_brand_country_enrichment_sets_country_if_known():
    from perfume_scraper.core import enrich_brand
    products=[{'name':'Sauvage Eau de Parfum','brand':'Dior'}]
    rows=[{'برند (English)':'Dior','برند (فارسی)':'دیور','Country / Region':'France'}]
    enrich_brand(products,rows)
    assert products[0]['matched_brand']=='Dior'
    assert products[0]['country']=='France'


def test_export_assigns_product_and_image_numbers(tmp_path):
    from perfume_scraper.core import write_output
    products=[{'name':'Perfume A','image_url':'https://img.test/a.jpg'}, {'name':'Perfume B'}, {'name':'Perfume C','image_url':'https://img.test/c.jpg'}]
    out=write_output(products,'json',tmp_path)
    rows=json.loads(out.read_text(encoding='utf-8'))
    assert [x['product_number'] for x in rows]==[1,2,3]
    assert [x.get('image_number') for x in rows]==[1,None,2]


def test_export_assigns_product_and_image_numbers(tmp_path):
    from perfume_scraper.core import write_output
    products=[{'name':'Perfume A','image_url':'https://img.test/a.jpg'}, {'name':'Perfume B'}, {'name':'Perfume C','image_url':'https://img.test/c.jpg'}]
    out=write_output(products,'json',tmp_path)
    rows=json.loads(out.read_text(encoding='utf-8'))
    assert [x['product_number'] for x in rows]==[1,2,3]
    assert [x.get('image_number') for x in rows]==[1,None,2]
