#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Browserless-driven FIPS patent search.

Stdout contract:
  FIPS_HITS_JSON: [...]

The Browserless endpoint is read from BROWSERLESS_WS_ENDPOINT in the process
environment or from the repository-root .env file. The endpoint is never
printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urljoin, urlparse


FIPS_SEARCH_URL = "https://www1.fips.ru/iiss/search.xhtml"
FIPS_DB_URL = "https://www1.fips.ru/iiss/db.xhtml"
SOURCE_ADAPTER = "fips"
DEFAULT_DATABASE = "Патентные документы РФ (рус.)"
OUTPUT_PREFIX = "FIPS_HITS_JSON:"


@dataclass
class FipsHit:
    publication_number: str | None = None
    application_number: str | None = None
    title: str | None = None
    abstract: str | None = None
    applicant: str | None = None
    inventor: str | None = None
    publication_date: str | None = None
    filing_date: str | None = None
    source_url: str | None = None
    database: str | None = DEFAULT_DATABASE
    source_adapter: str = SOURCE_ADAPTER


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, TypeError, ValueError):
            pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_dotenv_value(env_file: Path, key: str) -> str | None:
    if not env_file.exists():
        return None
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        value = value.strip().strip('"').strip("'")
        return value or None
    return None


def load_browserless_endpoint(env_file: Path | None = None) -> str | None:
    endpoint = os.environ.get("BROWSERLESS_WS_ENDPOINT", "").strip()
    if endpoint:
        return endpoint

    env_file = env_file or (_repo_root() / ".env")
    try:
        from dotenv import dotenv_values  # type: ignore
    except ImportError:
        return _read_dotenv_value(env_file, "BROWSERLESS_WS_ENDPOINT")

    values = dotenv_values(env_file)
    value = values.get("BROWSERLESS_WS_ENDPOINT")
    if value:
        return str(value).strip() or None
    return None


def error_result(error_code: str, message: str, retryable: bool = False) -> dict[str, object]:
    return {
        "error_code": error_code,
        "message": sanitize_error_message(message),
        "retryable": retryable,
        "source_adapter": SOURCE_ADAPTER,
    }


def sanitize_error_message(message: str) -> str:
    endpoint = load_browserless_endpoint()
    sanitized = message
    if endpoint:
        sanitized = sanitized.replace(endpoint, "[BROWSERLESS_WS_ENDPOINT]")
        parsed = urlparse(endpoint)
        if parsed.netloc:
            sanitized = sanitized.replace(parsed.netloc, "[BROWSERLESS_HOST]")
        if parsed.hostname:
            sanitized = sanitized.replace(parsed.hostname, "[BROWSERLESS_HOST]")
    sanitized = re.sub(
        r"(?i)(wss?://[^\s\"']*?[?&]token=)[^&\s\"']+",
        r"\1[REDACTED]",
        sanitized,
    )
    sanitized = re.sub(r"(?i)(token=)[^&\s\"']+", r"\1[REDACTED]", sanitized)
    sanitized = re.sub(r"(?i)wss?://[^\s\"']+", "[BROWSERLESS_WS_ENDPOINT]", sanitized)
    return sanitized


def format_hits_line(items: Sequence[object]) -> str:
    return f"{OUTPUT_PREFIX} {json.dumps(list(items), ensure_ascii=False, sort_keys=True)}"


def normalize_publication_number(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"\s+", "", value.upper())
    match = re.search(r"(?:RU)?(\d{4,})([A-ZА-Я]{0,2}\d?)?", text)
    if not match:
        return None
    kind = match.group(2) or ""
    return f"RU{match.group(1)}{kind}"


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", unescape(value)).strip(" \t\r\n;:-")
    return text or None


def _field_from_attrs(attrs: dict[str, str]) -> str | None:
    raw = " ".join(
        filter(
            None,
            [
                attrs.get("class", ""),
                attrs.get("data-field", ""),
                attrs.get("headers", ""),
                attrs.get("aria-label", ""),
            ],
        )
    ).lower()
    mapping = {
        "publication_number": (
            "doc-number",
            "docnumber",
            "pub-number",
            "publication_number",
            "td.number",
            " number",
        ),
        "application_number": ("app-number", "application"),
        "title": ("doc-title", "title", "name"),
        "abstract": ("abstract", "реферат"),
        "applicant": ("applicant", "patentee", "заявитель", "правообладатель"),
        "inventor": ("inventor", "author", "автор"),
        "publication_date": ("pubdate", "publication-date", "datepub", "публикац"),
        "filing_date": ("filing", "application-date", "подач"),
        "database": ("database", "db-name"),
    }
    for field, needles in mapping.items():
        if any(needle in raw for needle in needles):
            return field
    return None


class FipsResultParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.items: list[dict[str, object]] = []
        self._stack: list[str] = []
        self._current: dict[str, object] | None = None
        self._item_depth = 0
        self._field: str | None = None
        self._buffer: list[str] = []
        self._row_text: list[str] = []
        self._link: str | None = None

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: v or "" for k, v in attrs_list}
        css_class = attrs.get("class", "").lower()
        starts_item = tag == "tr" or any(
            marker in css_class
            for marker in ("result-row", "search-result", "doc-item", "document-item")
        )
        if starts_item and self._current is None:
            self._current = {}
            self._item_depth = 0
            self._row_text = []
            self._link = None
        self._stack.append(tag)

        if self._current is None:
            return
        self._item_depth += 1
        if tag == "a" and attrs.get("href") and not self._link:
            self._link = urljoin(self.base_url, attrs["href"])

        field = _field_from_attrs(attrs)
        if field:
            self._field = field
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        text = _clean_text(data)
        if not text:
            return
        self._row_text.append(text)
        if self._field:
            self._buffer.append(text)

    def handle_endtag(self, tag: str) -> None:
        if self._current is not None and self._field and tag in {"td", "div", "span", "a"}:
            value = _clean_text(" ".join(self._buffer))
            if value and self._field not in self._current:
                self._current[self._field] = value
            self._field = None
            self._buffer = []

        if self._current is not None:
            self._item_depth -= 1

        if self._current is not None and self._item_depth <= 0:
            item = self._finalize_current()
            if item:
                self.items.append(item)
            self._current = None
            self._item_depth = 0
            self._field = None
            self._buffer = []
            self._row_text = []
            self._link = None

        if self._stack:
            self._stack.pop()

    def _finalize_current(self) -> dict[str, object] | None:
        assert self._current is not None
        text = _clean_text(" ".join(self._row_text)) or ""
        pub_no = normalize_publication_number(str(self._current.get("publication_number") or ""))
        if not pub_no:
            pub_no = normalize_publication_number(text)
        if not pub_no and not self._link:
            return None

        item = dict(self._current)
        item["publication_number"] = pub_no
        if self._link:
            item["source_url"] = self._link
        if not item.get("title"):
            item["title"] = _title_from_row_text(text, pub_no)
        return item


def _title_from_row_text(text: str, pub_no: str | None) -> str | None:
    if not text:
        return None
    if pub_no:
        text = text.replace(pub_no, " ")
        text = text.replace(pub_no.removeprefix("RU"), " ")
    text = re.sub(r"\b\d{2}\.\d{2}\.\d{4}\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -;:")
    return text[:300] or None


def parse_fips_html(html: str, base_url: str = "https://www.fips.ru/") -> list[FipsHit]:
    parser = FipsResultParser(base_url)
    parser.feed(html)
    raw_items = parser.items
    return dedupe_hits(_hit_from_raw(item) for item in raw_items)


def _hit_from_raw(raw: dict[str, object]) -> FipsHit:
    def get(name: str) -> str | None:
        value = raw.get(name)
        return _clean_text(str(value)) if value is not None else None

    return FipsHit(
        publication_number=normalize_publication_number(get("publication_number")),
        application_number=get("application_number"),
        title=get("title"),
        abstract=get("abstract"),
        applicant=get("applicant"),
        inventor=get("inventor"),
        publication_date=get("publication_date"),
        filing_date=get("filing_date"),
        source_url=get("source_url"),
        database=get("database") or DEFAULT_DATABASE,
    )


def dedupe_hits(hits: Iterable[FipsHit]) -> list[FipsHit]:
    seen: set[str] = set()
    out: list[FipsHit] = []
    for hit in hits:
        key_parts = [
            hit.publication_number,
            hit.application_number,
            hit.source_url,
            (hit.title or "").casefold()[:160] if hit.title else None,
        ]
        key = next((part for part in key_parts if part), None)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


def hits_to_jsonable(hits: Sequence[FipsHit]) -> list[dict[str, object]]:
    return [asdict(hit) for hit in hits]


def _extract_rows_expression() -> str:
    return r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const pick = (root, selectors) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const text = node ? clean(node.textContent) : '';
      if (text) return text;
    }
    return '';
  };
  const nodes = Array.from(document.querySelectorAll(
    'table tr, .result-row, .search-results .item, .doc-item, .document-item'
  ));
  const rows = [];
  for (const el of nodes) {
    const rowText = clean(el.textContent);
    if (!rowText || !/(RU\s*)?\d{4,}/i.test(rowText)) continue;
    const link = el.querySelector('a[href]');
    rows.push({
      publication_number: pick(el, [
        '.doc-number', '.pub-number', '[data-field="docNumber"]',
        '[data-field="publication_number"]', 'td.number'
      ]),
      application_number: pick(el, ['.app-number', '[data-field="appNumber"]']),
      title: pick(el, ['.doc-title', '[data-field="title"]', 'td.title', 'a[href]']),
      abstract: pick(el, ['.abstract', '[data-field="abstract"]']),
      applicant: pick(el, ['.applicant', '[data-field="applicant"]']),
      inventor: pick(el, ['.inventor', '[data-field="inventor"]']),
      publication_date: pick(el, [
        '.publication-date', '.pub-date', '[data-field="pubDate"]', 'td.pubDate'
      ]),
      filing_date: pick(el, ['.filing-date', '[data-field="filingDate"]']),
      source_url: link ? link.href : location.href,
      database: 'Патентные документы РФ (рус.)',
      row_text: rowText,
    });
  }
  return rows;
})()
"""


def detect_fips_gateway_error(title: str, body_text: str) -> str | None:
    text = f"{title}\n{body_text}".casefold()
    if "502 bad gateway" in text:
        return "FIPS returned 502 Bad Gateway."
    if "bad gateway" in text and "nginx" in text:
        return "FIPS gateway is unavailable."
    return None


def _raise_if_fips_unavailable(page: object) -> None:
    title = page.title()
    body_text = page.evaluate("document.body ? document.body.innerText.slice(0, 2000) : ''")
    message = detect_fips_gateway_error(title, body_text)
    if message:
        raise RuntimeError(message)


def _select_fips_databases(page: object, timeout_ms: int) -> None:
    page.goto(FIPS_DB_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)
    _raise_if_fips_unavailable(page)

    title = page.get_by_text("Патентные документы РФ (рус.)", exact=True)
    if title.count():
        title.first.click(timeout=timeout_ms)
        page.wait_for_timeout(500)

    labels = [
        "Рефераты российских изобретений",
        "Заявки на российские изобретения",
        "Полные тексты российских изобретений из трех последних бюллетеней",
        "Формулы российских полезных моделей",
        "Формулы российских полезных моделей из трех последних бюллетеней",
    ]
    for label in labels:
        locator = page.get_by_text(label, exact=True)
        if not locator.count():
            continue
        try:
            locator.first.click(timeout=timeout_ms)
            page.wait_for_timeout(300)
        except Exception:
            continue


def _open_search_form(page: object, timeout_ms: int) -> None:
    sidebar_link = page.locator("#sidebarForm\\:searchLink")
    if sidebar_link.count():
        sidebar_link.first.click(timeout=timeout_ms)
    else:
        page.goto(FIPS_SEARCH_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)
    _raise_if_fips_unavailable(page)


def _fill_search_form(page: object, query: str, timeout_ms: int) -> None:
    _open_search_form(page, timeout_ms)

    main_query = page.locator("textarea:visible").first
    if not main_query.count():
        raise RuntimeError("FIPS search form input was not found")
    main_query.fill(query, timeout=timeout_ms)

    search_button = page.locator('input[type="submit"][value="Поиск"]').first
    if not search_button.count():
        raise RuntimeError("FIPS search submit control was not found")
    search_button.click(timeout=timeout_ms)

    page.wait_for_load_state("networkidle", timeout=timeout_ms)


def run_browser_search(query: str, limit: int, timeout_ms: int) -> list[FipsHit]:
    endpoint = load_browserless_endpoint()
    if not endpoint:
        raise RuntimeError("BROWSERLESS_WS_ENDPOINT is not configured")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install FIPS dependencies: pip install -r tools/requirements-fips.txt") from exc

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint, timeout=timeout_ms)
        context = browser.new_context(locale="ru-RU")
        page = context.new_page()
        try:
            _select_fips_databases(page, timeout_ms)
            _fill_search_form(page, query, timeout_ms)
            raw_rows = page.evaluate(_extract_rows_expression())
            hits = dedupe_hits(_hit_from_raw(row) for row in raw_rows)
            if not hits:
                hits = parse_fips_html(page.content(), page.url)
            return hits[:limit]
        finally:
            context.close()
            browser.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search Russian patent documents in FIPS through Browserless.",
    )
    parser.add_argument("query", nargs="+", help="Search unit or phrase.")
    parser.add_argument("--limit", type=int, default=20, help="Max results, 1-100.")
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=90_000,
        help="Browser operation timeout in milliseconds.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    query = " ".join(args.query).strip()
    limit = max(1, min(100, int(args.limit)))
    timeout_ms = max(5_000, int(args.timeout_ms))

    if not query:
        print(format_hits_line([error_result("FIPS_EMPTY_QUERY", "Search query is empty.")]))
        return 2

    try:
        hits = run_browser_search(query, limit, timeout_ms)
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        print(format_hits_line([error_result("FIPS_SEARCH_ERROR", message, retryable=True)]))
        return 1

    print(format_hits_line(hits_to_jsonable(hits)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
