#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from fips_search import (  # noqa: E402
    FipsHit,
    FipsRefineQuery,
    build_refine_queries,
    build_refined_results,
    dedupe_hits,
    format_hits_line,
    hits_to_jsonable,
    load_browserless_endpoint,
    normalize_publication_number,
    parse_fips_html,
    sanitize_error_message,
)


class FipsSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_endpoint = os.environ.pop("BROWSERLESS_WS_ENDPOINT", None)

    def tearDown(self) -> None:
        os.environ.pop("BROWSERLESS_WS_ENDPOINT", None)
        if self._old_endpoint is not None:
            os.environ["BROWSERLESS_WS_ENDPOINT"] = self._old_endpoint

    def test_load_browserless_endpoint_from_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text(
                "BROWSERLESS_WS_ENDPOINT=wss://browserless.example?token=secret\n",
                encoding="utf-8",
            )

            self.assertEqual(
                load_browserless_endpoint(env_file),
                "wss://browserless.example?token=secret",
            )

    def test_environment_variable_overrides_env_file(self) -> None:
        os.environ["BROWSERLESS_WS_ENDPOINT"] = "wss://from-env.example?token=secret"
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text(
                "BROWSERLESS_WS_ENDPOINT=wss://from-file.example?token=secret\n",
                encoding="utf-8",
            )

            self.assertEqual(
                load_browserless_endpoint(env_file),
                "wss://from-env.example?token=secret",
            )

    def test_publication_number_normalization(self) -> None:
        self.assertEqual(normalize_publication_number("2 765 432 C1"), "RU2765432C1")
        self.assertEqual(normalize_publication_number("RU 123456 U1"), "RU123456U1")

    def test_format_hits_line_contract(self) -> None:
        hit = FipsHit(publication_number="RU2765432C1", title="Тестовый патент")
        line = format_hits_line(hits_to_jsonable([hit]))

        self.assertTrue(line.startswith("FIPS_HITS_JSON: "))
        payload = json.loads(line.split(": ", 1)[1])
        self.assertEqual(payload[0]["publication_number"], "RU2765432C1")
        self.assertEqual(payload[0]["source_adapter"], "fips")

    def test_sanitize_error_message_redacts_browserless_token(self) -> None:
        os.environ["BROWSERLESS_WS_ENDPOINT"] = "wss://10.0.0.1:3000?token=secret"

        message = sanitize_error_message(
            "Cannot connect to wss://10.0.0.1:3000?token=secret; retry ws://10.0.0.1:3000/; ECONNREFUSED 10.0.0.1:3000"
        )

        self.assertNotIn("secret", message)
        self.assertNotIn("10.0.0.1", message)
        self.assertNotIn("3000", message)
        self.assertIn("[BROWSERLESS_WS_ENDPOINT]", message)

    def test_dedupe_hits_prefers_first_match(self) -> None:
        hits = dedupe_hits(
            [
                FipsHit(publication_number="RU2765432C1", title="Первый"),
                FipsHit(publication_number="RU2765432C1", title="Дубликат"),
                FipsHit(application_number="2023123456", title="Заявка"),
            ]
        )

        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].title, "Первый")

    def test_parse_fips_html_fixture(self) -> None:
        html = """
        <table class="results">
          <tr class="result-row">
            <td class="doc-number">2765432 C1</td>
            <td class="doc-title"><a href="/registers-doc-view/fips_servlet?DB=RUPAT&DocNumber=2765432">Способ управления очередью</a></td>
            <td class="applicant">ООО "Тест"</td>
            <td class="publication-date">15.03.2024</td>
          </tr>
          <tr class="result-row">
            <td data-field="docNumber">RU2765432C1</td>
            <td data-field="title">Способ управления очередью</td>
          </tr>
        </table>
        """

        hits = parse_fips_html(html, "https://www.fips.ru/iiss/search.xhtml")

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].publication_number, "RU2765432C1")
        self.assertEqual(hits[0].title, "Способ управления очередью")
        self.assertEqual(hits[0].applicant, 'ООО "Тест"')
        self.assertEqual(hits[0].publication_date, "15.03.2024")
        self.assertIn("registers-doc-view", hits[0].source_url or "")

    def test_parse_fips_modern_result_rows(self) -> None:
        html = """
        <form id="j_idt98">
          <div class="table">
            <div class="tr tit">
              <div class="th"><b>№</b></div>
              <div class="th"><b>Номер документа</b></div>
              <div class="th"><b>Дата публикации</b></div>
              <div class="th"><b>Изображение</b></div>
              <div class="th"><b>Название</b></div>
              <div class="th"><b>Библ-ка</b></div>
            </div>
            <a class="tr" data-index="3" href="document.xhtml?faces-redirect=true&amp;id=abc">
              <div class="td">3.</div>
              <div class="td" style="font-weight: bold;">2515997</div>
              <div class="td" style="font-weight: bold;">(20.05.2014)</div>
              <div class="td"></div>
              <div class="td">АКТИВНОЕ УПРАВЛЕНИЕ ОЧЕРЕДЬЮ</div>
              <div class="td" style="font-weight: bold;">РИ</div>
            </a>
          </div>
        </form>
        """

        hits = parse_fips_html(html, "https://www1.fips.ru/iiss/search_res.xhtml")

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].publication_number, "RU2515997")
        self.assertEqual(hits[0].publication_date, "20.05.2014")
        self.assertEqual(hits[0].title, "АКТИВНОЕ УПРАВЛЕНИЕ ОЧЕРЕДЬЮ")
        self.assertEqual(hits[0].database, "РИ")
        self.assertIn("document.xhtml", hits[0].source_url or "")

    def test_build_refine_queries_uses_fields_and_exclusions(self) -> None:
        queries = build_refine_queries(
            "управление очередью",
            features=["диспетчеризация очередей", "приоритет обработки"],
            effects=["снижение задержки"],
            domain="сеть связи",
            ipc=["H04W 28/10"],
            excludes=["газоперекачивающ"],
        )

        displays = [query.display() for query in queries]
        self.assertTrue(any("main:broad" in item for item in displays))
        self.assertTrue(any('(54) Название="управление очередью" NOT газоперекачивающ' in item for item in displays))
        self.assertTrue(any("Реферат=диспетчеризация очередей NOT газоперекачивающ" in item for item in displays))
        self.assertTrue(any("Формула=снижение задержки NOT газоперекачивающ" in item for item in displays))
        self.assertTrue(any("(51) МПК=H04W 28/10" in item for item in displays))

    def test_build_refined_results_dedupes_and_scores(self) -> None:
        broad = FipsRefineQuery("main:broad", "управление очередью")
        title = FipsRefineQuery(
            "title:управление очередью",
            fields=(("(54) Название", '"управление очередью"'),),
        )
        weak = FipsRefineQuery("main:broad", "управление очередью")
        hit = FipsHit(
            publication_number="RU2515997",
            title="АКТИВНОЕ УПРАВЛЕНИЕ ОЧЕРЕДЬЮ ДЛЯ ВОСХОДЯЩЕЙ ЛИНИИ СВЯЗИ",
            abstract="Технический результат заключается в уменьшении задержки передачи сигналов.",
            publication_date="20.05.2014",
        )
        duplicate = FipsHit(
            publication_number="RU2515997",
            title="Дубликат",
            publication_date="20.05.2014",
        )
        excluded = FipsHit(
            publication_number="RU2821718",
            title="Способ снижения потребления топливного газа газоперекачивающими агрегатами",
            publication_date="26.06.2024",
        )

        results = build_refined_results(
            [(hit, broad), (duplicate, title), (excluded, weak)],
            query="управление очередью",
            features=["управление очередью"],
            effects=["уменьшении задержки"],
            excludes=["газоперекачивающ"],
            top_k=10,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["publication_number"], "RU2515997")
        self.assertEqual(results[0]["rank"], 1)
        self.assertGreater(results[0]["score"], results[1]["score"])
        self.assertEqual(len(results[0]["matched_queries"]), 2)
        self.assertTrue(any("признак" in reason for reason in results[0]["score_reasons"]))
        self.assertTrue(any("штраф" in reason for reason in results[1]["score_reasons"]))


if __name__ == "__main__":
    unittest.main()
