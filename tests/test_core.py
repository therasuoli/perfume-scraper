import json
from pathlib import Path
from bs4 import BeautifulSoup
from perfume_scraper.core import _product_from_jsonld, load_sources, normalize, create_session

WORKBOOK=Path(__file__).parents[1]/'data'/'perfume-brands-by-country.xlsx'

def test_workbook_has_eight_iranian_sources():
    sources=load_sources(WORKBOOK,'iranian')
    assert len(sources)==8
    assert any('toofunatr.com' in x['url'] for x in sources)

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
