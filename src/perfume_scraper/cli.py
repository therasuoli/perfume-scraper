from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from .core import (
    create_session,
    enrich_brand,
    load_brands,
    load_sources,
    load_store_sources,
    scrape_url,
    write_output,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="استخراج خودکار محصولات عطر از وب‌سایت‌ها")
    parser.add_argument("--brands", default="data/perfume-brands-by-country.xlsx")
    parser.add_argument(
        "--source-list",
        choices=["iranian", "brands", "all", "custom", "all_stores", "selected_stores", "manual_urls"],
        default="iranian",
    )
    parser.add_argument("--stores-xlsx", default="data/perfume-online-stores.xlsx")
    parser.add_argument("--store-region", default="all")
    parser.add_argument("--store-selection", default="", help="نام فروشگاه، URL یا دامنه؛ جداکننده کاما یا خط جدید")
    parser.add_argument("--urls", default="", help="آدرس‌ها با جداکننده خط یا کاما؛ برای حالت custom/manual_urls")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--format", choices=["csv", "json", "xlsx"], default="xlsx")
    parser.add_argument("-o", "--output", default="run-output")
    parser.add_argument("--download-images", action="store_true")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _manual_sources(raw_urls: str) -> list[dict]:
    urls = [part.strip() for part in re.split(r"[\n,;]+", raw_urls or "") if part.strip()]
    sources = []
    for raw in urls:
        url = raw if raw.startswith(("http://", "https://")) else f"https://{raw.lstrip('/')}"
        host = urlparse(url).netloc
        if host:
            sources.append({"name": host, "url": url, "source_type": "custom"})
    return list({source["url"].lower().rstrip("/"): source for source in sources}.values())


def _resolve_sources(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[dict]:
    if args.source_list in ("custom", "manual_urls"):
        sources = _manual_sources(args.urls)
        if not sources:
            parser.error("در حالت لینک دستی باید حداقل یک URL وارد شود.")
        return sources
    if args.source_list in ("all_stores", "selected_stores"):
        selection = args.store_selection if args.source_list == "selected_stores" else ""
        sources = load_store_sources(args.stores_xlsx, args.store_region, selection)
        if args.source_list == "selected_stores" and not sources:
            parser.error("هیچ فروشگاهی مطابق انتخاب پیدا نشد؛ نام یا دامنه را بررسی کنید.")
        return sources
    return load_sources(args.brands, args.source_list)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit باید صفر یا بزرگ‌تر باشد")
    if args.max_pages < 1:
        parser.error("--max-pages باید حداقل ۱ باشد")
    if args.delay < 0:
        parser.error("--delay باید صفر یا بزرگ‌تر باشد")

    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    sources = _resolve_sources(args, parser)
    if not sources:
        logging.error("منبع معتبری پیدا نشد؛ گزارش اجرا ایجاد می‌شود.")

    all_items: list[dict] = []
    report: list[dict] = []
    session = create_session()
    try:
        for source in sources:
            row = {
                "name": source["name"],
                "url": source["url"],
                "source_type": source.get("source_type", "custom"),
                "pages_checked": 0,
                "products_found": 0,
                "errors": 0,
                "status": "started",
            }
            logging.info("شروع: %s (%s)", source["name"], source["url"])
            try:
                got, stats = scrape_url(
                    source["url"], source["name"], args.limit, args.download_images,
                    outdir / "images", args.delay, args.max_pages, session=session,
                )
                for item in got:
                    item["source_type"] = source.get("source_type", "custom")
                row.update(stats)
                errors = stats.get("errors", 0)
                row["status"] = "partial" if got and errors else ("ok" if got else ("error" if errors else "no_products"))
                all_items.extend(got)
                logging.info("%s: %d محصول | %d صفحه", source["name"], len(got), stats.get("pages_checked", 0))
            except Exception as exc:
                row["status"] = "error"
                row["error"] = str(exc)
                row["errors"] = row.get("errors", 0) + 1
                logging.exception("خطا در منبع %s", source.get("url"))
            report.append(row)
    finally:
        session.close()

    unique = {}
    for item in all_items:
        product_url = item.get("product_url")
        if product_url:
            existing = unique.get(product_url)
            if not existing or (not existing.get("image_url") and item.get("image_url")):
                unique[product_url] = item
    all_items = list(unique.values())
    try:
        enrich_brand(all_items, load_brands(args.brands))
    except Exception as exc:
        logging.warning("تطبیق برندها انجام نشد: %s", exc)

    product_path = write_output(all_items, args.format, outdir)
    run_report = {
        "source_list": args.source_list,
        "sources_total": len(sources),
        "total_products": len(all_items),
        "source_results": report,
    }
    (outdir / "run-report.json").write_text(
        json.dumps(run_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (outdir / "source-summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["name", "url", "source_type", "status", "pages_checked", "products_found", "errors", "error"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report)

    print(f"{len(all_items)} محصول استخراج شد از {len(sources)} منبع. خروجی: {product_path}")
    print(f"گزارش اجرا: {outdir / 'run-report.json'}")
    if report and all(source.get("status") == "error" for source in report):
        raise SystemExit("تمام منابع با خطای شبکه/دسترسی مواجه شدند؛ گزارش‌ها ذخیره شده‌اند.")


if __name__ == "__main__":
    main()
