"""Local browser dashboard for the perfume scraper. Only binds to localhost by default."""
from __future__ import annotations
import argparse, csv, json, threading, webbrowser, zipfile, io, re, email
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from .core import load_store_sources, scrape_url, load_brands, enrich_brand, write_output, create_session, translate_products, classify_product
from .scento_api import import_scento


ROOT = Path.cwd()
STORE_BOOK = ROOT / 'data' / 'perfume-online-stores.xlsx'
BRAND_BOOK = ROOT / 'data' / 'perfume-brands-by-country.xlsx'
OUTPUT_ROOT = ROOT / 'run-output'
WEB_ROOT = Path(__file__).parent / 'web'
REGIONS = ['all', 'Iran', 'UAE', 'Global', 'Niche', 'Official Brands']

STATE_LOCK = threading.RLock()
CANCEL_EVENT = threading.Event()
LOG_SEQUENCE = 0
STATE = {
    'state': 'idle', 'started_at': None, 'finished_at': None, 'current_site': '',
    'sources_total': 0, 'sources_done': 0, 'pages_checked': 0, 'products_found': 0,
    'errors': 0, 'cancel_requested': False, 'output_dir': '', 'output_file': '',
    'source_results': [], 'products': [], 'logs': [], 'details_checked': 0, 'details_total': 0, 'message': 'آماده اجرا',
}
WORKER = None

def _log(message, level='info'):
    global LOG_SEQUENCE
    stamp = datetime.now().strftime('%H:%M:%S')
    with STATE_LOCK:
        LOG_SEQUENCE += 1
        STATE['logs'].append({'id':LOG_SEQUENCE,'time':stamp,'level':level,'message':str(message)})
        STATE['logs'] = STATE['logs'][-500:]

def _state_copy():
    with STATE_LOCK:
        return json.loads(json.dumps(STATE, ensure_ascii=False))

def _sources(region='all'):
    if not STORE_BOOK.exists(): return []
    return load_store_sources(str(STORE_BOOK), region, '')

def _get_sources_for_job(config):
    mode=config.get('mode','all')
    if mode=='manual':
        urls=[x.strip() for x in str(config.get('urls','')).replace(',', '\n').replace(';','\n').splitlines() if x.strip()]
        sources=[]
        for url in urls:
            if not url.startswith(('http://','https://')): url='https://'+url
            host=urlparse(url).netloc
            if host: sources.append({'name':host,'url':url,'source_type':'manual'})
        # stable URL dedupe
        return list({x['url'].rstrip('/').lower():x for x in sources}.values())
    region=config.get('region','all')
    if mode=='selected':
        selected=config.get('selected',[])
        selection='\n'.join(str(x) for x in selected)
        return load_store_sources(str(STORE_BOOK),region,selection)
    return _sources(region)

def _worker_run(config):
    global WORKER
    started=datetime.now()
    outdir=OUTPUT_ROOT / ('ui-run-' + started.strftime('%Y%m%d-%H%M%S'))
    outdir.mkdir(parents=True,exist_ok=True)
    with STATE_LOCK:
        STATE.update({'state':'running','started_at':started.isoformat(timespec='seconds'),'finished_at':None,
            'current_site':'','sources_total':0,'sources_done':0,'pages_checked':0,'products_found':0,
            'errors':0,'details_checked':0,'details_total':0,'cancel_requested':False,'output_dir':str(outdir.relative_to(ROOT)) if outdir.is_relative_to(ROOT) else str(outdir),
            'output_file':'','source_results':[],'products':[],'message':'در حال آماده‌سازی منابع'})
    _log('اجرای جدید آغاز شد')
    try:
        sources=_get_sources_for_job(config)
    except Exception as exc:
        _log(f'خطا در خواندن فهرست منابع: {exc}','error')
        with STATE_LOCK: STATE.update({'state':'failed','message':str(exc),'finished_at':datetime.now().isoformat(timespec='seconds')})
        return
    with STATE_LOCK: STATE['sources_total']=len(sources)
    _log(f'{len(sources)} منبع برای استخراج آماده شد')
    if not sources:
        with STATE_LOCK: STATE.update({'state':'failed','message':'منبعی انتخاب نشده یا در فایل اکسل یافت نشد','finished_at':datetime.now().isoformat(timespec='seconds')})
        _log('هیچ منبعی برای اجرا پیدا نشد','error')
        return
    all_products=[]; source_reports=[]; session=create_session()
    try:
        for source in sources:
            if CANCEL_EVENT.is_set(): break
            source_row={'name':source['name'],'url':source['url'],'source_type':source.get('source_type','online_store'),
                'pages_checked':0,'products_found':0,'errors':0,'status':'running'}
            source_reports.append(source_row)
            with STATE_LOCK:
                STATE['current_site']=source['name']
                STATE['source_results']=list(source_reports)
            _log(f"شروع منبع: {source['name']} — {source['url']}")
            def page_callback(event, src_name=source['name']):
                event_type=event.get('event','page')
                with STATE_LOCK:
                    if event_type=='detail':
                        STATE['details_checked']+=1
                        STATE['details_total']=max(STATE['details_total'],int(event.get('details_total',0)))
                    else:
                        STATE['pages_checked']+=1
                        if source_reports and source_reports[-1].get('name')==src_name:
                            source_reports[-1].update({'pages_checked':event.get('pages_checked',0),'products_found':event.get('products_found',0),'errors':event.get('errors',0)})
                            STATE['source_results']=list(source_reports)
                    STATE['products_found']=len(all_products)+int(event.get('products_found',0))
                    preview=list(event.get('products_preview',[]))
                    if preview: STATE['products']=all_products[-120:]+preview[-30:]
                    STATE['current_site']=src_name
                if event_type=='detail':
                    _log(f"تکمیل اطلاعات محصول: {event.get('details_checked',0)}/{event.get('details_total',0)} — {event.get('page','')}")
                else:
                    page_status=event.get('status','running')
                    _log(f"صفحه {event.get('pages_checked',0)}: {event.get('page','')} | محصولات این سایت: {event.get('products_found',0)} | {page_status}", 'warning' if page_status=='error' else 'info')
            try:
                got,stats=scrape_url(source['url'],source['name'],int(config.get('limit_per_site',10)),
                    bool(config.get('download_images')),outdir/'images',float(config.get('delay',1.3)),
                    int(config.get('max_pages',12)),session=session,progress_callback=page_callback,cancel_event=CANCEL_EVENT,enrich_details=bool(config.get('enrich_details',True)))
                for item in got: item['source_type']=source.get('source_type','online_store')
                source_row.update(stats); source_row['status']='cancelled' if CANCEL_EVENT.is_set() else ('partial' if got and stats.get('errors',0) else ('ok' if got else ('error' if stats.get('errors',0) else 'no_products')))
                all_products.extend(got)
                _log(f"پایان {source['name']}: {len(got)} محصول، {stats.get('pages_checked',0)} صفحه")
            except Exception as exc:
                source_row['status']='error'; source_row['error']=str(exc); source_row['errors']=source_row.get('errors',0)+1
                _log(f"خطا در {source['name']}: {exc}",'error')
            with STATE_LOCK:
                STATE['sources_done']+=1
                STATE['errors']+=source_row.get('errors',0)
                STATE['source_results']=list(source_reports)
                STATE['products_found']=len(all_products)
                STATE['products']=all_products[-150:]
    finally:
        session.close()
    # Deduplicate by product URL, preserving the first complete record.
    dedup={}
    for item in all_products:
        key=item.get('product_url') or f"{item.get('site')}|{item.get('name')}"
        if key not in dedup or (not dedup[key].get('image_url') and item.get('image_url')): dedup[key]=item
    all_products=list(dedup.values())
    all_products=[classify_product(item) for item in all_products]
    try:
        if BRAND_BOOK.exists(): enrich_brand(all_products,load_brands(str(BRAND_BOOK)))
    except Exception as exc: _log(f'تطبیق برندها انجام نشد: {exc}','warning')
    if config.get('translate_fa'):
        if not __import__('os').environ.get('LIBRETRANSLATE_URL'):
            _log('ترجمه فعال است اما LIBRETRANSLATE_URL تنظیم نشده؛ متن اصلی حفظ شد و ترجمه‌ها خالی می‌مانند','warning')
        else:
            _log('ترجمه فارسی متن‌های محصول آغاز شد')
            try:
                translated=translate_products(all_products)
                _log(f'ترجمه انجام شد: {translated} فیلد؛ متن اصلی در خروجی حفظ شده')
            except Exception as exc: _log(f'خطا در ترجمه: {exc}','warning')
    # Auto-publish scraped products to the Larsi Supabase catalogue when configured.
    supabase_sync_report={'status':'skipped','reason':'Supabase secrets not configured'}
    import os
    if os.getenv('SUPABASE_URL') and (os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY')):
        try:
            from .supabase_sync import sync_products
            supabase_sync_report={'status':'ok', **sync_products(all_products)}
            _log(f"ذخیره خودکار در Supabase لارسی موفق: {supabase_sync_report['uploaded']} محصول", 'info')
        except Exception as exc:
            supabase_sync_report={'status':'error','error':str(exc)}
            _log(f"خطا در ذخیره Supabase: {exc}", 'error')
    fmt=config.get('format','xlsx')
    try:
        product_path=write_output(all_products,fmt,outdir)
        report={'mode':config.get('mode'),'region':config.get('region'),'sources_total':len(sources),
            'total_products':len(all_products),'cancelled':CANCEL_EVENT.is_set(),'source_results':source_reports,
            'supabase_sync':supabase_sync_report}
        (outdir/'run-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        with (outdir/'source-summary.csv').open('w',newline='',encoding='utf-8-sig') as fp:
            cols=['name','url','source_type','status','pages_checked','products_found','errors','error']
            writer=csv.DictWriter(fp,fieldnames=cols); writer.writeheader(); writer.writerows(source_reports)
    except Exception as exc:
        _log(f'خطا هنگام ساخت خروجی: {exc}','error')
        with STATE_LOCK: STATE.update({'state':'failed','message':str(exc),'finished_at':datetime.now().isoformat(timespec='seconds'),'current_site':''})
        return
    with STATE_LOCK:
        STATE['products']=all_products[-150:]
        STATE['products_found']=len(all_products)
        STATE['output_file']=str(product_path.relative_to(ROOT)) if product_path.is_relative_to(ROOT) else str(product_path)
        STATE['finished_at']=datetime.now().isoformat(timespec='seconds')
        STATE['current_site']=''
        STATE['state']='cancelled' if CANCEL_EVENT.is_set() else ('finished' if not any(x['status'] in ('error','partial') for x in source_reports) else 'finished_with_errors')
        STATE['message']=f"پایان اجرا؛ {len(all_products)} محصول یافت شد"
    _log(f"خروجی نهایی ساخته شد: {product_path}")
    _log('عملیات با درخواست کاربر متوقف شد' if CANCEL_EVENT.is_set() else 'عملیات تکمیل شد')


BANK_LOCK=threading.RLock()
BANK_STATE={'state':'idle','products':0,'current':'','logs':[],'unique_products':0,'input_products':0,'duplicates':0,'files_processed':0,'message':'','downloads':[]}
BANK_DIR=OUTPUT_ROOT/'databank'
BANK_FIELDS=['name','brand','price','currency','product_url','image_url','short_description','long_description','description','site','matched_brand','source_type','availability','image_path','country','country_of_origin','category','family','secondary_family','top','heart','base','notes','accords','perfumer','year','season','concentration']
def _bank_log(s):
    with BANK_LOCK: BANK_STATE['logs'].append(str(s)); BANK_STATE['logs']=BANK_STATE['logs'][-100:]
def _bank_rows_from_json(obj):
    if isinstance(obj,list): return [x for x in obj if isinstance(x,dict)]
    if isinstance(obj,dict):
        for k in ('products','items','data','results','records'):
            if isinstance(obj.get(k),list): return [x for x in obj[k] if isinstance(x,dict)]
        if all(not isinstance(v,(dict,list)) for v in obj.values()): return [obj]
    return []
def _read_bank_file(name,data):
    ext=Path(name).suffix.lower()
    if ext=='.json': return _bank_rows_from_json(json.loads(data.decode('utf-8-sig')))
    if ext in ('.xlsx','.xlsm'):
        from openpyxl import load_workbook
        wb=load_workbook(io.BytesIO(data),read_only=True,data_only=True); rows=[]
        for ws in wb.worksheets:
            vals=list(ws.iter_rows(values_only=True))
            if not vals: continue
            headers=[str(x or '').strip() for x in vals[0]]
            for row in vals[1:]:
                item={headers[i]:row[i] for i in range(min(len(headers),len(row))) if headers[i] and row[i] is not None}
                if item: rows.append(item)
        return rows
    if ext=='.csv':
        text=data.decode('utf-8-sig'); return list(csv.DictReader(io.StringIO(text)))
    raise ValueError(f'فرمت پشتیبانی نشده: {name}')
def _bank_norm_key(row):
    # Product identity uses normalized brand+name first; URLs are fallback only.
    name=re.sub(r'[^a-z0-9\u0600-\u06ff]+','',str(row.get('name') or row.get('product') or row.get('title') or '').casefold())
    brand=re.sub(r'[^a-z0-9\u0600-\u06ff]+','',str(row.get('brand') or row.get('matched_brand') or '').casefold())
    if name: return 'name:'+brand+'|'+name
    url=str(row.get('product_url') or row.get('url') or '').strip().lower().rstrip('/')
    return 'url:'+url if url else None
def _bank_clean(row):
    aliases={'product':'name','title':'name','product_name':'name','productname':'name','brand_name':'brand','url':'product_url','product_link':'product_url','link':'product_url','image':'image_url','image_link':'image_url','photo':'image_url','desc':'description','details':'long_description','summary':'short_description','store':'site','source':'site','country_of_origin':'country','origin_country':'country','made_in':'country','manufacturer_country':'country','scent_family':'family','categories':'category'}
    out={}
    for k,v in row.items():
        key=str(k or '').strip().lower().replace(' ','_')
        key=aliases.get(key,key)
        if v is None: continue
        if isinstance(v,float) and v.is_integer(): v=int(v)
        value=str(v).strip() if not isinstance(v,(int,float,bool)) else v
        if value not in ('',None): out[key]=value
    # copy description into short when available, and vice versa only when missing
    if out.get('description') and not out.get('short_description'): out['short_description']=out['description']
    if out.get('long_description') and not out.get('description'): out['description']=out['long_description']
    return classify_product(out)
def _bank_merge(rows):
    merged={}; duplicates=0
    for raw in rows:
        r=_bank_clean(raw); key=_bank_norm_key(r)
        if not key: continue
        if key not in merged: merged[key]=r; continue
        duplicates+=1; old=merged[key]
        # Keep existing values; fill blanks. Prefer richer descriptions if longer.
        for k,v in r.items():
            if not old.get(k): old[k]=v
            elif k in ('description','short_description','long_description') and len(str(v))>len(str(old.get(k,''))): old[k]=v
        # combine distinct source provenance values
        if r.get('site') and r['site']!=old.get('site'):
            old['site']=('; '.join(dict.fromkeys([str(old.get('site','')),str(r['site'])])).strip('; '))
    return list(merged.values()),duplicates
def _bank_save(rows,folder_name='bank-final'):
    BANK_DIR.mkdir(parents=True,exist_ok=True)
    master_dir=BANK_DIR/'master'; master_dir.mkdir(parents=True,exist_ok=True)
    master_json=master_dir/'perfume-database.json'
    existing=[]
    if master_json.exists():
        try: existing=_bank_rows_from_json(json.loads(master_json.read_text(encoding='utf-8')))
        except Exception: existing=[]
    batch, batch_duplicates=_bank_merge(rows)
    combined,duplicates=_bank_merge(existing+rows)
    snapshot=BANK_DIR/folder_name; snapshot.mkdir(parents=True,exist_ok=True)
    # Master database accumulates across import and manual-link runs, while a dated snapshot preserves each run.
    for ext in ('json','xlsx','csv'):
        write_output(combined,ext,str(master_dir),filename='perfume-database')
        write_output(batch,ext,str(snapshot),filename='batch-products')
    outputs=[{'label':'MASTER '+ext.upper(),'url':'/files/run-output/databank/master/perfume-database.'+ext} for ext in ('json','xlsx','csv')]
    return combined,duplicates,outputs

def _auto_sync_bank(rows):
    """Publish imported bank rows to the Larsi Supabase table when credentials exist."""
    import os
    if not (os.getenv('SUPABASE_URL') and (os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY'))):
        return {'status':'skipped','reason':'Supabase credentials are not configured'}
    from .supabase_sync import sync_products
    return {'status':'ok', **sync_products(rows)}



class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def _json(self, data, code=200):
        raw=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def _read_json(self):
        length=min(int(self.headers.get('Content-Length','0')),1_000_000)
        try: return json.loads(self.rfile.read(length) or b'{}')
        except Exception: return {}
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/status': self._json(_state_copy()); return
        if path=='/api/databank/status':
            with BANK_LOCK: self._json(dict(BANK_STATE)); return
        if path=='/api/sources':
            region=parse_qs(urlparse(self.path).query).get('region',['all'])[0]
            try: self._json({'regions':REGIONS,'sources':_sources(region)})
            except Exception as exc: self._json({'error':str(exc)},500)
            return
        if path=='/api/files':
            base=OUTPUT_ROOT.resolve(); found=[]
            if base.exists():
                for f in sorted(base.rglob('*')):
                    if f.is_file() and f.resolve().is_relative_to(base): found.append({'name':str(f.relative_to(ROOT)),'size':f.stat().st_size})
            self._json({'files':found[-500:]}); return
        if path=='/api/download-zip':
            base=OUTPUT_ROOT.resolve()
            if not base.exists() or not any(x.is_file() for x in base.rglob('*')):
                self._json({'error':'هنوز فایل خروجی برای بسته‌بندی وجود ندارد'},404); return
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
                for f in base.rglob('*'):
                    if f.is_file() and f.resolve().is_relative_to(base): archive.write(f,f.relative_to(base))
            payload=stream.getvalue(); self.send_response(200); self.send_header('Content-Type','application/zip'); self.send_header('Content-Disposition','attachment; filename="perfume-scraper-outputs.zip"'); self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload); return
        if path.startswith('/files/'): 
            rel=unquote(path[len('/files/'):])
            target=(ROOT/rel).resolve()
            base=OUTPUT_ROOT.resolve()
            if not target.is_relative_to(base) or not target.is_file(): self._json({'error':'not found'},404); return
            data=target.read_bytes(); mime='application/octet-stream'
            if target.suffix.lower() in ('.jpg','.jpeg'): mime='image/jpeg'
            elif target.suffix.lower()=='.png': mime='image/png'
            elif target.suffix.lower()=='.webp': mime='image/webp'
            elif target.suffix.lower()=='.gif': mime='image/gif'
            self.send_response(200); self.send_header('Content-Type',mime); self.send_header('Content-Disposition',f'attachment; filename="{target.name}"'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data); return
        if path=='/' or path=='/index.html':
            data=(WEB_ROOT/'index.html').read_bytes(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data); return
        if path in ('/app.js','/style.css'):
            data=(WEB_ROOT/path.lstrip('/')).read_bytes(); typ='text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8'; self.send_response(200); self.send_header('Content-Type',typ); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data); return
        self._json({'error':'not found'},404)
    def do_POST(self):
        global WORKER
        path=urlparse(self.path).path; data={} if path=='/api/databank/import' else self._read_json()
        if path=='/api/start':
            with STATE_LOCK:
                if STATE['state']=='running': self._json({'error':'یک عملیات در حال اجرا است'},409); return
            if data.get('mode') not in ('all','selected','manual'): self._json({'error':'نوع انتخاب منبع نامعتبر است'},400); return
            try:
                int(data.get('limit_per_site',10)); int(data.get('max_pages',12)); float(data.get('delay',1.3))
                if int(data.get('limit_per_site',10))<0 or int(data.get('max_pages',12))<1 or float(data.get('delay',1.3))<0: raise ValueError('مقادیر باید غیرمنفی باشند و صفحات حداقل ۱ باشد')
            except Exception as exc: self._json({'error':str(exc)},400); return
            if data.get('mode')=='manual' and not str(data.get('urls','')).strip(): self._json({'error':'لینک دستی وارد کنید'},400); return
            if data.get('mode')=='selected' and not data.get('selected'): self._json({'error':'حداقل یک فروشگاه انتخاب کنید'},400); return
            with STATE_LOCK: STATE['state']='starting'
            CANCEL_EVENT.clear()
            WORKER=threading.Thread(target=_worker_run,args=(data,),daemon=True); WORKER.start()
            self._json({'ok':True,'message':'شروع شد'}); return

        if path=='/api/databank/import':
            ctype=self.headers.get('Content-Type',''); length=int(self.headers.get('Content-Length','0'))
            if length<=0 or length>80*1024*1024: self._json({'error':'حجم درخواست نامعتبر است؛ مجموع فایل‌ها حداکثر ۸۰ مگابایت'},413); return
            raw=self.rfile.read(length)
            try:
                boundary_match=re.search(r'boundary=([^;]+)',ctype)
                if not boundary_match: raise ValueError('مرز فایل multipart نامعتبر است')
                boundary=boundary_match.group(1).strip(' \u0022') .encode()
                files=[]
                for segment in raw.split(b'--'+boundary):
                    segment=segment.strip(b'\r\n')
                    if not segment or segment==b'--': continue
                    header_blob,payload=segment.split(b'\r\n\r\n',1)
                    header_text=header_blob.decode('latin-1',errors='replace')
                    filename_match=re.search(r'filename=\"([^\"]+)\"|filename=([^;\r\n]+)',header_text,re.I)
                    if filename_match:
                        filename=(filename_match.group(1) or filename_match.group(2)).strip()
                        payload=payload.rstrip(b'\r\n')
                        files.append((filename,payload))
                if not files: raise ValueError('فایل آپلود شده دریافت نشد')
                if len(files)>10: raise ValueError('حداکثر ۱۰ فایل در هر نوبت مجاز است')
                rows=[]
                for name,data in files:
                    rows.extend(_read_bank_file(name,data))
                merged,dups,downloads=_bank_save(rows,datetime.now().strftime('import-%Y%m%d-%H%M%S'))
                sync_report=_auto_sync_bank(rows)
                self._json({'ok':True,'supabase_sync':sync_report,'files_processed':len(files),'input_products':len(rows),'unique_products':len(merged),'duplicates':dups,'message':'ادغام انجام شد؛ فایل‌ها به بانک اطلاعاتی تبدیل شدند.','downloads':downloads}); return
            except Exception as exc: self._json({'error':str(exc)},400); return
        if path=='/api/databank/scrape':
            with BANK_LOCK:
                if BANK_STATE.get('state')=='running': self._json({'error':'استخراج بانک در حال اجراست'},409); return
                BANK_STATE.update({'state':'running','products':0,'current':'در صف شروع','logs':[],'message':'در حال استخراج لینک‌ها','downloads':[]})
            urls=[x.strip() for x in str(data.get('urls','')).replace(';','\n').replace(',','\n').splitlines() if x.strip()]
            urls=list(dict.fromkeys(urls))
            if not urls:
                with BANK_LOCK: BANK_STATE.update({'state':'idle'})
                self._json({'error':'لینک وارد نشده'},400); return
            limit=max(0,int(data.get('limit',100))); pages=max(1,int(data.get('pages',20)))
            def run_bank():
                allrows=[]
                for url in urls:
                    if not url.startswith(('http://','https://')): url='https://'+url
                    host=urlparse(url).netloc
                    with BANK_LOCK: BANK_STATE['current']=url
                    _bank_log('شروع: '+url)
                    try:
                        products,stats=scrape_url(url,site_name=host,limit=limit,download_images=False,delay=1.2,max_pages=pages,session=create_session(),enrich_details=True)
                        allrows.extend(products); _bank_log(f"{host}: {len(products)} محصول، {stats.get('pages_checked',0)} صفحه، {stats.get('errors',0)} خطا")
                    except Exception as exc: _bank_log(f'خطا در {host}: {exc}')
                try:
                    merged,dups,downloads=_bank_save(allrows,datetime.now().strftime('links-%Y%m%d-%H%M%S'))
                    sync_report=_auto_sync_bank(allrows)
                    _bank_log(f"ارسال به Supabase: {sync_report.get('uploaded',0)} محصول ({sync_report.get('status')})")
                    with BANK_LOCK: BANK_STATE.update({'state':'finished','products':len(allrows),'input_products':len(allrows),'unique_products':len(merged),'duplicates':dups,'files_processed':len(urls),'message':'استخراج و ذخیره بانک تمام شد','downloads':downloads,'current':''})
                except Exception as exc:
                    _bank_log('خطا در ساخت فایل خروجی: '+str(exc))
                    with BANK_LOCK: BANK_STATE.update({'state':'failed','message':str(exc)})
            threading.Thread(target=run_bank,daemon=True).start(); self._json({'ok':True,'state':'running'}); return

        if path=='/api/databank/scento-import':
            with BANK_LOCK:
                if BANK_STATE.get('state')=='running': self._json({'error':'بانک در حال اجرای عملیات است'},409); return
                BANK_STATE.update({'state':'running','products':0,'current':'در حال جستجو در API سنتو','logs':[],'message':'شروع استخراج API','downloads':[]})
            queries=str(data.get('queries','')).strip()
            if not queries:
                with BANK_LOCK: BANK_STATE.update({'state':'idle'})
                self._json({'error':'عبارت‌های جستجو را وارد کنید'},400); return
            limit=max(1,min(int(data.get('limit',150)),1000))
            delay=max(0.15,min(float(data.get('delay',0.35)),5.0))
            def run_scento():
                try:
                    def api_progress(message):
                        with BANK_LOCK:
                            BANK_STATE['current']=str(message)
                            BANK_STATE['logs']=(BANK_STATE.get('logs',[])+[str(message)])[-100:]
                    items,stats=import_scento(queries,limit=limit,progress=api_progress,request_delay=delay)
                    merged,dups,downloads=_bank_save(items,datetime.now().strftime('scento-api-%Y%m%d-%H%M%S'))
                    sync_report=_auto_sync_bank(items)
                    api_progress(f"ذخیره Supabase: {sync_report.get('uploaded',0)} محصول ({sync_report.get('status')})")
                    with BANK_LOCK: BANK_STATE.update({'state':'finished','products':len(items),'input_products':len(items),'unique_products':len(merged),'duplicates':dups,'files_processed':stats.get('queries',0),'message':f"استخراج API سنتو انجام شد؛ {len(items)} محصول دریافت شد",'downloads':downloads,'current':'','api_stats':stats,'supabase_sync':sync_report})
                except Exception as exc:
                    api_progress('خطا: '+str(exc))
                    with BANK_LOCK: BANK_STATE.update({'state':'failed','message':str(exc),'current':''})
            threading.Thread(target=run_scento,daemon=True).start(); self._json({'ok':True,'state':'running'}); return

        if path=='/api/cancel':
            with STATE_LOCK:
                if STATE['state'] not in ('running','starting'): self._json({'error':'عملیاتی برای توقف وجود ندارد'},409); return
                STATE['cancel_requested']=True
            CANCEL_EVENT.set(); _log('درخواست توقف دریافت شد','warning'); self._json({'ok':True}); return
        self._json({'error':'not found'},404)

def main():
    parser=argparse.ArgumentParser(description='Perfume Scraper local web dashboard')
    parser.add_argument('--host',default='127.0.0.1',help='پیش‌فرض فقط روی سیستم خودتان')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    server=ThreadingHTTPServer((args.host,args.port),DashboardHandler)
    url=f'http://{args.host}:{args.port}'
    print(f'Perfume Scraper dashboard: {url}\nبرای خروج Ctrl+C را فشار دهید.')
    if not args.no_browser and args.host in ('127.0.0.1','localhost'): threading.Timer(.7,lambda:webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nسرور بسته شد.')
    finally: server.server_close()

if __name__=='__main__': main()
