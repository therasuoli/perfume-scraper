"""Optional automatic upload of scraped products into the Larsi Supabase catalogue."""
from __future__ import annotations
import hashlib
import os
import re
import requests

def _slug(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "-", text).strip("-")
    return text[:80] or "perfume"

def to_payload(product: dict) -> dict:
    name = str(product.get("name") or "").strip()
    brand = str(product.get("brand") or product.get("matched_brand") or "").strip()
    url = str(product.get("product_url") or "").strip()
    seed = url or f"{brand}|{name}"
    ident = _slug(seed)
    if len(ident) > 80 or not ident:
        ident = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    payload = {
        "name": name, "brand": brand,
        "price": product.get("price") or "",
        "currency": product.get("currency") or "",
        "image": product.get("image_url") or "",
        "image_url": product.get("image_url") or "",
        "short_description": product.get("short_description") or product.get("description") or "",
        "long_description": product.get("long_description") or product.get("description") or "",
        "description": product.get("long_description") or product.get("description") or product.get("short_description") or "",
        "product_url": url, "site": product.get("site") or "",
        "availability": product.get("availability") or "",
        "source_type": product.get("source_type") or "",
        "country": product.get("country") or product.get("country_of_origin") or "",
        "country_of_origin": product.get("country_of_origin") or product.get("country") or "",
        "category": product.get("category") or product.get("family") or "",
        "secondary_family": product.get("secondary_family") or "",
        "character": product.get("character") or product.get("accords") or [],
        "concentration": product.get("concentration") or "",
        "scraped_at": product.get("scraped_at") or "",
    }
    # Add optional fields only when present; don't overwrite app fields with nulls.
    for key in ("year", "gender", "family", "top", "heart", "base", "notes", "accords", "perfumer", "season", "secondary_family", "product_number", "image_number"):
        if product.get(key) not in (None, "", [], {}):
            payload[key] = product[key]
    return {"id": ident, "payload": payload}

def _norm_identity(product: dict) -> str:
    brand = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "", str(product.get("brand") or product.get("matched_brand") or "").casefold())
    name = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "", str(product.get("name") or "").casefold())
    return f"{brand}|{name}" if name else ""

def _fetch_existing(endpoint, headers, page_size=1000):
    existing=[]; offset=0
    while True:
        h=dict(headers); h["Range"]=f"{offset}-{offset+page_size-1}"; h["Range-Unit"]="items"
        response=requests.get(endpoint,headers=h,params={"select":"id,payload"},timeout=40)
        if not response.ok: raise RuntimeError(f"Supabase duplicate-check failed ({response.status_code}): {response.text[:400]}")
        batch=response.json() or []; existing.extend(batch)
        if len(batch)<page_size: break
        offset+=page_size
    return existing

def sync_products(products: list[dict], *, url: str | None = None, key: str | None = None,
                 table: str | None = None, batch_size: int = 100) -> dict:
    url=(url or os.getenv("SUPABASE_URL","https://eixzihvihoammvremxrl.supabase.co")).rstrip("/")
    key=key or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    table=table or os.getenv("SUPABASE_TABLE","perfumes")
    if not url or not key: raise RuntimeError("Supabase sync needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables")
    incoming=[p for p in products if p.get("name")]
    if not incoming: return {"uploaded":0,"skipped":len(products),"batches":0,"duplicates_in_input":0,"duplicates_in_database":0}
    endpoint=f"{url}/rest/v1/{table}"
    headers={"apikey":key,"Authorization":f"Bearer {key}","Content-Type":"application/json","Prefer":"resolution=merge-duplicates,return=minimal"}
    existing_rows=_fetch_existing(endpoint,headers)
    by_identity={}; by_url={}; max_product=0; max_image=0; db_duplicates_existing=0; db_duplicates_existing=0
    for row in existing_rows:
        payload=row.get("payload") or {}; identity=_norm_identity(payload)
        product_url=str(payload.get("product_url") or "").strip().lower().rstrip("/")
        if identity:
            if identity in by_identity: db_duplicates_existing+=1
            else: by_identity[identity]=row
        if product_url: by_url.setdefault(product_url,row)
        try: max_product=max(max_product,int(payload.get("product_number") or 0))
        except (TypeError,ValueError): pass
        try: max_image=max(max_image,int(payload.get("image_number") or 0))
        except (TypeError,ValueError): pass
    merged={}; input_dups=0
    for product in incoming:
        identity=_norm_identity(product); urlkey=str(product.get("product_url") or "").strip().lower().rstrip("/")
        key_identity=identity or ("url:"+urlkey if urlkey else "")
        if not key_identity: continue
        if key_identity not in merged: merged[key_identity]=dict(product); continue
        input_dups+=1; old=merged[key_identity]
        for field,value in product.items():
            if value in (None,"",[],{}): continue
            if not old.get(field) or (field in ("description","short_description","long_description") and len(str(value))>len(str(old.get(field) or ""))): old[field]=value
    output=[]; db_dups=0; next_product=max_product; next_image=max_image
    for product in merged.values():
        identity=_norm_identity(product); urlkey=str(product.get("product_url") or "").strip().lower().rstrip("/")
        old=by_identity.get(identity) if identity else None
        if not old and urlkey: old=by_url.get(urlkey)
        payload=to_payload(product)["payload"]
        if old:
            db_dups+=1; old_payload=old.get("payload") or {}
            if not old_payload.get("product_number"):
                next_product+=1; old_payload["product_number"]=next_product
            for field,value in payload.items():
                if value in (None,"",[],{}): continue
                if not old_payload.get(field) or (field in ("description","short_description","long_description") and len(str(value))>len(str(old_payload.get(field) or ""))): old_payload[field]=value
            row={"id":old.get("id"),"payload":old_payload}
        else:
            next_product+=1; payload["product_number"]=next_product
            row={"id":to_payload(product)["id"],"payload":payload}
        if row["payload"].get("image_url") and not row["payload"].get("image_number"):
            next_image+=1; row["payload"]["image_number"]=next_image
        output.append(row)
    uploaded=0
    for i in range(0,len(output),batch_size):
        batch=output[i:i+batch_size]; response=requests.post(endpoint+"?on_conflict=id",json=batch,headers=headers,timeout=40)
        if not response.ok: raise RuntimeError(f"Supabase upsert failed ({response.status_code}): {response.text[:500]}")
        uploaded+=len(batch)
    return {"uploaded":uploaded,"skipped":len(products)-len(incoming),"batches":(len(output)+batch_size-1)//batch_size,
            "duplicates_in_input":input_dups,"duplicates_in_database":db_dups,"duplicates_already_in_database":db_duplicates_existing,
            "existing_database_rows_checked":len(existing_rows),"numbered_products":next_product-max_product,"numbered_images":next_image-max_image}
