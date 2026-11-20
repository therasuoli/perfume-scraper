from perfume_scraper.scento_api import _find_matches, _extract_slug, _to_product

class FakeSession:
    def get(self, url, timeout=0, headers=None):
        class Response:
            text='<html><head><meta property="og:image" content="https://cdn.test/a.jpg"><meta name="description" content="Meta description"></head><body><h1>Test Perfume</h1></body></html>'
            def raise_for_status(self): pass
        return Response()

def test_search_results_parser_handles_folio_matches():
    assert _find_matches({'detail': {'matches': [{'kind':'perfume','name':'Rose'}]}})[0]['name']=='Rose'

def test_slug_from_scento_url():
    assert _extract_slug({'name':'Oud Wood','url':'https://www.scento.com/perfumes/oud-wood-tom-ford'})=='oud-wood-tom-ford'

def test_api_product_fields_and_image_metadata():
    hit={'kind':'perfume','name':'Test Perfume','house':'Test House','url':'https://www.scento.com/perfumes/test-perfume'}
    folio={'lede':'A short scent portrait','detail':{'name':'Test Perfume','house':'Test House','family':'Woody','pyramid':{'top':['Bergamot'],'heart':['Rose'],'base':['Oud']},'description':'A longer profile.'},'scento_page':{'url':hit['url']}}
    product=_to_product(hit,folio,'France',FakeSession())
    assert product['brand']=='Test House'
    assert product['country_of_origin']=='France'
    assert product['family']=='Woody'
    assert product['top']==['Bergamot'] and product['base']==['Oud']
    assert product['short_description']=='A short scent portrait'
    assert product['long_description']=='A longer profile.'
    assert product['image_url']=='https://cdn.test/a.jpg'
    assert product['source_type']=='scento_api'
