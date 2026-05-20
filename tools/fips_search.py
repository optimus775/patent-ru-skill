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
from dataclasses import asdict, dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import parse_qs, urljoin, urlparse


FIPS_SEARCH_URL = "https://www1.fips.ru/iiss/search.xhtml"
FIPS_DB_URL = "https://www1.fips.ru/iiss/db.xhtml"
SOURCE_ADAPTER = "fips"
DEFAULT_DATABASE = "Патентные документы РФ (рус.)"
DEFAULT_DATABASE_LABELS = (
    "Рефераты российских изобретений",
    "Заявки на российские изобретения",
)
OUTPUT_PREFIX = "FIPS_HITS_JSON:"
TITLE_FIELD_LABEL = "(54) Название"
PUBLICATION_DATE_FIELD_LABEL = "(45) Опубликовано"
IPC_FIELD_LABEL = "(51) МПК"
ABSTRACT_FIELD_LABEL = "Реферат"
FORMULA_FIELD_LABEL = "Формула"


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


@dataclass(frozen=True)
class FipsRefineQuery:
    label: str
    main_query: str | None = None
    fields: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def display(self) -> str:
        parts: list[str] = []
        if self.main_query:
            parts.append(f"main={self.main_query}")
        parts.extend(f"{label}={value}" for label, value in self.fields)
        return f"{self.label}: {'; '.join(parts)}"


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


def _clean_terms(values: Sequence[str | None]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _has_boolean_syntax(value: str) -> bool:
    return bool(re.search(r'\b(?:AND|OR|NOT|WITHIN|ADJ)\b|["()[\]]', value, re.I))


def _quote_phrase(value: str) -> str:
    text = _clean_text(value) or ""
    if not text or _has_boolean_syntax(text) or " " not in text:
        return text
    return f'"{text}"'


def _append_exclusions(query: str, excludes: Sequence[str]) -> str:
    text = _clean_text(query) or ""
    for term in _clean_terms(excludes):
        text = f"{text} NOT {_quote_phrase(term)}" if text else f"NOT {_quote_phrase(term)}"
    return text


def _join_query_terms(*terms: str | None) -> str:
    return " ".join(_clean_terms(terms))


def _join_or_terms(terms: Sequence[str]) -> str:
    cleaned = _clean_terms(terms)
    if not cleaned:
        return ""
    return " OR ".join(cleaned)


def _short_search_terms(terms: Sequence[str], max_words: int = 5) -> list[str]:
    out: list[str] = []
    for term in _clean_terms(terms):
        if len(re.findall(r"\w+", term, flags=re.U)) <= max_words:
            out.append(term)
    return out


def build_refine_queries(
    query: str,
    features: Sequence[str] = (),
    effects: Sequence[str] = (),
    domain: str | None = None,
    ipc: Sequence[str] = (),
    excludes: Sequence[str] = (),
) -> list[FipsRefineQuery]:
    base_query = _clean_text(query) or ""
    feature_terms = _clean_terms(features)
    effect_terms = _clean_terms(effects)
    domain_text = _clean_text(domain)
    ipc_terms = _clean_terms(ipc)
    exclude_terms = _clean_terms(excludes)
    queries: list[FipsRefineQuery] = []

    def add(item: FipsRefineQuery) -> None:
        if not item.main_query and not item.fields:
            return
        key = (
            item.main_query or "",
            tuple((label, value) for label, value in item.fields if value),
        )
        if any(
            (existing.main_query or "", tuple(existing.fields)) == key
            for existing in queries
        ):
            return
        queries.append(item)

    add(FipsRefineQuery("main:broad", _append_exclusions(base_query, exclude_terms)))
    phrase_query = _append_exclusions(_quote_phrase(base_query), exclude_terms)
    add(FipsRefineQuery("main:phrase", phrase_query))

    if domain_text:
        add(
            FipsRefineQuery(
                "main:domain",
                _append_exclusions(_join_query_terms(base_query, domain_text), exclude_terms),
            )
        )

    for term in _short_search_terms([base_query, *feature_terms]):
        add(
            FipsRefineQuery(
                f"title:{term}",
                fields=((TITLE_FIELD_LABEL, _append_exclusions(_quote_phrase(term), exclude_terms)),),
            )
        )

    for term in [*feature_terms, *effect_terms]:
        field_query = _append_exclusions(term, exclude_terms)
        add(FipsRefineQuery(f"abstract:{term}", fields=((ABSTRACT_FIELD_LABEL, field_query),)))
        add(FipsRefineQuery(f"formula:{term}", fields=((FORMULA_FIELD_LABEL, field_query),)))

    if ipc_terms:
        ipc_query = _join_or_terms(ipc_terms)
        add(
            FipsRefineQuery(
                "ipc:main",
                _append_exclusions(base_query, exclude_terms),
                ((IPC_FIELD_LABEL, ipc_query),),
            )
        )
        for term in feature_terms[:3]:
            add(
                FipsRefineQuery(
                    f"ipc:feature:{term}",
                    _append_exclusions(term, exclude_terms),
                    ((IPC_FIELD_LABEL, ipc_query),),
                )
            )

    return queries


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
        self._cells: list[str] = []
        self._cell_depth = 0
        self._cell_buffer: list[str] = []
        self._link: str | None = None

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: v or "" for k, v in attrs_list}
        css_class = attrs.get("class", "").lower()
        css_tokens = set(css_class.split())
        href = attrs.get("href", "")
        starts_item = tag == "tr" or any(
            marker in css_class
            for marker in ("result-row", "search-result", "doc-item", "document-item")
        ) or (
            tag == "a"
            and "tr" in css_tokens
            and "document.xhtml" in href
        )
        if starts_item and self._current is None:
            self._current = {}
            self._item_depth = 0
            self._row_text = []
            self._cells = []
            self._cell_depth = 0
            self._cell_buffer = []
            self._link = None
        self._stack.append(tag)

        if self._current is None:
            return
        self._item_depth += 1
        if tag == "a" and href and not self._link:
            self._link = urljoin(self.base_url, href)

        if tag in {"td", "div"} and (
            tag == "td" or "td" in css_tokens or "cell" in css_tokens
        ):
            self._cell_depth = 1
            self._cell_buffer = []
        elif self._cell_depth > 0:
            self._cell_depth += 1

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
        if self._cell_depth > 0:
            self._cell_buffer.append(text)
        if self._field:
            self._buffer.append(text)

    def handle_endtag(self, tag: str) -> None:
        if self._current is not None and self._field and tag in {"td", "div", "span", "a"}:
            value = _clean_text(" ".join(self._buffer))
            if value and self._field not in self._current:
                self._current[self._field] = value
            self._field = None
            self._buffer = []

        if self._current is not None and self._cell_depth > 0:
            self._cell_depth -= 1
            if self._cell_depth == 0:
                self._cells.append(_clean_text(" ".join(self._cell_buffer)) or "")
                self._cell_buffer = []

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
            self._cells = []
            self._cell_depth = 0
            self._cell_buffer = []
            self._link = None

        if self._stack:
            self._stack.pop()

    def _finalize_current(self) -> dict[str, object] | None:
        assert self._current is not None
        text = _clean_text(" ".join(self._row_text)) or ""
        item = dict(self._current)
        cells = [_clean_text(cell) or "" for cell in self._cells]
        if len(cells) >= 5:
            item.setdefault("publication_number", cells[1])
            item.setdefault("publication_date", cells[2].strip("()"))
            item.setdefault("title", cells[4])
            if len(cells) >= 6:
                item.setdefault("database", cells[5])

        pub_no = normalize_publication_number(str(self._current.get("publication_number") or ""))
        if not pub_no:
            pub_no = normalize_publication_number(str(item.get("publication_number") or ""))
        if not pub_no:
            pub_no = normalize_publication_number(text)
        if not pub_no and not self._link:
            return None

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


def _hit_identity_from_dict(item: dict[str, object]) -> str | None:
    for field_name in ("publication_number", "application_number", "source_url"):
        value = _clean_text(str(item.get(field_name) or ""))
        if value:
            return value.casefold()
    title = _clean_text(str(item.get("title") or ""))
    return title.casefold()[:160] if title else None


def _hit_identity(hit: FipsHit) -> str | None:
    return _hit_identity_from_dict(asdict(hit))


def _normalize_match_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold().replace("ё", "е")).strip()


def _match_terms(value: str) -> list[str]:
    text = _normalize_match_text(value)
    return [part for part in re.split(r"[^\w]+", text, flags=re.U) if len(part) > 2]


def _contains_term(haystack: str, term: str) -> bool:
    text = _normalize_match_text(term).strip('"')
    return bool(text and text in haystack)


def _term_overlap_score(haystack: str, term: str) -> int:
    tokens = _match_terms(term)
    if not tokens:
        return 0
    matched = sum(1 for token in tokens if token in haystack)
    if matched == len(tokens):
        return 2
    return 1 if matched else 0


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _merge_refined_entries(
    query_hits: Iterable[tuple[FipsHit, FipsRefineQuery]],
) -> list[dict[str, object]]:
    items: dict[str, dict[str, object]] = {}
    for hit, refine_query in query_hits:
        hit_dict = asdict(hit)
        key = _hit_identity(hit)
        if not key:
            continue
        item = items.setdefault(
            key,
            {
                **hit_dict,
                "matched_queries": [],
                "_matched_query_labels": [],
                "_detail_text": "",
                "_ipc": "",
            },
        )
        for field_name, value in hit_dict.items():
            if value and not item.get(field_name):
                item[field_name] = value
        matched_queries = item.setdefault("matched_queries", [])
        labels = item.setdefault("_matched_query_labels", [])
        display = refine_query.display()
        if isinstance(matched_queries, list) and display not in matched_queries:
            matched_queries.append(display)
        if isinstance(labels, list) and refine_query.label not in labels:
            labels.append(refine_query.label)
    return list(items.values())


def _score_refined_item(
    item: dict[str, object],
    query: str,
    features: Sequence[str],
    effects: Sequence[str],
    domain: str | None,
    ipc: Sequence[str],
    excludes: Sequence[str],
) -> tuple[int, list[str]]:
    title = _normalize_match_text(item.get("title"))
    abstract = _normalize_match_text(item.get("abstract"))
    detail_text = _normalize_match_text(item.get("_detail_text"))
    ipc_text = _normalize_match_text(item.get("_ipc"))
    blob = " ".join(part for part in (title, abstract, detail_text, ipc_text) if part)
    reasons: list[str] = []
    score = 0

    matched_queries = item.get("matched_queries")
    if isinstance(matched_queries, list) and matched_queries:
        bonus = min(len(matched_queries), 5)
        score += bonus
        _add_reason(reasons, f"найдено уточняющими запросами: {len(matched_queries)}")

    base = _clean_text(query) or ""
    if _contains_term(title, base):
        score += 8
        _add_reason(reasons, "базовый запрос найден в названии")
    elif _contains_term(blob, base):
        score += 3
        _add_reason(reasons, "базовый запрос найден в тексте документа")
    else:
        overlap = _term_overlap_score(blob, base)
        if overlap:
            score += overlap
            _add_reason(reasons, "частичное совпадение с базовым запросом")

    for term in _clean_terms(features):
        if _contains_term(title, term):
            score += 10
            _add_reason(reasons, f"признак в названии: {term}")
        elif _contains_term(abstract, term) or _contains_term(detail_text, term):
            score += 6
            _add_reason(reasons, f"признак в реферате/тексте: {term}")
        else:
            overlap = _term_overlap_score(blob, term)
            if overlap:
                score += overlap
                _add_reason(reasons, f"частичное совпадение признака: {term}")

    for term in _clean_terms(effects):
        if _contains_term(title, term):
            score += 8
            _add_reason(reasons, f"технический результат в названии: {term}")
        elif _contains_term(abstract, term) or _contains_term(detail_text, term):
            score += 5
            _add_reason(reasons, f"технический результат в реферате/тексте: {term}")
        else:
            overlap = _term_overlap_score(blob, term)
            if overlap:
                score += overlap
                _add_reason(reasons, f"частичное совпадение результата: {term}")

    if domain:
        domain_text = _clean_text(domain) or ""
        if _contains_term(title, domain_text):
            score += 5
            _add_reason(reasons, f"область применения в названии: {domain_text}")
        elif _contains_term(blob, domain_text):
            score += 3
            _add_reason(reasons, f"область применения в тексте: {domain_text}")

    for ipc_value in _clean_terms(ipc):
        if _normalize_match_text(ipc_value) in ipc_text or _normalize_match_text(ipc_value) in blob:
            score += 7
            _add_reason(reasons, f"совпадение МПК: {ipc_value}")

    for term in _clean_terms(excludes):
        if _contains_term(title, term) or _contains_term(abstract, term) or _contains_term(detail_text, term):
            score -= 10
            _add_reason(reasons, f"штраф за исключение: {term}")

    return max(score, 0), reasons


def _publication_date_sort_key(item: dict[str, object]) -> tuple[int, int, int]:
    value = _clean_text(str(item.get("publication_date") or ""))
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", value or "")
    if not match:
        return (0, 0, 0)
    day, month, year = (int(part) for part in match.groups())
    return (year, month, day)


def _rank_refined_items(
    items: list[dict[str, object]],
    query: str,
    features: Sequence[str],
    effects: Sequence[str],
    domain: str | None,
    ipc: Sequence[str],
    excludes: Sequence[str],
) -> list[dict[str, object]]:
    for item in items:
        score, reasons = _score_refined_item(item, query, features, effects, domain, ipc, excludes)
        item["score"] = score
        item["score_reasons"] = reasons
    items.sort(
        key=lambda item: (
            -int(item.get("score") or 0),
            -len(item.get("matched_queries") or []),
            tuple(-part for part in _publication_date_sort_key(item)),
        )
    )
    for index, item in enumerate(items, start=1):
        item["rank"] = index
    return items


def _strip_refined_item(item: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in item.items()
        if not key.startswith("_")
    }


def build_refined_results(
    query_hits: Iterable[tuple[FipsHit, FipsRefineQuery]],
    query: str,
    features: Sequence[str] = (),
    effects: Sequence[str] = (),
    domain: str | None = None,
    ipc: Sequence[str] = (),
    excludes: Sequence[str] = (),
    top_k: int = 20,
) -> list[dict[str, object]]:
    items = _merge_refined_entries(query_hits)
    _rank_refined_items(items, query, features, effects, domain, ipc, excludes)
    return [_strip_refined_item(item) for item in items[:top_k]]


def _extract_rows_expression() -> str:
    return r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const rows = [];
  const resultLinks = Array.from(document.querySelectorAll(
    'a.tr[href*="document.xhtml"], a.tr[data-index]'
  ));
  for (const el of resultLinks) {
    const cells = Array.from(el.querySelectorAll('.td, td')).map((cell) => clean(cell.textContent));
    if (cells.length < 5) continue;
    rows.push({
      publication_number: cells[1],
      publication_date: clean(cells[2]).replace(/[()]/g, ''),
      title: cells[4],
      source_url: el.href || location.href,
      database: cells[5] || 'Патентные документы РФ (рус.)',
      row_text: clean(el.textContent),
    });
  }
  if (rows.length) return rows;

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

    title = page.locator("#db-selection-form .title").filter(
        has_text=re.compile(r"Патентные\s+документы\s+РФ\s+\(рус\.\)", re.I)
    ).first
    title.wait_for(state="visible", timeout=timeout_ms)
    if "closed" in (title.get_attribute("class") or ""):
        title.click(timeout=timeout_ms)
        page.wait_for_timeout(500)

    grid = page.locator("#db-selection-form\\:dbsGrid1")
    grid.wait_for(state="visible", timeout=timeout_ms)

    for label in DEFAULT_DATABASE_LABELS:
        row = grid.locator(".oneline").filter(has_text=label).first
        row.wait_for(state="visible", timeout=timeout_ms)
        checkbox = row.locator('input[type="checkbox"]').first
        if not checkbox.is_checked():
            checkbox.check(timeout=timeout_ms)
            page.wait_for_timeout(700)

    proceed = page.locator('input[type="submit"][value="перейти к поиску"]').first
    proceed.wait_for(state="visible", timeout=timeout_ms)
    proceed.click(timeout=timeout_ms)
    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)
    _raise_if_fips_unavailable(page)


def _open_search_form(page: object, timeout_ms: int) -> None:
    sidebar_link = page.locator("#sidebarForm\\:searchLink")
    if sidebar_link.count():
        sidebar_link.first.click(timeout=timeout_ms)
    else:
        page.goto(FIPS_SEARCH_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)
    _raise_if_fips_unavailable(page)


def _clear_search_form(page: object) -> None:
    page.evaluate(
        """
(() => {
  const form = document.querySelector('#searchForm');
  if (!form) return false;
  for (const control of form.querySelectorAll('input[type="text"], textarea')) {
    control.value = '';
    control.dispatchEvent(new Event('input', { bubbles: true }));
    control.dispatchEvent(new Event('change', { bubbles: true }));
  }
  return true;
})()
"""
    )


def _fill_search_field_by_label(page: object, label: str, value: str) -> bool:
    return bool(
        page.evaluate(
            """
({ label, value }) => {
  const form = document.querySelector('#searchForm');
  if (!form) return false;
  const clean = (text) => (text || '').replace(/\\s+/g, ' ').trim().toLocaleLowerCase('ru-RU');
  const wanted = clean(label);
  const blocks = Array.from(form.querySelectorAll('.oneblock'));
  for (const block of blocks) {
    const labelNode = block.querySelector('.name') || block;
    if (!clean(labelNode.innerText).includes(wanted)) continue;
    const control = block.querySelector('input[type="text"], textarea');
    if (!control) continue;
    control.value = value;
    control.dispatchEvent(new Event('input', { bubbles: true }));
    control.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }
  return false;
}
""",
            {"label": label, "value": value},
        )
    )


def _fill_search_form(page: object, query: str, timeout_ms: int) -> None:
    if not page.locator("textarea:visible").count():
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


def _execute_refine_query(page: object, refine_query: FipsRefineQuery, timeout_ms: int) -> list[FipsHit]:
    if not page.locator("#searchForm textarea:visible").count():
        _open_search_form(page, timeout_ms)
    _clear_search_form(page)

    main_query = page.locator("#searchForm textarea:visible").first
    if refine_query.main_query:
        main_query.fill(refine_query.main_query, timeout=timeout_ms)
    else:
        main_query.fill("", timeout=timeout_ms)

    for label, value in refine_query.fields:
        if not _fill_search_field_by_label(page, label, value):
            raise RuntimeError(f"FIPS search field was not found: {label}")

    search_button = page.locator('#searchForm input[type="submit"][value="Поиск"]').first
    if not search_button.count():
        raise RuntimeError("FIPS search submit control was not found")
    search_button.click(timeout=timeout_ms)
    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)
    _raise_if_fips_unavailable(page)

    raw_rows = page.evaluate(_extract_rows_expression())
    hits = dedupe_hits(_hit_from_raw(row) for row in raw_rows)
    if not hits:
        hits = parse_fips_html(page.content(), page.url)
    return hits


def _section_after_label(text: str, label_pattern: str, stop_pattern: str = r"\n\s*\(\d{2}\)|\n\s*‹‹") -> str | None:
    match = re.search(label_pattern, text, flags=re.I | re.S)
    if not match:
        return None
    start = match.end()
    stop = re.search(stop_pattern, text[start:], flags=re.I | re.S)
    end = start + stop.start() if stop else min(len(text), start + 2000)
    return _clean_text(text[start:end])


def _parse_document_detail_text(text: str) -> dict[str, object]:
    details: dict[str, object] = {"_detail_text": text}
    doc_number = re.search(r"\(11\)\s*([\d\s]+(?:[A-ZА-Я]\d?)?)", text)
    if doc_number:
        details["_detail_publication_number"] = normalize_publication_number(doc_number.group(1))

    application = re.search(r"\(21\)\(22\)\s*Заявка:\s*([^,\n]+)(?:,\s*([0-9.]+))?", text)
    if application:
        details["application_number"] = _clean_text(application.group(1))
        if application.group(2):
            details["filing_date"] = _clean_text(application.group(2))

    published = re.search(r"\(45\)\s*Опубликовано:\s*([0-9.]+)", text)
    if published:
        details["publication_date"] = published.group(1)

    title = _section_after_label(text, r"\(54\)\s*", r"\n\s*\(57\)|\n\s*\(\d{2}\)|\n\s*‹‹")
    if title:
        details["title"] = title

    abstract = _section_after_label(text, r"\(57\)\s*Реферат:\s*", r"\n\s*‹‹|\n\s*ИНФОРМАЦИОННО-ПОИСКОВАЯ")
    if abstract:
        details["abstract"] = abstract

    inventor = _section_after_label(text, r"\(72\)\s*Автор\(ы\):\s*")
    if inventor:
        details["inventor"] = inventor

    applicant = _section_after_label(text, r"\(71\)\s*Заявитель\(и\):\s*")
    if not applicant:
        applicant = _section_after_label(text, r"\(73\)\s*Патентообладатель\(и\):\s*")
    if applicant:
        details["applicant"] = applicant

    ipc = _section_after_label(text, r"\(51\)\s*МПК\s*", r"\n\s*\(12\)|\n\s*Статус:|\n\s*\(\d{2}\)")
    if ipc:
        details["_ipc"] = ipc

    return details


def _details_match_hit(details: dict[str, object], hit: FipsHit) -> bool:
    hit_numbers = {
        normalize_publication_number(hit.publication_number),
        normalize_publication_number(hit.application_number),
    }
    detail_numbers = {
        normalize_publication_number(str(details.get("_detail_publication_number") or "")),
        normalize_publication_number(str(details.get("application_number") or "")),
    }
    hit_numbers.discard(None)
    detail_numbers.discard(None)
    return bool(hit_numbers and detail_numbers and hit_numbers.intersection(detail_numbers))


def _apply_details_to_hit(hit: FipsHit, details: dict[str, object]) -> None:
    for field_name in (
        "application_number",
        "title",
        "abstract",
        "applicant",
        "inventor",
        "publication_date",
        "filing_date",
    ):
        value = _clean_text(str(details.get(field_name) or ""))
        if value and not getattr(hit, field_name):
            setattr(hit, field_name, value)


def _open_result_document(page: object, source_url: str, timeout_ms: int) -> bool:
    parsed = urlparse(source_url)
    doc_id = parse_qs(parsed.query).get("id", [""])[0]
    if doc_id:
        link = page.locator(f'a.tr[href*="{doc_id}"]').first
        if link.count():
            link.click(timeout=timeout_ms)
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            return True

    page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)
    return True


def _return_to_results(page: object, timeout_ms: int) -> None:
    try:
        page.go_back(wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


def _enrich_hits_with_details(page: object, hits: Sequence[FipsHit], limit: int, timeout_ms: int) -> int:
    if limit <= 0:
        return 0
    opened = 0
    for hit in hits:
        if opened >= limit:
            break
        source_url = _clean_text(hit.source_url)
        if not source_url:
            continue
        try:
            _open_result_document(page, source_url, timeout_ms)
            _raise_if_fips_unavailable(page)
            detail_text = page.evaluate("document.body ? document.body.innerText : ''")
            details = _parse_document_detail_text(detail_text)
            opened += 1
            if not _details_match_hit(details, hit):
                continue
            _apply_details_to_hit(hit, details)
        except Exception:
            continue
        finally:
            _return_to_results(page, timeout_ms)
    return opened


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


def run_browser_refined_search(
    query: str,
    features: Sequence[str],
    effects: Sequence[str],
    domain: str | None,
    ipc: Sequence[str],
    excludes: Sequence[str],
    top_k: int,
    details_limit: int,
    timeout_ms: int,
) -> list[dict[str, object]]:
    endpoint = load_browserless_endpoint()
    if not endpoint:
        raise RuntimeError("BROWSERLESS_WS_ENDPOINT is not configured")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install FIPS dependencies: pip install -r tools/requirements-fips.txt") from exc

    refine_queries = build_refine_queries(query, features, effects, domain, ipc, excludes)
    query_hits: list[tuple[FipsHit, FipsRefineQuery]] = []
    query_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint, timeout=timeout_ms)
        context = browser.new_context(locale="ru-RU")
        page = context.new_page()
        try:
            _select_fips_databases(page, timeout_ms)
            details_remaining = details_limit
            for refine_query in refine_queries:
                try:
                    hits = _execute_refine_query(page, refine_query, timeout_ms)
                    if details_remaining > 0:
                        details_remaining -= _enrich_hits_with_details(
                            page,
                            hits,
                            details_remaining,
                            timeout_ms,
                        )
                except Exception as exc:
                    query_errors.append(f"{refine_query.display()}: {sanitize_error_message(str(exc))}")
                    continue
                query_hits.extend((hit, refine_query) for hit in hits)

            items = _merge_refined_entries(query_hits)
            _rank_refined_items(items, query, features, effects, domain, ipc, excludes)

            if not items and query_errors:
                return [
                    error_result(
                        "FIPS_REFINE_QUERY_ERROR",
                        "; ".join(query_errors[:5]),
                        retryable=True,
                    )
                ]

            return [_strip_refined_item(item) for item in items[:top_k]]
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
        "--refine",
        action="store_true",
        help="Run several narrower FIPS queries and return a ranked shortlist.",
    )
    parser.add_argument(
        "--feature",
        action="append",
        default=[],
        help="Essential technical feature for refined search; can be repeated.",
    )
    parser.add_argument(
        "--effect",
        action="append",
        default=[],
        help="Technical result/effect for refined search; can be repeated.",
    )
    parser.add_argument("--domain", help="Application domain for refined search.")
    parser.add_argument(
        "--ipc",
        action="append",
        default=[],
        help="IPC class for refined search; can be repeated.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Term to exclude with NOT in refined search; can be repeated.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="Ranked shortlist size for --refine, 1-100.",
    )
    parser.add_argument(
        "--details-limit",
        type=int,
        default=30,
        help="How many top refined results to open for detail enrichment, 0-100.",
    )
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
    top_k = max(1, min(100, int(args.top_k)))
    details_limit = max(0, min(100, int(args.details_limit)))
    timeout_ms = max(5_000, int(args.timeout_ms))

    if not query:
        print(format_hits_line([error_result("FIPS_EMPTY_QUERY", "Search query is empty.")]))
        return 2

    try:
        if args.refine:
            items = run_browser_refined_search(
                query=query,
                features=args.feature,
                effects=args.effect,
                domain=args.domain,
                ipc=args.ipc,
                excludes=args.exclude,
                top_k=top_k,
                details_limit=details_limit,
                timeout_ms=timeout_ms,
            )
        else:
            hits = run_browser_search(query, limit, timeout_ms)
            items = hits_to_jsonable(hits)
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        print(format_hits_line([error_result("FIPS_SEARCH_ERROR", message, retryable=True)]))
        return 1

    print(format_hits_line(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
