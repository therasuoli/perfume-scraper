"""Optional importer for the public, read-only Scento perfume REST API."""
from __future__ import annotations
import re, time, html
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

BASE = 'https://www.scento.com/api/perfume/v1'

def _slug(text):
    return re.sub(r'[^a-z0-9]+','-',str(text or '').casefold()).strip('-')

def _list(v):
    if v is None: return []
    if isinstance(v,list): return [str(x).strip() for x in v if x]
    if isinstance(v,str): return [x.strip() for x in re.split(r'[,;|]',v) if x.strip()]
    return []

def _find_matches(data):
    if isinstance(data,list): return data
    if not isinstance(data,dict): return []
    detail=data.get('detail') or {}
    for candidate in (detail.get('matches'), data.get('matches'), detail.get('results'), data.get('results'), detail.get('items'), data.get('items')):
        if isinstance(candidate,list): return candidate
    return []

def _scento_page_url(hit):
    for key in ('url','scento_url','page_url'):
        val=hit.get(key)
        if isinstance(val,dict): val=val.get('url')
        if val:
            candidate=urljoin('https://www.scento.com/',str(val))
            if urlparse(candidate).netloc.endswith('scento.com'): return candidate
    page=hit.get('scento_page')
    if isinstance(page,dict) and page.get('url'): return urljoin('https://www.scento.com/',str(page['url']))
    return ''

def _extract_slug(hit):
    for key in ('slug','id','perfume_slug'):
        val=hit.get(key)
        if val and isinstance(val,str) and '/' not in val and 'http' not in val: return val
    url=_scento_page_url(hit)
    if url:
        parts=urlparse(url).path.strip('/').split('/')
        if parts and parts[-1]: return parts[-1]
    return _slug(hit.get('name'))

def _api_get(session, url, params=None):
    r=session.get(url,params=params,timeout=25,headers={'User-Agent':'LarsiPerfumeResearch/1.0'})
    r.raise_for_status(); return r.json()

def _house_country(session, house, country_cache):
    if not house: return ''
    slug=_slug(house)
    if slug in country_cache: return country_cache[slug]
    try:
        data=_api_get(session,f'{BASE}/houses/{slug}')
        detail=data.get('detail',{}) if isinstance(data,dict) else {}
        house_info=detail.get('house') or detail.get('brand') or {}
        if isinstance(house_info,str): house_info={}
        country=detail.get('country') or detail.get('origin_country') or detail.get('country_of_origin') or house_info.get('country') or house_info.get('origin_country') or ''
        country_cache[slug]=str(country or '')
    except Exception: country_cache[slug]=''
    return country_cache[slug]

def _page_meta(session, page_url):
    if not page_url: return {}
    try:
        r=session.get(page_url,timeout=18,headers={'User-Agent':'Mozilla/5.0 LarsiPerfumeResearch/1.0'}); r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser')
        def meta(*selectors):
            for sel in selectors:
                n=soup.select_one(sel)
                if n and n.get('content'): return html.unescape(str(n['content']).strip())
            return ''
        img=meta('meta[property="og:image"]','meta[name="twitter:image"]')
        desc=meta('meta[name="description"]','meta[property="og:description"]')
        h1=soup.select_one('h1')
        return {'image_url':img,'page_description':desc,'page_title':h1.get_text(' ',strip=True) if h1 else ''}
    except Exception: return {}

def _to_product(hit, folio, country, session):
    detail=(folio.get('detail') or {}) if isinstance(folio,dict) else {}
    pyramid=detail.get('pyramid') or detail.get('notes_pyramid') or {}
    if not isinstance(pyramid,dict): pyramid={}
    name=detail.get('name') or hit.get('name') or ''
    house=detail.get('house') or detail.get('brand') or hit.get('house') or hit.get('brand') or ''
    if isinstance(house,dict): house=house.get('name') or ''
    top=_list(pyramid.get('top') or detail.get('top_notes') or detail.get('top'))
    heart=_list(pyramid.get('heart') or detail.get('heart_notes') or detail.get('middle_notes') or detail.get('heart'))
    base=_list(pyramid.get('base') or detail.get('base_notes') or detail.get('base'))
    all_notes=_list(detail.get('notes')) or list(dict.fromkeys(top+heart+base))
    family=detail.get('family') or detail.get('scent_family') or hit.get('family') or ''
    secondary=detail.get('secondary_family') or ''
    character=_list(detail.get('character') or detail.get('accords') or hit.get('accords'))
    lede=str(folio.get('lede') or detail.get('description') or detail.get('portrait') or '').strip()
    description=str(detail.get('description') or detail.get('long_description') or lede).strip()
    short=lede[:350].strip()
    long=description if description and description!=short else (lede if len(lede)>350 else '')
    page_url=_scento_page_url(hit) or urljoin('https://www.scento.com/',str((folio.get('scento_page') or {}).get('url','')))
    if not page_url and detail.get('url'): page_url=urljoin('https://www.scento.com/',str(detail.get('url')))
    meta=_page_meta(session,page_url)
    image=detail.get('image') or detail.get('image_url') or hit.get('image') or hit.get('image_url') or meta.get('image_url','')
    if isinstance(image,list): image=image[0] if image else ''
    short=short or meta.get('page_description','')[:350]
    long=long or meta.get('page_description','')
    product_url=page_url
    brand=house
    origin=country or detail.get('country') or detail.get('origin_country') or detail.get('country_of_origin') or ''
    return {'name':str(name).strip(),'brand':str(brand).strip(),'matched_brand':str(brand).strip(),'country':str(origin).strip(),
      'country_of_origin':str(origin).strip(),'family':str(family),'secondary_family':str(secondary),'accords':character,
      'top':top,'heart':heart,'base':base,'notes':all_notes,'year':detail.get('year') or hit.get('year',''),
      'perfumer':detail.get('perfumers') or detail.get('perfumer') or '', 'concentration':detail.get('concentration') or '',
      'character':character,'season':detail.get('seasons') or detail.get('season') or [],
      'short_description':short,'long_description':long,'description':long or short,
      'product_url':product_url,'image_url':str(image or ''),'site':'Scento API','source_type':'scento_api','scraped_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}

def import_scento(queries, limit=100, progress=None, cancel_event=None, request_delay=0.35):
    """Search Scento by supplied terms, fetch portraits and normalize to scraper products."""
    session=requests.Session(); session.headers.update({'User-Agent':'LarsiPerfumeResearch/1.0 (catalog importer)'})
    qlist=list(dict.fromkeys(q.strip() for q in re.split(r'[\n,;]+',str(queries or '')) if q.strip()))
    if not qlist: raise ValueError('حداقل یک عبارت جستجو وارد کنید؛ این API جستجو-محور است و دریافت کامل دیتابیس مجاز نیست.')
    hits={}; stats={'queries':len(qlist),'search_hits':0,'portraits_loaded':0,'failed':0}
    for q in qlist:
        if cancel_event is not None and cancel_event.is_set(): break
        try:
            result=_api_get(session,f'{BASE}/search',{'q':q,'kind':'perfume'})
            for hit in _find_matches(result):
                if not isinstance(hit,dict) or str(hit.get('kind','perfume')).lower() not in ('perfume','fragrance'): continue
                key=_extract_slug(hit)
                if key: hits.setdefault(key,hit)
            stats['search_hits']=len(hits)
            if progress: progress(f'جستجو «{q}»: {len(hits)} نتیجه یکتا')
        except Exception as exc:
            stats['failed']+=1
            if progress: progress(f'خطای جستجوی «{q}»: {exc}')
        time.sleep(request_delay)
        if limit and len(hits)>=limit: break
    products=[]; country_cache={}
    for i,(slug,hit) in enumerate(list(hits.items())[:limit or None],1):
        if cancel_event is not None and cancel_event.is_set(): break
        try:
            folio=_api_get(session,f'{BASE}/perfumes/{slug}')
            detail=folio.get('detail',{}) if isinstance(folio,dict) else {}
            house=detail.get('house') or detail.get('brand') or hit.get('house') or hit.get('brand') or ''
            if isinstance(house,dict): house=house.get('name','')
            country=_house_country(session,house,country_cache)
            item=_to_product(hit,folio,country,session)
            if item.get('name'): products.append(item); stats['portraits_loaded']+=1
            if progress: progress(f'پرتره {i}/{min(len(hits),limit or len(hits))}: {item.get("name",slug)}')
        except Exception as exc:
            stats['failed']+=1
            if progress: progress(f'خطا در دریافت جزئیات {slug}: {exc}')
        time.sleep(request_delay)
    session.close()
    return products,stats
