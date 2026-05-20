#!/usr/bin/env python3
"""End-to-end smoke harness for the civil RU2844157C1 AI training fixture.

The harness intentionally writes generated artifacts only under outputs/.
It does not print Browserless endpoints or .env values.
"""
from __future__ import annotations

import argparse
import binascii
import json
import os
import re
import struct
import subprocess
import sys
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_DIR = ROOT / "outputs" / "e2e_ru2844157_ai_training"
DEFAULT_TOOL_SMOKE_DIR = ROOT / "outputs" / "tool_smoke"
OUTPUT_PREFIX = "FIPS_HITS_JSON:"

CASE_SLUG = "e2e_ru2844157_ai_training"
DOC_STEM = "Способ_и_система_для_обучения_глубокой_нейронной_сети"
PATENT_URL = "https://patents.google.com/patent/RU2844157C1/ru"

BANNED_RE = re.compile(
    r"беспилот|бпла|военн|оруж|боеприпас|радиолокац|drone|uav|military",
    re.IGNORECASE,
)
CLEAN_RE = re.compile(
    r"self-check|Browserless|BROWSERLESS|\.env|patent-ru-skill|учебн",
    re.IGNORECASE,
)

EXPECTED_PROMPTS = [
    "intake.md",
    "project_scan.md",
    "patent_points_analyzer.md",
    "prior_art_search.md",
    "disclosure_preview.md",
    "disclosure_builder.md",
    "template_reference.md",
    "disclosure_self_check.md",
    "iteration_context.md",
    "merger.md",
    "correction_handler.md",
]


@dataclass
class StepResult:
    name: str
    status: str
    details: str = ""
    artifacts: list[str] = field(default_factory=list)


class Harness:
    def __init__(
        self,
        *,
        case_dir: Path,
        tool_smoke_dir: Path,
        skip_fips: bool,
        skip_failure_mode: bool,
    ) -> None:
        self.case_dir = case_dir.resolve()
        self.tool_smoke_dir = tool_smoke_dir.resolve()
        self.skip_fips = skip_fips
        self.skip_failure_mode = skip_failure_mode
        self.results: list[StepResult] = []
        self.fips_broad: list[dict[str, Any]] = []
        self.fips_refined: list[dict[str, Any]] = []
        self.version_outputs: list[tuple[str, Path, Path]] = []
        self.puppeteer_config = self.case_dir / "puppeteer_no_sandbox.json"

    def record(
        self,
        name: str,
        ok: bool,
        details: str = "",
        artifacts: list[Path] | None = None,
        *,
        skipped: bool = False,
    ) -> None:
        status = "SKIP" if skipped else ("PASS" if ok else "FAIL")
        rel_artifacts = []
        for item in artifacts or []:
            try:
                rel_artifacts.append(str(item.resolve().relative_to(ROOT)))
            except ValueError:
                rel_artifacts.append(str(item))
        self.results.append(
            StepResult(
                name=name,
                status=status,
                details=sanitize(details),
                artifacts=rel_artifacts,
            )
        )

    def run(
        self,
        label: str,
        args: list[str],
        *,
        cwd: Path = ROOT,
        env: dict[str, str] | None = None,
        timeout: int = 120,
        expect_code: int | None = 0,
    ) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if expect_code is not None and proc.returncode != expect_code:
            msg = (
                f"{label}: exit {proc.returncode}, expected {expect_code}\n"
                f"stdout:\n{sanitize(proc.stdout[-3000:])}\n"
                f"stderr:\n{sanitize(proc.stderr[-3000:])}"
            )
            raise AssertionError(msg)
        return proc

    def prepare_dirs(self) -> None:
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self.tool_smoke_dir.mkdir(parents=True, exist_ok=True)
        self.puppeteer_config.write_text(
            json.dumps(
                {
                    "args": [
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                    ]
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.record(
            "Создание output-каталогов",
            self.case_dir.is_dir() and self.tool_smoke_dir.is_dir(),
            "Каталоги готовы; Puppeteer config для sandbox-limited окружений записан.",
            [self.case_dir, self.tool_smoke_dir, self.puppeteer_config],
        )

    def preflight(self) -> None:
        missing_prompts = [
            name for name in EXPECTED_PROMPTS if not (ROOT / "prompts" / name).is_file()
        ]
        self.record(
            "Проверка prompt-файлов workflow",
            not missing_prompts,
            "Все ожидаемые prompt-файлы найдены."
            if not missing_prompts
            else "Не найдены: " + ", ".join(missing_prompts),
        )

        endpoint_configured = bool(os.environ.get("BROWSERLESS_WS_ENDPOINT", "").strip())
        env_file = ROOT / ".env"
        env_file_has_key = False
        if env_file.is_file():
            env_file_has_key = any(
                line.strip().startswith("BROWSERLESS_WS_ENDPOINT=")
                for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines()
            )
        self.record(
            "Проверка Browserless-конфигурации без раскрытия секрета",
            endpoint_configured or env_file_has_key or self.skip_fips,
            "BROWSERLESS_WS_ENDPOINT найден в окружении или .env."
            if endpoint_configured or env_file_has_key
            else "BROWSERLESS_WS_ENDPOINT не найден; ФИПС-проверки пропущены или упадут.",
        )

        proc = self.run(
            "unit tests",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            timeout=120,
        )
        self.record("Unit-тесты", "OK" in proc.stderr or "OK" in proc.stdout, "unittest discover завершился успешно.")

        tools = [
            "fips_search.py",
            "docx_to_md.py",
            "pptx_to_md.py",
            "md_to_docx.py",
            "mermaid_render.py",
            "iteration_dialog_log.py",
        ]
        failed = []
        for tool in tools:
            try:
                self.run(
                    f"{tool} --help",
                    [sys.executable, str(ROOT / "tools" / tool), "--help"],
                    timeout=60,
                )
            except Exception as exc:  # noqa: BLE001 - collected into report
                failed.append(f"{tool}: {exc}")
        self.record(
            "CLI --help для всех tools",
            not failed,
            "Все tools показали help." if not failed else "\n".join(failed),
        )

    def tool_smoke(self) -> None:
        docx_out = self.tool_smoke_dir / "sample_architecture_review.md"
        self.run(
            "docx_to_md smoke",
            [
                sys.executable,
                str(ROOT / "tools" / "docx_to_md.py"),
                "-i",
                str(ROOT / "examples/example_batch_job_scheduler/knowledge/docs/sample_architecture_review.docx"),
                "-o",
                str(docx_out),
            ],
            timeout=120,
        )
        self.record(
            "Smoke docx_to_md.py",
            docx_out.is_file() and docx_out.stat().st_size > 0,
            "DOCX пример конвертирован в Markdown.",
            [docx_out],
        )

        pptx_out = self.tool_smoke_dir / "sample_scheduler_deck.md"
        self.run(
            "pptx_to_md smoke",
            [
                sys.executable,
                str(ROOT / "tools" / "pptx_to_md.py"),
                "-i",
                str(ROOT / "examples/example_batch_job_scheduler/knowledge/docs/sample_scheduler_deck.pptx"),
                "-o",
                str(pptx_out),
            ],
            timeout=120,
        )
        self.record(
            "Smoke pptx_to_md.py",
            pptx_out.is_file() and pptx_out.stat().st_size > 0,
            "PPTX пример конвертирован в Markdown.",
            [pptx_out],
        )

        simple_media = self.tool_smoke_dir / "simple_media"
        simple_media.mkdir(parents=True, exist_ok=True)
        simple_png = simple_media / "red.png"
        write_png(simple_png, rgb=(220, 36, 48))
        simple_md = self.tool_smoke_dir / "simple_markdown.md"
        simple_md.write_text(
            "\n".join(
                [
                    "# Smoke Markdown",
                    "",
                    "Абзац с **жирным** текстом и `inline code`.",
                    "",
                    "| Поле | Значение |",
                    "|---|---|",
                    "| fixture | RU2844157C1 |",
                    "",
                    "- пункт списка",
                    "",
                    "![](simple_media/red.png)",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        simple_docx = self.tool_smoke_dir / "simple_markdown.docx"
        self.run(
            "md_to_docx smoke",
            [
                sys.executable,
                str(ROOT / "tools" / "md_to_docx.py"),
                "-i",
                str(simple_md),
                "-o",
                str(simple_docx),
                "--base-dir",
                str(self.tool_smoke_dir),
            ],
            timeout=120,
        )
        self.record(
            "Smoke md_to_docx.py",
            simple_docx.is_file() and simple_docx.stat().st_size > 0,
            "Markdown с таблицей, списком и PNG конвертирован в Word.",
            [simple_md, simple_png, simple_docx],
        )

        mermaid_in = self.tool_smoke_dir / "mermaid_smoke_input.md"
        mermaid_out = self.tool_smoke_dir / "mermaid_smoke_output.md"
        mermaid_in.write_text(
            """# Mermaid smoke

```mermaid
flowchart TD
    A[Данные] --> B[Оценка]
    B --> C[Отбор]
```

```mermaid
flowchart TD
    A --> 
```
""",
            encoding="utf-8",
        )
        self.run(
            "mermaid_render smoke",
            [
                sys.executable,
                str(ROOT / "tools" / "mermaid_render.py"),
                "-i",
                str(mermaid_in),
                "-o",
                str(mermaid_out),
                "--assets-dir",
                "mermaid_smoke_figures",
                "--no-docx",
            ],
            env={"MERMAID_PUPPETEER_CONFIG": str(self.puppeteer_config)},
            timeout=240,
        )
        pngs = list((self.tool_smoke_dir / "mermaid_smoke_figures").glob("*.png"))
        preserved_invalid = "```mermaid" in mermaid_out.read_text(encoding="utf-8", errors="replace")
        self.record(
            "Smoke mermaid_render.py",
            bool(pngs) and preserved_invalid,
            "Валидный Mermaid стал PNG, невалидный блок сохранен как fenced source.",
            [mermaid_out, *pngs],
        )

    def fips_checks(self) -> None:
        if self.skip_fips:
            self.record("ФИПС broad/refine", True, "Пропущено параметром --skip-fips.", skipped=True)
            return

        broad = self.run(
            "FIPS broad",
            [
                sys.executable,
                str(ROOT / "tools" / "fips_search.py"),
                "обучение глубокой нейронной сети",
                "--limit",
                "5",
                "--timeout-ms",
                "60000",
            ],
            timeout=180,
        )
        self.fips_broad = parse_fips_hits(broad.stdout)
        has_fixture = any(
            (item.get("publication_number") or "") in {"RU2844157", "RU2844157C1"}
            and item.get("publication_date") == "28.07.2025"
            for item in self.fips_broad
        )
        self.record(
            "ФИПС broad search",
            has_fixture,
            "Широкий поиск содержит RU2844157 с датой 28.07.2025.",
        )

        refined = self.run(
            "FIPS refine",
            [
                sys.executable,
                str(ROOT / "tools" / "fips_search.py"),
                "обучение глубокой нейронной сети",
                "--refine",
                "--feature",
                "трудные выборки",
                "--feature",
                "генеративная модель",
                "--effect",
                "стабильное качество прогнозирования",
                "--domain",
                "вычислительная техника",
                "--exclude",
                "беспилот",
                "--exclude",
                "БПЛА",
                "--exclude",
                "военн",
                "--exclude",
                "оруж",
                "--exclude",
                "боеприпас",
                "--exclude",
                "радиолокац",
                "--top-k",
                "5",
                "--details-limit",
                "2",
                "--timeout-ms",
                "60000",
            ],
            timeout=240,
        )
        self.fips_refined = parse_fips_hits(refined.stdout)
        rank_one = bool(self.fips_refined) and (
            self.fips_refined[0].get("publication_number") in {"RU2844157", "RU2844157C1"}
            and self.fips_refined[0].get("rank") == 1
        )
        no_banned = not BANNED_RE.search(json.dumps(public_hit_fields(self.fips_refined), ensure_ascii=False))
        self.record(
            "ФИПС refined search",
            rank_one and no_banned,
            "RU2844157 находится на rank 1; запрещенные темы не найдены в shortlist.",
        )

    def write_fixture_files(self) -> None:
        fixture = {
            "publication_number": "RU2844157C1",
            "application_number": "RU2024118858A",
            "title": "Способ и система для обучения глубокой нейронной сети с помощью дополнительных формируемых данных",
            "filing_date": "2024-07-05",
            "publication_date": "2025-07-28",
            "source_url": PATENT_URL,
            "domain": "гражданская вычислительная техника, обучение глубоких нейронных сетей",
            "object": "группа решений: способ и система",
            "technical_result": "более стабильное качество прогнозирования глубокой нейронной сети на данных с разным уровнем сложности",
            "excluded_topics": [
                "беспилотные системы",
                "военная тематика",
                "оружие",
                "боеприпасы",
                "радиолокационные сценарии",
                "double-use сценарии",
            ],
        }
        fixture_path = self.case_dir / "patent_fixture.json"
        fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        prompt_path = self.case_dir / "agent_start_prompt.txt"
        prompt_path.write_text(
            f"""Используй patent-ru-skill и подготовь полный комплект материалов российской заявки на изобретение.
Исходный публичный материал: RU2844157C1, "Способ и система для обучения глубокой нейронной сети с помощью дополнительных формируемых данных", {PATENT_URL}.
Работай как с гражданским IT/AI-решением. Исключи беспилотники, военную, оружейную, боеприпасную, радиолокационную и double-use тематику.
Тип: изобретение. Объект: группа решений способ + система; носитель добавлять только если он явно вытекает из раскрытия.
Заявитель, авторы и контактные поля: "подлежит уточнению".
Выход: полный Markdown + Word, фигуры, prior art notes, preview и финальная внутренняя проверка без включения служебных проверок в итоговый документ.
""",
            encoding="utf-8",
        )

        prior_art_path = self.case_dir / "prior_art_notes.md"
        prior_art_path.write_text(build_prior_art_notes(), encoding="utf-8")
        preview_path = self.case_dir / "preview.md"
        preview_path.write_text(build_preview(), encoding="utf-8")

        self.record(
            "Fixture, prompt, prior art notes и preview",
            all(path.is_file() for path in [fixture_path, prompt_path, prior_art_path, preview_path]),
            "Опорные материалы для E2E-сценария записаны.",
            [fixture_path, prompt_path, prior_art_path, preview_path],
        )

    def build_disclosure_versions(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        variants = [
            ("v1_base", False, True, "Базовая версия с исходной формулой."),
            ("v2_poisson", True, True, "Добавлен вариант выбора трудных выборок через распределение Пуассона."),
            ("v3_corrected", True, False, "Из формулы убраны конкретные названия генеративных моделей."),
        ]

        for label, include_poisson, brand_in_claims, _summary in variants:
            draft = self.case_dir / f"{DOC_STEM}_{label}_{timestamp}_draft.md"
            final_md = self.case_dir / f"{DOC_STEM}_{label}_{timestamp}.md"
            final_docx = final_md.with_suffix(".docx")
            draft.write_text(
                build_disclosure(
                    include_poisson=include_poisson,
                    brand_in_claims=brand_in_claims,
                ),
                encoding="utf-8",
            )
            self.run(
                f"render disclosure {label}",
                [
                    sys.executable,
                    str(ROOT / "tools" / "mermaid_render.py"),
                    "-i",
                    str(draft),
                    "-o",
                    str(final_md),
                    "--assets-dir",
                    f"figures_{label}",
                "--docx",
                    str(final_docx),
                ],
                env={"MERMAID_PUPPETEER_CONFIG": str(self.puppeteer_config)},
                timeout=300,
            )
            self.version_outputs.append((label, final_md, final_docx))

        self.run(
            "iteration log merge",
            [
                sys.executable,
                str(ROOT / "tools" / "iteration_dialog_log.py"),
                "--case-dir",
                str(self.case_dir),
                "--kind",
                "merge",
                "--user",
                "Добавить вариант выбора трудных выборок через распределение Пуассона.",
                "--summary",
                "В описание и зависимые пункты добавлен статистический вариант выбора трудных выборок.",
                "--artifacts",
                f"{self.version_outputs[1][1].name},{self.version_outputs[1][2].name}",
            ],
            timeout=60,
        )
        self.run(
            "iteration log correct",
            [
                sys.executable,
                str(ROOT / "tools" / "iteration_dialog_log.py"),
                "--case-dir",
                str(self.case_dir),
                "--kind",
                "correct",
                "--user",
                "Убрать конкретные названия ControlNet/UniControlNet из формулы.",
                "--summary",
                "Формула обобщена до вспомогательной модели условной генерации; примеры оставлены только в описании.",
                "--artifacts",
                f"{self.version_outputs[2][1].name},{self.version_outputs[2][2].name}",
            ],
            timeout=60,
        )

        artifacts = []
        for _, md, docx in self.version_outputs:
            artifacts.extend([md, docx])
        artifacts.append(self.case_dir / "revision_dialog_log.md")
        self.record(
            "Сборка E2E-комплекта и итераций",
            all(path.is_file() and path.stat().st_size > 0 for path in artifacts),
            "Созданы три версии Markdown/Word и журнал итераций.",
            artifacts,
        )

    def validate_artifacts(self) -> None:
        latest_md = self.version_outputs[-1][1]
        latest_text = latest_md.read_text(encoding="utf-8", errors="replace")
        required_sections = [
            "## Описание изобретения",
            "## Формула изобретения",
            "## Реферат",
            "## Фигуры",
        ]
        has_sections = all(section in latest_text for section in required_sections)

        all_md_texts = []
        for path in self.case_dir.glob("*.md"):
            all_md_texts.append((path, path.read_text(encoding="utf-8", errors="replace")))
        banned_hits = [
            f"{path.name}: {match.group(0)}"
            for path, text in all_md_texts
            for match in BANNED_RE.finditer(text)
        ]
        clean_hits = [
            f"{path.name}: {match.group(0)}"
            for path, text in all_md_texts
            for match in CLEAN_RE.finditer(text)
        ]

        formula_text = extract_between(latest_text, "## Формула изобретения", "## Реферат")
        formula_has_brand = re.search(r"ControlNet|UniControlNet", formula_text, re.IGNORECASE) is not None
        latest_docx = self.version_outputs[-1][2]
        pngs = list(self.case_dir.glob("figures_v3_corrected/*.png"))
        self_check_report = self.case_dir / "self_check_report.json"
        self_check_report.write_text(
            json.dumps(
                {
                    "latest_markdown": latest_md.name,
                    "sections_present": has_sections,
                    "banned_topic_hits": banned_hits,
                    "cleanliness_hits": clean_hits,
                    "formula_contains_brand_names": formula_has_brand,
                    "figures": [path.name for path in pngs],
                    "docx_exists": latest_docx.is_file(),
                    "revision_log_exists": (self.case_dir / "revision_dialog_log.md").is_file(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        ok = (
            has_sections
            and not banned_hits
            and not clean_hits
            and not formula_has_brand
            and latest_docx.is_file()
            and bool(pngs)
            and (self.case_dir / "revision_dialog_log.md").is_file()
        )
        details = "Итоговые Markdown/Word, фигуры, журнал и фильтры прошли проверку."
        if not ok:
            details = "\n".join(
                [
                    f"sections_present={has_sections}",
                    f"banned_hits={banned_hits}",
                    f"cleanliness_hits={clean_hits}",
                    f"formula_has_brand={formula_has_brand}",
                    f"docx_exists={latest_docx.is_file()}",
                    f"png_count={len(pngs)}",
                ]
            )
        self.record(
            "Валидация итоговых артефактов",
            ok,
            details,
            [latest_md, latest_docx, *pngs, self_check_report],
        )

    def failure_mode(self) -> None:
        if self.skip_failure_mode:
            self.record("Failure-mode Browserless", True, "Пропущено параметром --skip-failure-mode.", skipped=True)
            return
        proc = self.run(
            "FIPS invalid endpoint",
            [
                sys.executable,
                str(ROOT / "tools" / "fips_search.py"),
                "обучение глубокой нейронной сети",
                "--limit",
                "3",
                "--timeout-ms",
                "5000",
            ],
            env={"BROWSERLESS_WS_ENDPOINT": "ws://127.0.0.1:1?token=test-secret"},
            timeout=60,
            expect_code=None,
        )
        hits = parse_fips_hits(proc.stdout)
        raw = proc.stdout + proc.stderr
        no_secret = "test-secret" not in raw and "127.0.0.1" not in raw
        structured_error = bool(hits) and hits[0].get("error_code") == "FIPS_SEARCH_ERROR"
        self.record(
            "Failure-mode: неверный Browserless endpoint",
            structured_error and no_secret,
            "Получен структурированный FIPS_SEARCH_ERROR; fake token/host не раскрыты.",
        )

    def write_report(self) -> Path:
        report = {
            "case": CASE_SLUG,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "case_dir": str(self.case_dir.relative_to(ROOT)),
            "tool_smoke_dir": str(self.tool_smoke_dir.relative_to(ROOT)),
            "results": [asdict(result) for result in self.results],
            "fips_broad": self.fips_broad,
            "fips_refined": self.fips_refined,
            "version_outputs": [
                {
                    "label": label,
                    "markdown": str(md.relative_to(ROOT)),
                    "docx": str(docx.relative_to(ROOT)),
                }
                for label, md, docx in self.version_outputs
            ],
        }
        report_path = self.case_dir / "e2e_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report_path

    def failed(self) -> list[StepResult]:
        return [result for result in self.results if result.status == "FAIL"]


def sanitize(value: str) -> str:
    value = re.sub(r"wss?://[^\s\"'<>]+", "[BROWSERLESS_WS_ENDPOINT]", value)
    value = re.sub(r"token=[^&\s\"'<>]+", "token=[redacted]", value)
    value = value.replace("test-secret", "[redacted-test-token]")
    value = value.replace("127.0.0.1", "[redacted-host]")
    return value


def parse_fips_hits(stdout: str) -> list[dict[str, Any]]:
    for line in stdout.splitlines():
        if line.startswith(OUTPUT_PREFIX):
            payload = line.split(":", 1)[1].strip()
            return json.loads(payload)
    raise AssertionError("FIPS_HITS_JSON line was not found")


def public_hit_fields(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = {
        "publication_number",
        "application_number",
        "title",
        "abstract",
        "applicant",
        "inventor",
        "publication_date",
        "filing_date",
        "database",
    }
    return [{key: item.get(key) for key in keys if key in item} for item in items]


def write_png(path: Path, *, rgb: tuple[int, int, int]) -> None:
    width = height = 24
    row = bytes([0]) + bytes(rgb) * width
    raw = row * height

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def build_prior_art_notes() -> str:
    return f"""# Заметки по уровню техники

## Fixture

| Поле | Значение |
|---|---|
| Документ | RU2844157C1 |
| Название | Способ и система для обучения глубокой нейронной сети с помощью дополнительных формируемых данных |
| Заявка | RU2024118858A |
| Дата публикации | 28.07.2025 |
| Источник | {PATENT_URL} |

## Ближайшие источники

| Источник | Дата | Суть | Ограничение для текущего решения |
|---|---:|---|---|
| RU2641447C1 | 17.01.2018 | Обучение глубоких нейронных сетей на основе распределений попарных мер схожести. | Не раскрывает генерацию дополнительных входных изображений по эталонной метке для трудных выборок. |
| WO2020167490A1 | 20.08.2020 | Поэтапное обучение модели с выявлением сложных входных данных. | Требует дополнительных данных, собранных или размеченных отдельно; не формирует новые входные данные из эталонной метки внутри цикла обучения. |
| WO2021035193A1 | 25.02.2021 | Активное обучение с неразмеченными выборками и выбором данных для получения эталонных меток. | Зависит от пула неразмеченных данных и внешней разметки. |
| EP4254265A1 | 04.10.2023 | Регуляризация U-net с дополнительным декодером. | Привязано к конкретной архитектуре и не добавляет сформированные обучающие изображения в набор данных. |

## Отличительные признаки

- после эпохи обучения измеряют качество прогнозирования для каждой размеченной выборки;
- выбирают трудные выборки с наихудшим качеством или низкой вероятностью принадлежности распределению показателей;
- для трудной выборки формируют входные изображения по соответствующей эталонной метке;
- сформированные изображения добавляют к обучающим данным для следующей эпохи;
- цикл повторяют до выполнения критерия завершения.
"""


def build_preview() -> str:
    return """# Preview направления заявки

| Поле | Рабочее решение |
|---|---|
| Название | Способ и система для обучения глубокой нейронной сети с помощью дополнительных формируемых данных |
| Объект охраны | Группа решений: способ и система |
| Техническая проблема | Нестабильность качества прогнозирования на обучающих данных разной сложности |
| Технический результат | Более стабильное качество прогнозирования при меньшей потребности во внешних дополнительных данных |
| Ближайший уровень техники | WO2020167490A1 и RU2641447C1 |

Предполагаемый независимый пункт способа: выполняют эпоху обучения на размеченных выборках, измеряют качество прогнозирования для каждой выборки, выбирают трудные выборки, формируют дополнительные входные изображения по эталонным меткам трудных выборок, добавляют сформированные изображения к обучающим данным и повторяют цикл до выполнения критерия завершения.

Фигуры: блок-схема способа обучения; структурная схема системы; схема формирования дополнительных данных.
"""


def build_disclosure(*, include_poisson: bool, brand_in_claims: bool) -> str:
    poisson_description = (
        " В одном варианте показатели качества сопоставляют с распределением Пуассона, "
        "если анализируемый показатель имеет счетную природу или описывает число ошибок в выборке."
        if include_poisson
        else ""
    )
    poisson_claim = (
        "\n\n7. Способ по п. 4, в котором упомянутое распределение представляет собой распределение Пуассона."
        if include_poisson
        else ""
    )
    brand_claim = (
        "\n\n8. Способ по п. 1, в котором вспомогательная генеративная модель представляет собой модель ControlNet или UniControlNet."
        if brand_in_claims
        else "\n\n8. Способ по п. 1, в котором вспомогательная генеративная модель представляет собой модель условной генерации изображений, управляемую эталонной меткой и дополнительными обуславливающими данными."
    )
    system_offset = 9

    return f"""# Материалы заявки на изобретение

## Заявочные сведения

| Поле | Значение |
|---|---|
| Тип заявки | Изобретение |
| Рабочее название | Способ и система для обучения глубокой нейронной сети с помощью дополнительных формируемых данных |
| Объект | Группа решений: способ и система |
| Заявитель | подлежит уточнению |
| Авторы | подлежит уточнению |
| Технический контакт | подлежит уточнению |
| Исходный публичный материал | RU2844157C1, RU2024118858A, публикация 28.07.2025 |

## Описание изобретения

### Название изобретения

Способ и система для обучения глубокой нейронной сети с помощью дополнительных формируемых данных.

### Область техники, к которой относится изобретение

Изобретение относится к вычислительной технике, а именно к обучению глубоких нейронных сетей на размеченных данных. Решение может применяться для задач анализа изображений, сегментации, оценки глубины, классификации и иных задач, в которых качество прогнозирования зависит от сложности обучающих выборок.

### Уровень техники

Известны подходы, в которых качество модели улучшают за счет дополнительной разметки, регуляризации или повторного обучения на сложных примерах. В RU2641447C1 раскрыто обучение глубоких нейронных сетей с использованием распределений попарных мер схожести, однако такой подход не формирует дополнительные входные изображения по эталонным меткам трудных выборок.

В WO2020167490A1 раскрыто поэтапное обучение модели с выявлением сложных входных данных. Недостаток данного подхода состоит в необходимости привлечения дополнительных данных, собранных или размеченных отдельно. В WO2021035193A1 используется активное обучение с неразмеченными выборками, что также предполагает наличие внешнего пула данных и получение эталонных меток для выбранных выборок.

Ближайшие решения не устраняют полностью проблему нестабильного качества прогнозирования для выборок различной сложности без привлечения внешнего набора неразмеченных данных или отдельной ручной разметки.

### Раскрытие сущности изобретения

Техническая проблема состоит в нестабильности качества прогнозирования глубокой нейронной сети для обучающих выборок с разным уровнем сложности, особенно когда трудные примеры редки в исходном размеченном наборе.

Технический результат состоит в обеспечении более стабильного качества прогнозирования глубокой нейронной сети на данных с разным уровнем сложности, а также в снижении потребности во внешнем наборе дополнительных данных.

Для достижения результата выполняют по меньшей мере одну эпоху обучения глубокой нейронной сети на размеченных выборках, оценивают качество прогнозирования для каждой выборки, выбирают трудные выборки, для каждой выбранной выборки формируют дополнительные входные изображения на основе соответствующей эталонной метки и добавляют сформированные изображения к обучающим данным для следующей эпохи. Цикл повторяют до выполнения критерия завершения обучения.

Выбор трудных выборок может осуществляться по значениям функции потерь, метрике расхождения между прогнозируемой и эталонной разметкой, показателю качества прогнозируемой разметки или их комбинации. В одном варианте вычисленные показатели сопоставляют с одномерным или многомерным распределением, а трудными признают выборки с наименьшей вероятностью принадлежности указанному распределению.{poisson_description}

Вспомогательная генеративная модель может быть выполнена как модель условной генерации изображений, принимающая эталонную метку и дополнительные обуславливающие данные, например карту контуров или карту глубины. В качестве неограничивающих примеров такой модели могут использоваться ControlNet или UniControlNet; эти примеры не ограничивают объем реализации.

### Краткое описание чертежей

Фиг. 1 иллюстрирует последовательность операций способа обучения глубокой нейронной сети.

Фиг. 2 иллюстрирует систему для обучения глубокой нейронной сети.

Фиг. 3 иллюстрирует формирование дополнительного входного изображения на основе эталонной метки.

### Осуществление изобретения

Система содержит модуль обучения, модуль оценки качества, модуль выбора трудных обучающих примеров, вспомогательную генеративную модель и память обучающих данных. Модуль обучения выполняет эпоху обучения глубокой нейронной сети на множестве размеченных выборок. Каждая выборка содержит входное изображение и соответствующую эталонную метку.

После эпохи обучения модуль оценки качества применяет обучаемую сеть к обучающим выборкам и определяет показатель качества для каждой выборки. Показатель может включать значение функции потерь, значение метрики с использованием эталонной разметки или показатель качества прогнозируемой разметки без использования эталонной разметки.

Модуль выбора трудных обучающих примеров ранжирует выборки по ухудшению показателя качества либо сопоставляет показатели с распределением данных. Выборки с наихудшим качеством или с наименьшей вероятностью принадлежности распределению передают во вспомогательную генеративную модель вместе с соответствующими эталонными метками.

Вспомогательная генеративная модель формирует одно или более входных изображений, соответствующих эталонной метке трудной выборки. Сформированное изображение объединяют с указанной эталонной меткой, образуя дополнительную размеченную выборку. Дополнительные выборки добавляют к обучающим данным и используют при следующей эпохе обучения.

Критерием завершения может быть достижение заданного количества итераций, достижение заданной величины качества прогнозирования, стабилизация качества на проверочном наборе либо отсутствие существенного прироста качества после нескольких последовательных итераций.

```mermaid
flowchart TD
    A[Размеченные выборки] --> B[Эпоха обучения]
    B --> C[Оценка качества по каждой выборке]
    C --> D[Выбор трудных выборок]
    D --> E[Формирование входных изображений по эталонным меткам]
    E --> F[Добавление сформированных выборок]
    F --> G{{Критерий завершения выполнен}}
    G -- нет --> B
    G -- да --> H[Обученная глубокая нейронная сеть]
```

```mermaid
flowchart LR
    M1[Модуль обучения] --> M2[Модуль оценки качества]
    M2 --> M3[Модуль выбора трудных примеров]
    M3 --> M4[Вспомогательная генеративная модель]
    M4 --> M5[Память обучающих данных]
    M5 --> M1
```

```mermaid
flowchart LR
    L[Эталонная метка] --> G[Модель условной генерации]
    C[Обуславливающие данные] --> G
    G --> I[Сформированное входное изображение]
    I --> P[Дополнительная размеченная выборка]
    L --> P
```

## Формула изобретения

1. Способ обучения глубокой нейронной сети, содержащий этапы, на которых выполняют одну эпоху обучения глубокой нейронной сети на размеченных выборках; выполняют оценку качества прогнозирования глубокой нейронной сети на обучающих выборках с измерением качества прогнозирования для каждой обучающей выборки; выбирают выборки с наихудшим измеренным качеством прогнозирования в качестве трудных выборок; для каждой трудной выборки используют соответствующую ей эталонную метку для формирования входных изображений, соответствующих данной эталонной метке; добавляют сформированные входные изображения к обучающим данным для выполнения следующей эпохи обучения глубокой нейронной сети; повторяют указанные этапы один или более раз до выполнения критерия завершения обучения глубокой нейронной сети.

2. Способ по п. 1, в котором критерием завершения является выполнение заданного количества итераций обучения.

3. Способ по п. 1, в котором критерием завершения является достижение заданной величины качества прогнозирования.

4. Способ по п. 1, в котором во время эпохи обучения вычисляют один или более показателей для каждой обучающей выборки, сопоставляют вычисленные показатели с распределением данных и определяют трудные выборки как выборки с наименьшей вероятностью принадлежности указанному распределению.

5. Способ по п. 4, в котором показатель выбран из группы, включающей значение функции потерь, значение метрики расхождения между прогнозируемой разметкой и эталонной меткой, показатель качества прогнозируемой разметки и их комбинацию.

6. Способ по п. 4, в котором упомянутое распределение представляет собой Гауссово распределение.{poisson_claim}{brand_claim}

{system_offset}. Система для обучения глубокой нейронной сети, содержащая по меньшей мере один процессор и память, причем система содержит модуль обучения, выполненный с возможностью выполнения эпохи обучения глубокой нейронной сети на размеченных выборках; модуль оценки качества, выполненный с возможностью измерения качества прогнозирования для каждой обучающей выборки; модуль выбора трудных обучающих примеров, выполненный с возможностью выбора выборок с наихудшим измеренным качеством прогнозирования; и вспомогательную генеративную модель, выполненную с возможностью формирования входных изображений, соответствующих эталонной метке трудной выборки, при этом система выполнена с возможностью добавления сформированных входных изображений к обучающим данным и повторения обучения до выполнения критерия завершения.

{system_offset + 1}. Система по п. {system_offset}, в которой модуль выбора трудных обучающих примеров выполнен с возможностью сопоставления показателей качества с одномерным или многомерным распределением данных.

{system_offset + 2}. Система по п. {system_offset}, в которой вспомогательная генеративная модель выполнена с возможностью формирования входного изображения на основе эталонной метки и дополнительных обуславливающих данных.

## Реферат

Изобретение относится к вычислительной технике и предназначено для обучения глубоких нейронных сетей на размеченных данных. Выполняют эпоху обучения сети, оценивают качество прогнозирования для каждой обучающей выборки, выбирают трудные выборки, формируют для них дополнительные входные изображения на основе соответствующих эталонных меток, добавляют сформированные изображения к обучающим данным и повторяют цикл до выполнения критерия завершения. Система содержит модуль обучения, модуль оценки качества, модуль выбора трудных обучающих примеров, вспомогательную генеративную модель и память обучающих данных. Технический результат состоит в повышении стабильности качества прогнозирования глубокой нейронной сети на данных с разным уровнем сложности. 2 н. и зависимые пункты формулы, 3 ил.

## Фигуры

Фигуры приведены в описании и после рендеринга представлены PNG-изображениями.
"""


def extract_between(text: str, start: str, end: str) -> str:
    start_idx = text.find(start)
    if start_idx < 0:
        return ""
    end_idx = text.find(end, start_idx + len(start))
    if end_idx < 0:
        return text[start_idx:]
    return text[start_idx:end_idx]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Полный E2E smoke-тест patent-ru-skill на RU2844157C1."
    )
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--tool-smoke-dir", type=Path, default=DEFAULT_TOOL_SMOKE_DIR)
    parser.add_argument("--skip-fips", action="store_true", help="Не запускать live-поиск ФИПС.")
    parser.add_argument(
        "--skip-failure-mode",
        action="store_true",
        help="Не запускать проверку неверного Browserless endpoint.",
    )
    args = parser.parse_args(argv)

    harness = Harness(
        case_dir=args.case_dir,
        tool_smoke_dir=args.tool_smoke_dir,
        skip_fips=args.skip_fips,
        skip_failure_mode=args.skip_failure_mode,
    )
    steps = [
        harness.prepare_dirs,
        harness.preflight,
        harness.tool_smoke,
        harness.fips_checks,
        harness.write_fixture_files,
        harness.build_disclosure_versions,
        harness.validate_artifacts,
        harness.failure_mode,
    ]

    for step in steps:
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - report and continue
            harness.record(step.__name__, False, str(exc))

    report = harness.write_report()
    print(f"E2E_REPORT={report.relative_to(ROOT)}")
    for result in harness.results:
        print(f"{result.status:4} {result.name}")
        if result.details and result.status != "PASS":
            print("     " + result.details.replace("\n", "\n     "))
    failed = harness.failed()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
