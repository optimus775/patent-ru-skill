#!/usr/bin/env python3
"""Добавляет запись в журнал итераций каталога патентного дела."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG = "revision_dialog_log.md"

FILE_HEADER = """# Журнал итераций

> Записи добавляются `iteration_dialog_log.py` или агентом по правилам `prompts/iteration_context.md`.

"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Добавить запись в Markdown-журнал итераций дела"
    )
    parser.add_argument(
        "--case-dir",
        type=Path,
        required=True,
        help="Каталог результатов дела; должен существовать",
    )
    parser.add_argument(
        "--kind",
        choices=("merge", "correct"),
        required=True,
        help="merge=объединение материалов; correct=исправление",
    )
    parser.add_argument(
        "--user",
        default="",
        help="Краткое содержание текущего запроса пользователя",
    )
    parser.add_argument(
        "--summary",
        default="",
        help="Краткая выдержка из сводки объединения или исправления",
    )
    parser.add_argument(
        "--artifacts",
        default="",
        help="Имена выданных файлов через запятую",
    )
    parser.add_argument(
        "--log-name",
        default=DEFAULT_LOG,
        help=f"Имя файла журнала; по умолчанию {DEFAULT_LOG}",
    )
    args = parser.parse_args()

    case_dir = args.case_dir.expanduser().resolve()
    if not case_dir.is_dir():
        print(f"ERROR: каталог не существует или не является каталогом: {case_dir}", file=sys.stderr)
        return 2

    log_path = case_dir / args.log_name
    now_local = datetime.now().astimezone()
    now_utc = datetime.now(timezone.utc)
    kind_label = "объединение материалов" if args.kind == "merge" else "исправление"

    user_block = (args.user or "").strip() or "(Не передан --user; при необходимости заполните краткое содержание запроса.)"
    summary_block = (args.summary or "").strip() or "-"
    art = (args.artifacts or "").strip()
    if art:
        art_lines = "\n".join(f"- `{x.strip()}`" for x in art.split(",") if x.strip())
    else:
        art_lines = "-"

    entry = f"""## {now_local.strftime("%Y-%m-%d %H:%M:%S")} local - {now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")} UTC

**Тип**: {kind_label}

**Краткое содержание запроса**:

{user_block}

**Выданные файлы**:

{art_lines}

**Выдержка из сводки**:

{summary_block}

---

"""

    if log_path.exists():
        prev = log_path.read_text(encoding="utf-8")
        if prev and not prev.endswith("\n"):
            prev += "\n"
        log_path.write_text(prev + "\n" + entry, encoding="utf-8")
    else:
        log_path.write_text(FILE_HEADER + "\n" + entry, encoding="utf-8")

    print(f"LOG_FILE={log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
