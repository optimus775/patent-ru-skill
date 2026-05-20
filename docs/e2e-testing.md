# Полное E2E-тестирование пайплайна

Этот документ описывает воспроизводимый прогон `patent-ru-skill` на гражданском IT/AI fixture `RU2844157C1`: «Способ и система для обучения глубокой нейронной сети с помощью дополнительных формируемых данных».

Сценарий исключает беспилотники, военную, оружейную, боеприпасную, радиолокационную и смежную double-use тематику.

## Подготовка окружения

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r tools/requirements-fips.txt
(cd tools && npm install)
```

Для live-проверок ФИПС должен быть задан `BROWSERLESS_WS_ENDPOINT` в окружении или в локальном `.env`. Скрипт проверяет наличие ключа, но не выводит значение endpoint или token.

В sandbox-limited Linux-окружениях runner передает `mermaid_render.py` переменную `MERMAID_PUPPETEER_CONFIG` с локальным Puppeteer config, включающим `--no-sandbox`. Обычный CLI `mermaid_render.py` без этой переменной работает как раньше.

## Полный запуск

```bash
.venv/bin/python tools/e2e_ru2844157_ai_training.py
```

Основные результаты создаются в:

```text
outputs/e2e_ru2844157_ai_training/
outputs/tool_smoke/
```

Ключевые артефакты:

- `patent_fixture.json` - фиксированный fixture по `RU2844157C1`;
- `prior_art_notes.md` и `preview.md` - проверяемые рабочие материалы;
- три версии комплекта `.md`/`.docx`, включая итерационную правку;
- `revision_dialog_log.md` - журнал итераций;
- `self_check_report.json` и `e2e_report.json` - машинно-читаемые отчеты проверок.

## Offline-режим

Если ФИПС или Browserless временно недоступны, можно проверить локальные инструменты, сборку и валидацию артефактов без live-поиска:

```bash
.venv/bin/python tools/e2e_ru2844157_ai_training.py --skip-fips
```

Проверку неверного Browserless endpoint можно отключить отдельно:

```bash
.venv/bin/python tools/e2e_ru2844157_ai_training.py --skip-failure-mode
```

## Что Проверяется

- `unittest discover` для существующих unit-тестов;
- `--help` для `fips_search.py`, `docx_to_md.py`, `pptx_to_md.py`, `md_to_docx.py`, `mermaid_render.py`, `iteration_dialog_log.py`;
- конвертация примерных `.docx` и `.pptx`;
- Markdown -> Word с таблицей, списком и PNG;
- Mermaid -> PNG с сохранением невалидного блока без падения всего процесса;
- ФИПС broad/refine: `RU2844157` должен находиться по теме обучения глубокой нейронной сети, а refined-поиск должен поставить его на `rank 1`;
- итоговый комплект содержит российскую структуру заявки, Word-экспорт, PNG-фигуры и журнал итераций;
- финальные Markdown-артефакты не содержат запрещенных тематик, служебных строк, секретов, `self-check`, ссылок на skill или `.env`;
- после коррекционной итерации конкретные названия `ControlNet`/`UniControlNet` отсутствуют в формуле, но могут оставаться как примеры в описании.

## Критерий Успеха

Команда полного запуска должна завершиться с кодом `0` и напечатать путь вида:

```text
E2E_REPORT=outputs/e2e_ru2844157_ai_training/e2e_report.json
```

Если команда возвращает ненулевой код, откройте `e2e_report.json`: каждый шаг содержит `PASS`, `FAIL` или `SKIP`, краткую причину и связанные артефакты.
