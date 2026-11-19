# Perfume Scraper — Hadi Rasouli

ابزار پژوهشی و آموزشی استخراج محصولات عطر از صفحات عمومی وب. پروژه دو مسیر اجرا دارد: **پنل گرافیکی محلی در مرورگر** و **اجرای ابری با GitHub Actions**. نیازی به Node.js ندارد.


## امکانات اصلی
- داشبورد وب فارسی، راست‌چین و واکنش‌گرا
- مشاهده زنده گزارش‌ها، صفحات بررسی‌شده، تعداد محصولات و خطاها
- انتخاب منبع از شیت‌های Iran، UAE، Global، Niche و Official Brands
- انتخاب چند فروشگاه با جستجو، انتخاب همه و پاک کردن انتخاب
- وارد کردن چند لینک دستی برای سایت یا صفحه مشخص
- استخراج JSON-LD، کارت‌های رایج محصول و Microdata
- فیلدهای نام محصول، برند، قیمت، ارز، توضیح کوتاه و بلند، موجودی، لینک محصول و لینک تصویر
- تکمیل خودکار اطلاعات با مراجعه اختیاری به صفحه محصول (نام، برند، تصویر، قیمت و توضیحات)
- پیش‌نمایش محصولات و تصویرها در داشبورد
- توقف خزش در حین اجرا
- دانلود اختیاری تصاویر
- پیش‌نمایش توضیح کوتاه و بازکردن توضیحات کامل هر محصول در داشبورد
- دانلود یک‌جای تمام خروجی‌ها، گزارش‌ها و تصاویر به صورت ZIP از داشبورد
- خروجی Excel، CSV و JSON به همراه `run-report.json` و `source-summary.csv`
- Retry برای خطاهای موقت HTTP و تست‌های آفلاین
- GitHub Actions با Python 3.10 تا 3.13


## اجرا با داشبورد مرورگر (محلی)

### 1) نصب Python
Python 3.10 یا بالاتر را نصب کنید. در نصب Windows گزینه **Add Python to PATH** را فعال کنید.

### 2) استخراج ZIP
ZIP را استخراج کنید و Terminal / Command Prompt را در پوشه اصلی پروژه باز کنید (همان جایی که `pyproject.toml` قرار دارد).

### 3) نصب ابزار

```bash
python -m pip install -e .
```

### 4) اجرای پنل

در Windows می‌توانید فایل `start-dashboard.bat` را دوبار کلیک کنید؛ نصب وابستگی‌ها و بازکردن پنل انجام می‌شود. یا در ترمینال: `perfume-scraper-ui`.

```bash
perfume-scraper-ui
```

مرورگر روی `http://127.0.0.1:8765` باز می‌شود. اگر خودکار باز نشد، همین آدرس را دستی باز کنید. پنل فقط روی سیستم محلی در دسترس است؛ برای پایان دادن به سرور در ترمینال `Ctrl+C` بزنید.

### تنظیمات پنل
- **انتخاب شیت:** همه فروشگاه‌ها یا یک منطقه (ایران، امارات، Global، نیش یا برندهای رسمی)
- **فروشگاه‌های انتخابی:** یک منطقه را انتخاب کنید، فروشگاه‌ها را جستجو و تیک بزنید
- **لینک دستی:** چند URL عمومی را در کادر وارد کنید، هر URL در یک خط
- **حد محصول از هر سایت:** صفر یعنی بدون سقف
- **حد صفحات:** تعداد صفحات مجاز بررسی در هر سایت
- **فاصله درخواست:** برای کاهش فشار به سایت‌ها مقدار مناسب تعیین کنید
- **فرمت:** Excel / CSV / JSON
- **تکمیل توضیحات محصول:** بازدید اختیاری از صفحات محصولات برای دریافت توضیحات کوتاه و کامل، برند و تصویر؛ حداکثر ۴۰ صفحه محصول از هر فروشگاه در این مرحله برای کاهش فشار روی سایت
- **دانلود تصویر:** ذخیره فایل تصویر در فولدر `images` داخل خروجی اجرا
- **دانلود خروجی‌ها:** فهرست فایل‌ها را در پنل باز کنید یا از «دانلود همه خروجی‌ها ZIP» استفاده کنید


## اجرای GitHub Actions

1. فایل‌های پروژه را در ریشه Repository بارگذاری کنید، شامل پوشه مخفی `.github`.
2. از تب **Actions** مطمئن شوید Workflowها فعال هستند.
3. Workflow **Run Perfume Scraper** را باز کنید و **Run workflow** بزنید.
4. منبع و تنظیمات را انتخاب کنید؛ خروجی در بخش **Artifacts** همان اجرا قرار می‌گیرد.


### ورودی‌های Workflow

| گزینه | شرح |
|---|---|
| `source_list` | همه فروشگاه‌ها، فروشگاه‌های انتخابی، لینک دستی، یا حالت‌های قدیمی |
| `store_region` | all / Iran / UAE / Global / Niche / Official Brands |
| `store_selection` | نام، URL یا دامنه فروشگاه‌ها؛ چند مقدار را با کاما جدا کنید |
| `urls` | URLهای دستی، هر کدام در یک خط یا جداشده با کاما |
| `limit` | تعداد محصول از هر سایت؛ صفر بدون محدودیت |
| `max_pages` | سقف صفحات هر سایت |
| `output_format` | xlsx، csv یا json |
| `enrich_details` | مراجعه به صفحه محصول برای تکمیل توضیحات کوتاه/بلند، تصویر، برند و قیمت |
| `download_images` | دانلود تصاویر محصول و قرار دادن در Artifact |


## اجرای خط فرمان (اختیاری)

```bash
perfume-scraper --source-list all_stores --stores-xlsx data/perfume-online-stores.xlsx --store-region all --limit 10 --max-pages 12 --format xlsx --output run-output --verbose
```

لینک دستی:

```bash
perfume-scraper --source-list manual_urls --urls "https://example.com/perfumes" --limit 10 --max-pages 12 --format xlsx --output run-output --enrich-details
```


## تست‌های آفلاین

```bash
python -m pip install -e ".[dev]"
python -m pytest -vv
```

تست‌ها ساختار منابع، فیلتر انتخاب فروشگاه، استخراج محصول و تصویر، callback پیشرفت و توقف را بررسی می‌کنند. تست‌ها به سایت‌های خارجی درخواست نمی‌فرستند.


## فایل‌های منبع
- `data/perfume-online-stores.xlsx` — منابع فروشگاهی و منطقه‌ها
- `data/perfume-brands-by-country.xlsx` — فهرست برندها و منابع قبلی؛ برای تکمیل تطبیق برند استفاده می‌شود


## خروجی هر اجرا
- `products.xlsx` / `products.csv` / `products.json`
- `run-report.json` — خلاصه اجرا و وضعیت هر منبع
- `source-summary.csv` — گزارش قابل بازکردن در Excel
- `images/` — در صورت فعال‌کردن دانلود تصویر


## حریم استفاده و محدودیت
این ابزار به صفحات عمومی درخواست HTTP می‌فرستد و از ورود به حساب‌ها، دور زدن CAPTCHA یا عبور از کنترل‌های دسترسی استفاده نمی‌کند. ساختار HTML سایت‌ها متفاوت است؛ ممکن است صفحات JS-rendered یا محافظت‌شده داده کامل ارائه نکنند. robots.txt، شرایط استفاده، محدودیت درخواست و حقوق محتوا را رعایت کنید.


## لایسنس و توسعه‌دهنده
- Developer: **Hadi Rasouli (هادی رسولی)**
- License: **MIT** (متن اصلی فایل LICENSE حفظ شده و نام توسعه‌دهنده به آن افزوده شده). عبارت GBL به‌عنوان مجوز استاندارد نرم‌افزار شناخته نشد؛ اگر منظورت GPL بوده، قبل از انتشار عمومی تأیید کن تا مجوز را به GPL تغییر دهم.


## ساختار

```text
.github/workflows/    GitHub Actions
src/perfume_scraper/ Scraper + Dashboard local server + web UI
src/perfume_scraper/web/ UI assets (HTML/CSS/JS)
tests/                Offline test suite
data/                 Source Excel workbooks
```

## Smart edition improvements
- Adaptive retries and extended request timeouts for transient network/server errors. HTTP 429/503 are handled with backoff; access controls and CAPTCHA are not bypassed.
- Animated dashboard analytics (pages/products and source health) with responsive canvas charts.
- Optional Persian translation fields (`description_fa`, `short_description_fa`, `long_description_fa`) while preserving originals. Translation requires a LibreTranslate-compatible endpoint.

### Optional translation setup
Set environment variables before launching the dashboard:
- `LIBRETRANSLATE_URL` — base URL for a LibreTranslate-compatible server (for example, your own instance URL).
- `LIBRETRANSLATE_API_KEY` — optional key if your translation server requires one.

Translation is opt-in in the dashboard. If no endpoint is configured, source text is preserved and translation fields remain empty. No external translation service is contacted by default.


### Windows quick setup for translation
In a Command Prompt window, set the endpoint for the LibreTranslate server you use:
```bat
set LIBRETRANSLATE_URL=https://your-libretranslate-server.example
set LIBRETRANSLATE_API_KEY=your-key-if-required
start-dashboard.bat
```
Replace the example URL and key with your translation provider's actual settings. The dashboard will keep original English text and add Persian fields when translation is enabled.
