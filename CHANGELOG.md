## 0.6.3 — Database duplicate review + sequential numbering
- Before Supabase writes, reads existing `perfumes` rows in pages and compares normalized brand/name identities and product URLs.
- Avoids adding an incoming duplicate as a new record; updates the matched record and fills missing values, preferring longer descriptions.
- Merges duplicate products in the same extraction batch by normalized brand/name, regardless of URL.
- Reports duplicates in input, duplicates in the database, and previously existing duplicate rows. Does not destructively delete old records.
- Adds sequential `product_number` and image-only `image_number` fields to export and Supabase payloads.
- Downloaded images use an independent `image-00001.ext` sequence.

## 0.6.3 — Database duplicate review + sequential numbering
- Before Supabase writes, reads the existing `perfumes` catalog in paged requests and compares normalized brand/name identities and product URLs.
- Prevents adding an incoming product as a new row when it already exists; updates the matching row and fills missing data, preferring longer descriptions.
- Merges duplicate products in the same extraction batch by normalized brand/name, regardless of product URL.
- Reports duplicate counts in input and already-existing database records; does not destructively delete old duplicate records.
- Adds sequential `product_number` and image-only `image_number` fields to export and Supabase payloads.
- Saved image files use the independent `image-00001.ext` numbering sequence.

# 0.6.1\n\n- افزودن ذخیره خودکار محصولات استخراج‌شده در Supabase لارسی (REST upsert) با env secrets.\n- Sync خودکار در CLI، داشبورد محلی و GitHub Actions؛ بدون قرار دادن Service Role در کد.\n- شناسه پایدار برای جلوگیری از duplicate هنگام استخراج دوباره.\n\n# Changelog

## 0.6.0 — Smart Edition
- Improved transient network failure handling with adaptive timeout retries and backoff for HTTP 429/503.
- Added animated, responsive live dashboard charts for crawl trends and source health.
- Added opt-in Persian description translation using a LibreTranslate-compatible endpoint, preserving source fields.
- Documented translation setup and safety boundaries.

## 0.6.2 — Smart product fields + Scento API import
- Added a dedicated Scento REST API search-import card in the dashboard (search terms, product cap, request delay).
- Imports perfume portraits, house/brand, country where API provides it, family, secondary family, note pyramid, character/accord tags, concentration, year, perfumer, short/long text and page image metadata.
- Deduplicates API hits, stores master bank exports, and auto-upserts imported products into Supabase when service credentials are configured.
- Added category inference for scraped/imported products; country is left blank when it cannot be verified.
- Expanded Supabase payload mapping and included safe SQL Editor setup/index/policy script.
