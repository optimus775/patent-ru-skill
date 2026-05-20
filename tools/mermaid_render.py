#!/usr/bin/env python3
"""
Рендерит fenced mermaid-блоки в Markdown в PNG и заменяет каждый блок ссылкой на
изображение, чтобы `md_to_docx.py` мог встроить фигуры в Word.

Порядок поиска backend для Mermaid:
1. `tools/node_modules/.bin/mmdc` после локального `npm install`;
2. `mmdc` в PATH;
3. `npx -y @mermaid-js/mermaid-cli mmdc`.

Для черновиков патентной заявки используйте fenced mermaid как рабочий формат
фигур и запускайте этот скрипт перед выдачей Markdown/Word.

Если один mermaid-блок не рендерится, скрипт сохраняет исходный fence, рендерит
остальные блоки, записывает Markdown и все равно пробует создать Word.

Параметры viewport и scale по умолчанию подобраны для читаемых фигур в Word.

Примеры:
  python tools/mermaid_render.py -i draft.md -o disclosure.md
  # По умолчанию также записывает disclosure.docx.
  python tools/mermaid_render.py -i draft.md -o out/disclosure.md --docx out/custom.docx
  python tools/mermaid_render.py -i draft.md -o disclosure.md --no-docx

Ошибка конвертации Word не прерывает процесс; скрипт печатает команду для ручного запуска.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _local_mmdc() -> tuple[list[str], bool] | None:
    """Использует локальный node_modules/.bin/mmdc, если он доступен."""
    here = Path(__file__).resolve().parent
    if sys.platform == "win32":
        cand = here / "node_modules" / ".bin" / "mmdc.cmd"
    else:
        cand = here / "node_modules" / ".bin" / "mmdc"
    if cand.is_file():
        return [str(cand)], False
    return None


def _find_mmdc_invocation() -> tuple[list[str], bool]:
    """
    Возвращает (argv prefix, use_shell).
    В Windows npx может быть .ps1-wrapper и требовать shell=True.
    """
    local = _local_mmdc()
    if local:
        return local
    mmdc = shutil.which("mmdc")
    if mmdc and Path(mmdc).suffix.lower() not in (".ps1",):
        return [mmdc], False
    if sys.platform == "win32":
        return ["npx", "-y", "@mermaid-js/mermaid-cli", "mmdc"], True
    return ["npx", "-y", "@mermaid-js/mermaid-cli", "mmdc"], False


def _mmdc_extra_args(
    *,
    scale: float,
    width: int,
    height: int,
) -> list[str]:
    """Формирует параметры разрешения для mmdc."""
    args = [
        "-s",
        str(scale),
        "-w",
        str(width),
        "-H",
        str(height),
    ]
    puppeteer_config = os.environ.get("MERMAID_PUPPETEER_CONFIG", "").strip()
    if puppeteer_config:
        args.extend(["-p", puppeteer_config])
    return args


def _render_one_mermaid(
    mermaid_source: str,
    png_path: Path,
    mmdc_base: list[str],
    *,
    use_shell: bool,
    scale: float,
    width: int,
    height: int,
) -> None:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".mmd",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(mermaid_source.strip() + "\n")
        tmp_path = Path(tmp.name)
    try:
        extra = _mmdc_extra_args(scale=scale, width=width, height=height)
        if use_shell:
            parts = [
                *mmdc_base,
                "-i",
                str(tmp_path),
                "-o",
                str(png_path),
                "-b",
                "white",
                *extra,
            ]
            cmd = " ".join(shlex.quote(p) for p in parts)
            r = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
        else:
            cmd = [
                *mmdc_base,
                "-i",
                str(tmp_path),
                "-o",
                str(png_path),
                "-b",
                "white",
                *extra,
            ]
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
            )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            raise RuntimeError(f"mmdc завершился с ошибкой (exit {r.returncode}): {err[:2000]}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


_MMD_START = re.compile(r"^```mermaid\s*$", re.IGNORECASE)
_MMD_END = re.compile(r"^```\s*$")


def render_markdown_mermaid(
    md_text: str,
    *,
    out_md_path: Path,
    assets_rel: str,
    mmdc_scale: float = 2.0,
    mmdc_width: int = 1400,
    mmdc_height: int = 1050,
) -> tuple[str, int, int]:
    """
    Возвращает (новый Markdown, число успешных блоков, число неудачных блоков).
    Неудачные блоки возвращаются в исходном fenced mermaid виде.
    """
    lines = md_text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    ok = 0
    failed = 0
    block_idx = 0
    assets_dir = out_md_path.parent / assets_rel
    mmdc_base, use_shell = _find_mmdc_invocation()

    while i < len(lines):
        line = lines[i]
        if _MMD_START.match(line):
            fence_open = line
            i += 1
            body: list[str] = []
            while i < len(lines) and not _MMD_END.match(lines[i]):
                body.append(lines[i])
                i += 1
            closing = lines[i] if i < len(lines) else "```\n"
            if i < len(lines):
                i += 1
            block_idx += 1
            fname = f"fig_{ok + 1:03d}.png"
            png_path = assets_dir / fname
            try:
                _render_one_mermaid(
                    "".join(body),
                    png_path,
                    mmdc_base,
                    use_shell=use_shell,
                    scale=mmdc_scale,
                    width=mmdc_width,
                    height=mmdc_height,
                )
            except Exception as e:
                failed += 1
                print(
                    f"[mermaid_render] mermaid-блок {block_idx} не отрендерен; исходник сохранен: {e}",
                    file=sys.stderr,
                )
                out.append(fence_open)
                out.extend(body)
                if not closing.endswith("\n"):
                    closing = closing + "\n"
                out.append(closing)
                continue
            ok += 1
            rel = f"{assets_rel.strip('/')}/{fname}".replace("\\", "/")
            out.append("\n")
            out.append(f"![Фиг. {ok}]({rel})\n")
            out.append("\n")
            continue
        out.append(line)
        i += 1

    return "".join(out), ok, failed


def _print_manual_docx_hint(out_md: Path, docx_out: Path, base_dir: Path, md_script: Path) -> None:
    print(
        "Подсказка: Markdown можно вручную конвертировать в Word после установки requirements.txt:",
        file=sys.stderr,
    )
    if md_script.is_file():
        parts = [
            sys.executable,
            str(md_script),
            "-i",
            str(out_md),
            "-o",
            str(docx_out),
            "--base-dir",
            str(base_dir),
        ]
        print("  " + " ".join(shlex.quote(p) for p in parts), file=sys.stderr)
    else:
        print(
            "  python tools/md_to_docx.py -i <output.md> -o <output.docx> --base-dir <md directory>",
            file=sys.stderr,
        )


def try_write_docx(out_md: Path, docx_out: Path) -> bool:
    """
    Вызывает соседний md_to_docx.py. Возвращает True при успехе и False при ошибке.
    """
    tools_dir = Path(__file__).resolve().parent
    md_script = tools_dir / "md_to_docx.py"
    base_dir = out_md.parent
    docx_out.parent.mkdir(parents=True, exist_ok=True)

    if not md_script.is_file():
        print("Предупреждение: md_to_docx.py не найден; Word не создается.", file=sys.stderr)
        _print_manual_docx_hint(out_md, docx_out, base_dir, md_script)
        return False

    cmd = [
        sys.executable,
        str(md_script),
        "-i",
        str(out_md),
        "-o",
        str(docx_out),
        "--base-dir",
        str(base_dir),
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("Предупреждение: генерация Word превысила 300 секунд.", file=sys.stderr)
        _print_manual_docx_hint(out_md, docx_out, base_dir, md_script)
        return False
    except OSError as e:
        print(f"Предупреждение: не удалось запустить md_to_docx: {e}", file=sys.stderr)
        _print_manual_docx_hint(out_md, docx_out, base_dir, md_script)
        return False

    if r.returncode != 0:
        print(f"Предупреждение: md_to_docx завершился с кодом {r.returncode}.", file=sys.stderr)
        err = (r.stderr or r.stdout or "").strip()
        if err:
            print(err[:2000], file=sys.stderr)
        _print_manual_docx_hint(out_md, docx_out, base_dir, md_script)
        return False

    print(f"Word записан: {docx_out}", file=sys.stderr)
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Рендерит mermaid fences в PNG и опционально создает одноименный Word"
    )
    p.add_argument("-i", "--input", required=True, type=Path, help="Путь к входному .md")
    p.add_argument("-o", "--output", required=True, type=Path, help="Путь к выходному .md со ссылками на изображения")
    p.add_argument(
        "--assets-dir",
        default="mermaid_figures",
        help="Относительный каталог для PNG из mermaid; по умолчанию mermaid_figures",
    )
    p.add_argument(
        "--docx",
        type=Path,
        default=None,
        metavar="PATH",
        help="Путь к выходному .docx; по умолчанию имя -o с расширением .docx",
    )
    p.add_argument(
        "--no-docx",
        action="store_true",
        help="Не генерировать Word; записать только Markdown со ссылками на изображения",
    )
    p.add_argument(
        "--mmdc-scale",
        type=float,
        default=2.0,
        metavar="N",
        help="mmdc -s / масштаб Puppeteer; по умолчанию 2",
    )
    p.add_argument(
        "--mmdc-width",
        type=int,
        default=1400,
        metavar="PX",
        help="mmdc -w, ширина viewport в пикселях; по умолчанию 1400",
    )
    p.add_argument(
        "--mmdc-height",
        type=int,
        default=1050,
        metavar="PX",
        help="mmdc -H, высота viewport в пикселях; по умолчанию 1050",
    )
    args = p.parse_args(argv)
    if args.mmdc_scale <= 0:
        print("Ошибка: --mmdc-scale должен быть положительным", file=sys.stderr)
        return 1
    if args.mmdc_width < 400 or args.mmdc_height < 400:
        print("Ошибка: --mmdc-width и --mmdc-height должны быть не меньше 400", file=sys.stderr)
        return 1

    in_path = args.input.resolve()
    if not in_path.is_file():
        print(f"Ошибка: входной файл не найден: {in_path}", file=sys.stderr)
        return 1

    out_path = args.output.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        md = in_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        md = in_path.read_text(encoding="utf-8", errors="replace")

    new_md, n_ok, n_fail = render_markdown_mermaid(
        md,
        out_md_path=out_path,
        assets_rel=args.assets_dir.strip("/\\") or "mermaid_figures",
        mmdc_scale=args.mmdc_scale,
        mmdc_width=args.mmdc_width,
        mmdc_height=args.mmdc_height,
    )

    out_path.write_text(new_md, encoding="utf-8")
    parts = [f"Записано {out_path} (mermaid: {n_ok} блок(ов) преобразовано в PNG"]
    if n_fail:
        parts.append(f", {n_fail} блок(ов) не отрендерены и сохранены как fenced source")
    parts.append(")")
    print("".join(parts), file=sys.stderr)
    if n_fail:
        print(
            "[mermaid_render] Markdown создан"
            + ("; далее будет попытка создать Word" if not args.no_docx else "")
            + "; проверьте Node/mmdc или исправьте синтаксис mermaid перед повторным запуском.",
            file=sys.stderr,
        )

    if args.no_docx:
        return 0

    docx_path = (
        args.docx.resolve()
        if args.docx is not None
        else out_path.with_suffix(".docx")
    )
    try_write_docx(out_path, docx_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
