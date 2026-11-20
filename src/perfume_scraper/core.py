from __future__ import annotations
import csv, json, logging, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
LOG=logging.getLogger('perfume_scraper')
HEADERS={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125 Safari/537.36 PerfumeResearchBot/2.0'}

def create_session():
    session=requests.Session(); session.headers.update(HEADERS)
    retry=Retry(total=3,connect=3,read=2,status=3,backoff_factor=.6,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(('GET',)),raise_on_status=False)
    adapter=HTTPAdapter(max_retries=retry,pool_connections=12,pool_maxsize=12)
    session.mount('http://',adapter); session.mount('https://',adapter); return session
PRODUCT_WORDS=('product','perfume','fragrance','عطر','ادکلن','محصول')
CATEGORY_WORDS=('shop','store','category','categories','collection','collections','product-category','products','catalog','برند','دسته','فروشگاه')
SKIP_EXT=('.jpg','.jpeg','.png','.webp','.gif','.svg','.pdf','.zip','.css','.js','.woff','.mp4','.mp3','.xml','.json')

def _url(u):
    u=urldefrag(str(u or '').strip())[0]
    if not u: return ''
    if not u.startswith(('http://','https://')): u='https://'+u.lstrip('/')
    return u

def _norm_header(s):
    return re.sub(r'[\u200c\u200f\u0640\s]+','',str(s or '')).casefold()
def _find_col(headers, terms):
    normalized=[_norm_header(h) for h in headers]
    for term in terms:
        t=_norm_header(term)
        for i,h in enumerate(normalized):
            if t in h: return i
    return None

def load_sources(workbook,source='iranian'):
    from openpyxl import load_workbook
    wb=load_workbook(workbook,data_only=True); out=[]
    if source in ('all','brands','iranian') and 'برندهای عطر' in wb.sheetnames and source in ('all','brands'):
        ws=wb['برندهای عطر']; rows=list(ws.values)
        if rows:
            headers=[str(x or '').strip() for x in rows[0]]
            urlcol=_find_col(headers,('وب سایت رسمی','وبسایت رسمی','website','url','سایت'))
            namecol=_find_col(headers,('برند english','brand name','برند'))
            if urlcol is not None:
                for r in rows[1:]:
                    raw=r[urlcol] if len(r)>urlcol else None
                    if raw:
                        name=(r[namecol] if namecol is not None and len(r)>namecol and r[namecol] else raw)
                        u=_url(raw)
                        if urlparse(u).netloc: out.append({'name':str(name),'url':u,'source_type':'brand'})
    if source in ('all','iranian') and 'فروشگاه‌های ایرانی' in wb.sheetnames:
        ws=wb['فروشگاه‌های ایرانی']; rows=list(ws.values)
        if rows:
            headers=[str(x or '').strip() for x in rows[0]]
            ucol=_find_col(headers,('آدرس وب سایت','website','url','آدرس'))
            ncol=_find_col(headers,('نام فروشگاه','نام','store name'))
            if ucol is not None:
                for r in rows[1:]:
                    raw=r[ucol] if len(r)>ucol else None
                    if raw:
                        name=(r[ncol] if ncol is not None and len(r)>ncol and r[ncol] else raw)
                        u=_url(raw)
                        if urlparse(u).netloc: out.append({'name':str(name),'url':u,'source_type':'iranian_store'})
    seen=set(); cleaned=[]
    for x in out:
        key=x['url'].lower().rstrip('/')
        if key not in seen: seen.add(key); cleaned.append(x)
    LOG.info('منابع شناسایی‌شده از اکسل (%s): %d',source,len(cleaned))
    return cleaned


def load_store_sources(workbook, regions='all', selection=''):
    """
    Load online retailer sources from the Iran/UAE/Global/Niche/Official Brands workbook.
    `selection` accepts comma- or newline-separated store names or URLs.
    """
    from openpyxl import load_workbook
    wb=load_workbook(workbook,data_only=True)
    region_map={'iran':'Iran','uae':'UAE','global':'Global','niche':'Niche','official':'Official Brands'}
    requested=regions.strip().lower()
    if requested in ('all','all_stores',''):
        sheets=[s for s in ('Iran','UAE','Global','Niche','Official Brands') if s in wb.sheetnames]
    else:
        key=requested.replace('official brands','official').replace('official-brands','official')
        sheet=region_map.get(key, regions)
        sheets=[sheet] if sheet in wb.sheetnames else []
    tokens={x.strip().casefold() for x in re.split(r'[\n,;]+',selection or '') if x.strip()}
    out=[]
    for sheet in sheets:
        rows=list(wb[sheet].values)
        if not rows: continue
        headers=[str(x or '').strip() for x in rows[0]]
        ncol=_find_col(headers,('Store Name','نام فروشگاه','نام'))
        ucol=_find_col(headers,('Direct Store / Perfume URL','Website','URL','آدرس'))
        countrycol=_find_col(headers,('Country / Region','Country','کشور'))
        typecol=_find_col(headers,('Store Type','Type','نوع فروشگاه'))
        focuscol=_find_col(headers,('Product Focus','Focus','تمرکز'))
        notescol=_find_col(headers,('Notes / Verification','Notes','توضیحات'))
        if ucol is None: continue
        for row in rows[1:]:
            raw=row[ucol] if len(row)>ucol else None
            if not raw: continue
            url=_url(raw)
            if not urlparse(url).netloc: continue
            name=str(row[ncol] if ncol is not None and len(row)>ncol and row[ncol] else urlparse(url).netloc).strip()
            host=urlparse(url).netloc.casefold().removeprefix('www.')
            token_hosts={t.replace('https://','').replace('http://','').split('/')[0].casefold().removeprefix('www.') for t in tokens}
            if tokens and name.casefold() not in tokens and url.casefold() not in tokens and host not in token_hosts:
                continue
            source={'name':name,'url':url,'source_type':'online_store','region':sheet}
            if countrycol is not None and len(row)>countrycol: source['country']=str(row[countrycol] or '')
            if typecol is not None and len(row)>typecol: source['store_type']=str(row[typecol] or '')
            if focuscol is not None and len(row)>focuscol: source['product_focus']=str(row[focuscol] or '')
            if notescol is not None and len(row)>notescol: source['notes']=str(row[notescol] or '')
            out.append(source)
    seen=set(); cleaned=[]
    for x in out:
        key=x['url'].lower().rstrip('/')
        if key not in seen: seen.add(key); cleaned.append(x)
    LOG.info('منابع فروشگاه از شیت (%s): %d',regions,len(cleaned))
    return cleaned

def _get(session,url):
    """Adaptive request strategy: retry transient errors with longer timeouts and backoff.
    Respects server throttling; does not bypass access controls or CAPTCHA.
    """
    last_error=None
    for attempt, timeout in enumerate((18, 28, 40), 1):
        try:
            r=session.get(url,timeout=timeout,allow_redirects=True)
            if r.status_code in (429, 503):
                wait=min(2 ** attempt, 12)
                LOG.warning('محدودیت موقت %s (HTTP %s)، مکث %ss',url,r.status_code,wait)
                if attempt<3: time.sleep(wait); continue
            r.raise_for_status()
            try: session._perfume_last_error=None
            except Exception: pass
            return r
        except requests.RequestException as e:
            last_error=e
            if attempt<3:
                wait=min(1.2 * (2 ** (attempt-1)), 6)
                LOG.warning('تلاش %s/3 ناموفق %s: %s؛ تلاش مجدد پس از %ss',attempt,url,e,wait)
                time.sleep(wait)
    try: session._perfume_last_error=f'{type(last_error).__name__}: {last_error}'
    except Exception: pass
    LOG.warning('دریافت پس از ۳ تلاش ناموفق %s: %s',url,last_error)
    return None


def translate_to_persian(text, endpoint=None, api_key=None, timeout=18):
    """Optional LibreTranslate-compatible translation. Original text is always retained.
    Set LIBRETRANSLATE_URL (and optionally LIBRETRANSLATE_API_KEY) to enable.
    """
    text=_clean_text(text)
    if not text: return ''
    endpoint=(endpoint or __import__('os').environ.get('LIBRETRANSLATE_URL','')).strip()
    api_key=api_key or __import__('os').environ.get('LIBRETRANSLATE_API_KEY','')
    if not endpoint: return ''
    try:
        payload={'q':text,'source':'auto','target':'fa','format':'text'}
        if api_key: payload['api_key']=api_key
        response=requests.post(endpoint.rstrip('/')+'/translate',json=payload,timeout=timeout)
        response.raise_for_status()
        translated=(response.json() or {}).get('translatedText','')
        return _clean_text(translated)
    except Exception as exc:
        LOG.warning('ترجمه خودکار در دسترس نیست: %s',exc)
        return ''


def translate_products(items, progress_callback=None):
    """Add Persian translation fields without overwriting source-language fields."""
    translated_count=0
    cache={}
    for idx,item in enumerate(items,1):
        for field in ('short_description','long_description','description'):
            original=item.get(field) or ''
            target=f'{field}_fa'
            if original and not item.get(target):
                key=_clean_text(original)
                if key not in cache: cache[key]=translate_to_persian(key)
                item[target]=cache[key]
                if item[target]: translated_count+=1
        item['translation_status']='translated' if any(item.get(f'{f}_fa') for f in ('short_description','long_description','description')) else ('unavailable' if any(item.get(f) for f in ('short_description','long_description','description')) else 'empty')
        if progress_callback and idx%10==0: progress_callback(idx,len(items),translated_count)
    return translated_count

def _walk_jsonld(obj):
    if isinstance(obj,list):
        for x in obj: yield from _walk_jsonld(x)
    elif isinstance(obj,dict):
        yield obj
        for v in obj.values():
            if isinstance(v,(dict,list)): yield from _walk_jsonld(v)

def _clean_text(value):
    if value is None: return ''
    if isinstance(value, (list, tuple)): value=' '.join(str(x) for x in value)
    text=BeautifulSoup(str(value), 'html.parser').get_text(' ', strip=True)
    return re.sub(r'\s+', ' ', text).strip()

def _split_description(description):
    text=_clean_text(description)
    if not text: return '', ''
    short=text[:320].strip()
    long=text if len(text)>320 else ''
    return short, long

def _description_from_soup(soup):
    short=''
    for selector in ('meta[name="description"]','meta[property="og:description"]','meta[name="twitter:description"]'):
        node=soup.select_one(selector)
        if node and node.get('content'):
            short=_clean_text(node.get('content')); break
    long=''
    selectors=(
        '[itemprop="description"]','.woocommerce-product-details__short-description',
        '.woocommerce-Tabs-panel--description','.product-description','.product__description',
        '.product-description-content','.product-details__description','.description',
        '#description','.tab-content .description','.product__content .rte',
    )
    for selector in selectors:
        node=soup.select_one(selector)
        if node:
            candidate=_clean_text(node)
            if len(candidate)>20:
                long=candidate; break
    if not short and long: short=long[:320]
    return short, long

def enrich_product_details(session, items, progress_callback=None, cancel_event=None, max_details=40):
    """Visit product pages to fill missing product descriptions, names, brands and images."""
    enriched=0
    candidates=[x for x in items if x.get('product_url') and (not x.get('long_description') or not x.get('image_url') or not x.get('brand'))]
    for index,item in enumerate(candidates[:max_details],1):
        if cancel_event is not None and cancel_event.is_set(): break
        url=item.get('product_url','')
        response=_get(session,url)
        if not response or 'html' not in response.headers.get('content-type','text/html').lower():
            continue
        soup=BeautifulSoup(response.text,'html.parser')
        for script in soup.select('script[type="application/ld+json"]'):
            try: parsed=json.loads(script.string or script.get_text())
            except Exception: continue
            for structured in _walk_jsonld(parsed):
                product=_product_from_jsonld(structured,url,item.get('site',''))
                if product:
                    for key in ('name','brand','price','currency','image_url','availability','short_description','long_description'):
                        if product.get(key) and (not item.get(key) or (key in ('short_description','long_description') and len(product.get(key,''))>len(item.get(key,'')))):
                            item[key]=product[key]
                    break
        title=soup.select_one('h1[itemprop="name"],h1.product_title,h1.product-title,h1')
        if title:
            title_text=_clean_text(title)
            if title_text and (not item.get('name') or len(item.get('name',''))<len(title_text)): item['name']=title_text
        short,long=_description_from_soup(soup)
        if short and (not item.get('short_description') or len(short)>len(item.get('short_description',''))): item['short_description']=short
        if long and (not item.get('long_description') or len(long)>len(item.get('long_description',''))): item['long_description']=long
        item['description']=item.get('long_description') or item.get('short_description') or item.get('description','')
        if not item.get('image_url'):
            image=_page_image(soup,url)
            if not image:
                node=soup.select_one('img[itemprop="image"],.woocommerce-product-gallery img,.product-gallery img,.product-image img,img.product-image,img#product-image')
                if node:
                    image=node.get('data-src') or node.get('data-lazy-src') or node.get('src') or ''
                    image=urljoin(url,image) if image else ''
            if image: item['image_url']=_url(image)
        if not item.get('brand'):
            brand_node=soup.select_one('[itemprop="brand"] [itemprop="name"], [itemprop="brand"],.product-brand,.brand-name')
            if brand_node: item['brand']=_clean_text(brand_node.get('content') or brand_node)
        price_node=soup.select_one('[itemprop="price"],.price .amount,.product-price,.price')
        if not item.get('price') and price_node: item['price']=_clean_text(price_node.get('content') or price_node)
        enriched+=1
        if progress_callback: progress_callback({'event':'detail','site':item.get('site',''),'page':url,'details_checked':index,'details_total':min(len(candidates),max_details),'products_found':len(items),'status':'detail'})
    return enriched

def _product_from_jsonld(data,page_url,site_name):
    typ=data.get('@type',[]); typ=[typ] if isinstance(typ,str) else typ
    if not any('product' in str(t).lower() for t in typ): return None
    name=data.get('name')
    if not name: return None
    offers=data.get('offers') or {}; offers=offers[0] if isinstance(offers,list) and offers else offers
    image=data.get('image') or ''; image=image[0] if isinstance(image,list) and image else image
    brand=data.get('brand') or {}; brand=brand.get('name','') if isinstance(brand,dict) else brand
    return {'site':site_name,'name':str(name).strip(),'brand':str(brand or ''),'price':str(offers.get('price','') if isinstance(offers,dict) else ''),'currency':str(offers.get('priceCurrency','') if isinstance(offers,dict) else ''),'product_url':_url(urljoin(page_url,str(data.get('url') or page_url))),'image_url':_url(urljoin(page_url,str(image))) if image else '', 'description':_clean_text(data.get('description','')),'short_description':_split_description(data.get('description',''))[0],'long_description':_split_description(data.get('description',''))[1],'availability':str(offers.get('availability','') if isinstance(offers,dict) else ''),'image_path':''}

def _page_image(soup,page_url):
    for selector,attr in (('meta[property="og:image"]','content'),('meta[name="twitter:image"]','content'),('meta[property="twitter:image"]','content')):
        node=soup.select_one(selector)
        value=node.get(attr,'') if node else ''
        if value: return _url(urljoin(page_url,value))
    return ''

def _cards(soup,page_url,site_name):
    out=[]
    selectors=('li.product','.product-small','.product-card','.product-item','[itemtype*=Product]','.product','.products li','.woocommerce-loop-product__link','article.product','[data-product-id]')
    cards=[]
    for sel in selectors:
        try: cards.extend(soup.select(sel))
        except Exception: pass
    for c in cards:
        a=c.select_one('a[href]'); title=c.select_one('.woocommerce-loop-product__title,.product-title,.title,[itemprop=name],h2,h3,[data-product-name]')
        name=title.get_text(' ',strip=True) if title else (a.get('title','') if a else '')
        if not name and a: name=a.get_text(' ',strip=True)
        if not name or not a: continue
        price=c.select_one('.price,.amount,[itemprop=price],[data-price]'); desc=c.select_one('.product-description,.description,.short-description,.product-excerpt,[itemprop=description],.woocommerce-product-details__short-description'); img=c.select_one('img')
        image=(img.get('data-srcset') or img.get('srcset') or img.get('data-src') or img.get('data-lazy-src') or img.get('data-original') or img.get('data-original-src') or img.get('src') or '').split(',')[0].strip().split(' ')[0] if img else ''
        href=a.get('href')
        if not href: continue
        out.append({'site':site_name,'name':name,'brand':'','price':price.get_text(' ',strip=True) if price else (price.get('content','') if price else ''),'currency':'','product_url':_url(urljoin(page_url,href)),'image_url':_url(urljoin(page_url,image)) if image else '', 'description':_clean_text(desc) if desc else '', 'short_description':_clean_text(desc)[:320] if desc else '', 'long_description':'','availability':'','image_path':''})
    # Product microdata even if card wrappers are non-standard
    for node in soup.select('[itemtype*=Product]'):
        name_node=node.select_one('[itemprop=name]'); url_node=node.select_one('[itemprop=url]') or node.select_one('a[href]')
        name=(name_node.get('content') or name_node.get_text(' ',strip=True)) if name_node else ''
        url=url_node.get('content') or url_node.get('href') if url_node else page_url
        if name and url:
            out.append({'site':site_name,'name':name,'brand':'','price':'','currency':'','product_url':_url(urljoin(page_url,url)),'image_url':'','description':'','short_description':'','long_description':'','availability':'','image_path':''})
    return out

def _sitemap_urls(session,base,max_urls=150):
    found=[]; seen=set(); roots=[urljoin(base,'/sitemap.xml'),urljoin(base,'/sitemap_index.xml')]
    for sm in roots:
        r=_get(session,sm)
        if not r or not r.text.strip().startswith(('<','<?xml')): continue
        try: root=__import__('xml.etree.ElementTree',fromlist=['ElementTree']).fromstring(r.content)
        except Exception: continue
        locs=[_url(x.text) for x in root.iter() if x.tag.lower().endswith('loc') and x.text]
        for u in locs:
            if u in seen: continue
            seen.add(u)
            if u.lower().endswith('.xml'):
                if len(found)<12:
                    rr=_get(session,u)
                    if rr:
                        try:
                            sub=__import__('xml.etree.ElementTree',fromlist=['ElementTree']).fromstring(rr.content)
                            found.extend(_url(x.text) for x in sub.iter() if x.tag.lower().endswith('loc') and x.text and any(w in x.text.lower() for w in PRODUCT_WORDS+ CATEGORY_WORDS))
                        except Exception: pass
            elif any(w in u.lower() for w in PRODUCT_WORDS+ CATEGORY_WORDS): found.append(u)
            if len(found)>=max_urls: break
    return list(dict.fromkeys(found))[:max_urls]

def scrape_url(start_url,site_name=None,limit=0,download_images=False,image_dir='run-output/images',delay=1.0,max_pages=40,session=None,progress_callback=None,cancel_event=None,enrich_details=False):
    start_url=_url(start_url); site_name=site_name or urlparse(start_url).netloc; s=session or create_session()
    base=f'{urlparse(start_url).scheme}://{urlparse(start_url).netloc}'
    queue=[start_url]; queue.extend(_sitemap_urls(s,base,max_pages)); seen_pages=set(); products={}
    # Add typical shop/catalog endpoints, harmless if unavailable.
    for path in ('/shop/','/products/','/collections/all','/product-category/perfume/','/category/perfume/','/perfumes/','/عطر/'):
        queue.append(urljoin(base,path))
    stats={'pages_checked':0,'products_found':0,'errors':0,'error_details':[]}
    while queue and len(seen_pages)<max_pages and (not limit or len(products)<limit):
        if cancel_event is not None and cancel_event.is_set(): break
        page=queue.pop(0)
        if page in seen_pages or not page.startswith(('http://','https://')) or not _same_host(page,start_url): continue
        seen_pages.add(page); stats['pages_checked']+=1
        r=_get(s,page)
        if not r:
            stats['errors']+=1
            stats['error_details'].append({'url':page,'reason':getattr(s,'_perfume_last_error','request failed after retries')})
            if progress_callback: progress_callback({'event':'page','site':site_name,'page':page,'pages_checked':stats['pages_checked'],'products_found':len(products),'products_preview':list(products.values())[-30:],'errors':stats['errors'],'status':'error'})
            continue
        if 'html' not in r.headers.get('content-type','text/html').lower():
            if progress_callback: progress_callback({'event':'page','site':site_name,'page':page,'pages_checked':stats['pages_checked'],'products_found':len(products),'products_preview':list(products.values())[-30:],'errors':stats['errors'],'status':'non_html'})
            continue
        soup=BeautifulSoup(r.text,'html.parser')
        for script in soup.select('script[type="application/ld+json"]'):
            try: parsed=json.loads(script.string or script.get_text())
            except Exception: continue
            for obj in _walk_jsonld(parsed):
                item=_product_from_jsonld(obj,page,site_name)
                if item: products[item['product_url']]=item
        for item in _cards(soup,page,site_name): products.setdefault(item['product_url'],item)
        fallback_image=_page_image(soup,page)
        if fallback_image:
            for item in products.values():
                if item.get('product_url') and not item.get('image_url') and item['product_url'].rstrip('/')==page.rstrip('/'): 
                    item['image_url']=fallback_image
        for a in soup.select('a[href]'):
            raw=a.get('href'); u=_url(urljoin(page,raw))
            if not u or not _same_host(u,start_url) or u in seen_pages or any(u.lower().split('?')[0].endswith(x) for x in SKIP_EXT): continue
            path=urlparse(u).path.lower(); txt=a.get_text(' ',strip=True).lower()
            if any(w in path or w in txt for w in PRODUCT_WORDS+CATEGORY_WORDS):
                if u not in queue and len(queue)<max_pages*4: queue.append(u)
        # Discover Shopify product JSON endpoint links and product structured URLs where present
        if delay: time.sleep(delay)
        stats['products_found']=len(products)
        if progress_callback: progress_callback({'event':'page','site':site_name,'page':page,'pages_checked':stats['pages_checked'],'products_found':len(products),'products_preview':list(products.values())[-30:],'errors':stats['errors'],'status':'running','queue':len(queue)})
        LOG.info('%s | pages %d/%d | products %d | queue %d',site_name,len(seen_pages),max_pages,len(products),len(queue))
    items=list(products.values())[:limit or None]
    if enrich_details and items:
        enrich_product_details(s,items,progress_callback=progress_callback,cancel_event=cancel_event,max_details=min(len(items),40))
    if download_images:
        image_no=0
        for i,item in enumerate(items,1):
            if cancel_event is not None and cancel_event.is_set(): break
            if item.get('image_url'):
                image_no+=1; item['image_number']=image_no
                try: item['image_path']=str(_download_image(s,item['image_url'],image_dir,image_no))
                except (requests.RequestException, OSError) as e: LOG.warning('تصویر دانلود نشد: %s',e)
    stats['products_found']=len(items)
    return items,stats

def _same_host(a,b): return urlparse(a).netloc.lower().removeprefix('www.')==urlparse(b).netloc.lower().removeprefix('www.')
def _download_image(session,url,folder,number):
    r=session.get(url,timeout=25); r.raise_for_status(); ct=r.headers.get('content-type','').split(';')[0].lower(); ext={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp','image/gif':'.gif'}.get(ct,Path(urlparse(url).path).suffix or '.img')
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True); p=folder/f'image-{number:05d}{ext}'; p.write_bytes(r.content); return p

def normalize(s): return re.sub(r'[^a-z0-9]','',(s or '').casefold())
def load_brands(path):
    from openpyxl import load_workbook
    wb=load_workbook(path,data_only=True); ws=wb['برندهای عطر']; rows=list(ws.values); heads=[str(x or '').strip() for x in rows[0]]
    return [dict(zip(heads,r)) for r in rows[1:] if any(x is not None for x in r)]
def enrich_brand(items,rows):
    aliases={}; countries={}
    for r in rows:
        en=str(r.get('برند (English)') or r.get('Brand') or r.get('brand') or '').strip(); fa=str(r.get('برند (فارسی)') or r.get('Brand (Persian)') or '').strip()
        country=str(r.get('کشور') or r.get('Country') or r.get('Country of Origin') or r.get('Country / Region') or r.get('country_of_origin') or r.get('کشور سازنده') or '').strip()
        if en:
            aliases[normalize(en)]=en
            if country: countries[normalize(en)]=country
        if fa:
            aliases[normalize(fa)]=en or fa
            if country: countries[normalize(fa)]=country
    for p in items:
        cand=normalize(p.get('brand') or p.get('name','')); hits=[v for k,v in aliases.items() if k and (k in cand or cand in k)]
        match=hits[0] if len(set(hits))==1 else ''
        p['matched_brand']=match
        if match and not p.get('brand'): p['brand']=match
        if match and not (p.get('country') or p.get('country_of_origin')):
            p['country']=countries.get(normalize(match),''); p['country_of_origin']=p['country']
    return items

def classify_product(item):
    """Categorize from captured perfume fields only; don't invent missing attributes."""
    text=' '.join(str(item.get(k) or '') for k in ('name','description','short_description','long_description','notes','accords','family','character')).casefold()
    mapping={
      'woody':['woody','wood','oud','agarwood','cedar','sandalwood','vetiver','خشبی','عود','چوب'],
      'floral':['floral','rose','jasmine','tuberose','iris','violet','گل','رز','یاس','زنبق'],
      'amber':['amber','resin','vanilla','benzoin','warm spicy','کهربا','وانیل','رزین'],
      'fresh/citrus':['citrus','bergamot','lemon','orange','fresh','aquatic','marine','مرکبات','دریایی','خنک'],
      'aromatic':['aromatic','lavender','herbal','mint','sage','اسطوخودوس','گیاهی','نعناع'],
      'leather':['leather','suede','smoky','tobacco','چرم','دودی','تنباکو'],
      'fruity':['fruity','apple','pear','berry','cherry','peach','میوه','سیب','توت','هلو']}
    if item.get('family'):
        item.setdefault('category',str(item['family']))
    elif not item.get('category'):
        found=[cat for cat,terms in mapping.items() if any(term in text for term in terms)]
        item['category']=found[0] if found else 'other'
    return item

def write_output(items,fmt,folder,filename='products'):
    # Number products and images consistently in every export from this scrape run.
    image_no=0
    for product_no,item in enumerate(items,1):
        item.setdefault('product_number',product_no)
        if item.get('image_url') or item.get('image_path'):
            image_no+=1; item.setdefault('image_number',image_no)
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True); p=folder/f'{filename}.{fmt}'
    fields=list(items[0]) if items else ['site','name','brand','price','currency','product_url','image_url','description','short_description','long_description','availability','image_path','matched_brand','source_type']
    if fmt=='json': p.write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
    elif fmt=='csv':
        with p.open('w',newline='',encoding='utf-8-sig') as f: w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(items)
    elif fmt=='xlsx':
        from openpyxl import Workbook
        wb=Workbook(); ws=wb.active; ws.title='Products'; ws.append(fields)
        for x in items: ws.append([x.get(k,'') for k in fields])
        wb.save(p)
    else: raise ValueError('فرمت نامعتبر')
    return p
