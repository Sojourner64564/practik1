#!/usr/bin/env python3
"""Утилита для выборки и просмотра страниц из архива Common Crawl."""

from __future__ import annotations

import argparse
import io
import json
import socket
import sys
from collections import Counter

import requests
from bs4 import BeautifulSoup
from tabulate import tabulate
from warcio.archiveiterator import ArchiveIterator

# --- Принудительное использование IPv4 -----------------------------------
_getaddrinfo_original = socket.getaddrinfo


def _force_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _getaddrinfo_original(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _force_ipv4
# -------------------------------------------------------------------------

CDX_ENDPOINT = "https://index.commoncrawl.org/CC-MAIN-2024-30-index"
WARC_TEMPLATE = "https://data.commoncrawl.org/{filename}"

EXCLUDED_MARKERS = (
    "robots.txt",
    "sitemap",
    "/wiki/",
    "?C=",
    "&O=",
    ".pdf",
    ".xml",
    "?id=",
)

TEXT_PREVIEW_LEN = 600
FULL_TEXT_LIMIT = 30_000
MAX_CDX_RETRIES = 3
CDX_TIMEOUT = 30
WARC_TIMEOUT = 60


# --------------------------------------------------------------------------
# Работа с CDX-индексом
# --------------------------------------------------------------------------
def fetch_cdx_records(domain: str, cap: int) -> list[dict]:
    """Запрашивает у CDX-сервера список записей для указанного домена."""
    query = {
        "url": f"*.{domain}/*",
        "output": "json",
        "filter": ["status:200", "mime:text/html"],
        "limit": str(cap),
    }

    payload = None
    for attempt in range(MAX_CDX_RETRIES):
        try:
            resp = requests.get(CDX_ENDPOINT, params=query, timeout=CDX_TIMEOUT)
        except requests.RequestException as err:
            print(f"[CDX] сеть недоступна: {err}", file=sys.stderr)
            continue

        if resp.status_code in (502, 504):
            print(f"[CDX] шлюз вернул {resp.status_code}, пробуем снова…")
            continue

        try:
            resp.raise_for_status()
        except requests.HTTPError as err:
            print(f"[CDX] HTTP-ошибка: {err}", file=sys.stderr)
            return []

        payload = resp.text
        break

    if payload is None:
        return []

    collected: list[dict] = []
    for raw_line in payload.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        try:
            item = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        target = item.get("url", "")
        if any(marker in target for marker in EXCLUDED_MARKERS):
            continue

        collected.append(item)
        if len(collected) >= cap:
            break

    return collected


# --------------------------------------------------------------------------
# Извлечение содержимого из WARC
# --------------------------------------------------------------------------
def extract_page(record: dict) -> tuple[str, str]:
    """Возвращает (title, text) для одной записи WARC."""
    offset = int(record["offset"])
    length = int(record["length"])
    byte_range = f"bytes={offset}-{offset + length - 1}"

    warc_url = WARC_TEMPLATE.format(filename=record["filename"])
    resp = requests.get(warc_url, headers={"Range": byte_range}, timeout=WARC_TIMEOUT)
    resp.raise_for_status()

    buffer = io.BytesIO(resp.content)
    for entry in ArchiveIterator(buffer):
        if entry.rec_type != "response":
            continue

        soup = BeautifulSoup(entry.content_stream().read(), "html.parser")
        heading = soup.title.get_text(strip=True) if soup.title else ""
        body = soup.get_text(" ", strip=True)
        return heading, body[:FULL_TEXT_LIMIT]

    return "", ""


# --------------------------------------------------------------------------
# Формирование таблицы
# --------------------------------------------------------------------------
def render_table(records, needles, with_text):
    survivors = []

    for idx, rec in enumerate(records, 1):
        heading, body = "", ""
        if with_text:
            try:
                heading, body = extract_page(rec)
            except Exception as err:
                print(f"[WARC] пропуск {rec.get('url', '?')}: {err}", file=sys.stderr)
                continue

            if needles:
                haystack = f"{heading} {body}".lower()
                if not all(n.lower() in haystack for n in needles):
                    continue

        survivors.append(rec)

        print(f"\n[{idx}] {rec.get('url', '')}")
        print(f"    Дата:       {rec.get('timestamp', '')}")
        if with_text:
            print(f"    Заголовок:  {heading}")
            print(f"    Текст:      {body[:TEXT_PREVIEW_LEN]}")

    print(f"\nВсего строк: {len(survivors)}")
    return survivors


# --------------------------------------------------------------------------
# Статистика
# --------------------------------------------------------------------------
def print_stats(records: list[dict]) -> None:
    if not records:
        return

    domain_counter: Counter[str] = Counter()
    year_counter: Counter[str] = Counter()

    for rec in records:
        url = rec.get("url", "")
        if "://" in url:
            domain_counter[url.split("/")[2]] += 1

        ts = rec.get("timestamp", "")
        if len(ts) >= 4:
            year_counter[ts[:4]] += 1

    print("\nРаспределение по доменам:")
    for dom, n in domain_counter.most_common():
        print(f"  {dom}: {n}")

    print("\nРаспределение по годам:")
    for yr in sorted(year_counter):
        print(f"  {yr}: {year_counter[yr]}")


# --------------------------------------------------------------------------
# Точка входа
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Поиск по архиву Common Crawl",
    )
    p.add_argument("keywords", nargs="*", default=[],
                   help="Ключевые слова для поиска")
    p.add_argument("--domain", nargs="+", required=True,
                   help="Домен (например, pstu.ru)")
    p.add_argument("--limit", type=int, default=10,
                   help="Ограничение числа результатов")
    p.add_argument("--show-text", action="store_true",
                   help="Показать фрагмент текста страницы")
    return p


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.limit < 1:
        print("--limit должен быть больше нуля", file=sys.stderr)
        return 2

    per_domain = args.limit * 2 if args.show_text else args.limit

    all_records: list[dict] = []
    for dom in args.domain:
        print(f"Поиск по домену: {dom}")
        batch = fetch_cdx_records(dom, per_domain)
        print(f"  найдено: {len(batch)}")
        all_records.extend(batch)

    final = render_table(all_records, args.keywords, args.show_text)
    print_stats(final)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())