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
    dedupe_hits,
    format_hits_line,
    hits_to_jsonable,
    load_browserless_endpoint,
    normalize_publication_number,
    parse_fips_html,
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


if __name__ == "__main__":
    unittest.main()
