# Инструменты

Каталог содержит вспомогательные скрипты для `patent-ru-skill`.

## Зависимости

Базовые инструменты конвертации:

```bash
pip install -r requirements.txt
```

Поиск ФИПС через Browserless:

```bash
pip install -r tools/requirements-fips.txt
cp .env.example .env
```

В `.env` укажите `BROWSERLESS_WS_ENDPOINT`. Локальный Chromium не нужен: Playwright подключается к удаленному Browserless по CDP.

Рендер Mermaid:

```bash
cd tools
npm install
```

Если Puppeteer не находит Chrome:

```bash
npx puppeteer browsers install chrome-headless-shell
```

## mermaid_render.py

Рендерит fenced `mermaid` блоки в Markdown в PNG и заменяет каждый блок ссылкой на изображение. По умолчанию также вызывает `md_to_docx.py` и создает одноименный `.docx`.

```bash
python3 tools/mermaid_render.py -i draft.md -o "Название_изобретения_20260519120000.md"
python3 tools/mermaid_render.py -i draft.md -o out/final.md --docx out/final.docx
python3 tools/mermaid_render.py -i draft.md -o out/final.md --no-docx
```

Порядок поиска `mmdc`:

1. `tools/node_modules/.bin/mmdc`;
2. `mmdc` в `PATH`;
3. `npx -y @mermaid-js/mermaid-cli mmdc`.

Если один mermaid-блок не рендерится, его исходный fence сохраняется, а остальные блоки продолжают обрабатываться.

В sandbox-limited Linux-окружениях можно передать Puppeteer config через переменную `MERMAID_PUPPETEER_CONFIG`:

```bash
MERMAID_PUPPETEER_CONFIG=puppeteer-no-sandbox.json \
  python3 tools/mermaid_render.py -i draft.md -o out/final.md
```

В Linux, если `MERMAID_PUPPETEER_CONFIG` не задан, `mermaid_render.py` по умолчанию сразу передает временный Puppeteer config с `--no-sandbox`, чтобы не провоцировать `chrome-headless` coredump в sandbox-limited окружениях. Чтобы отключить это поведение, установите `MERMAID_PUPPETEER_NO_SANDBOX=0`.

## md_to_docx.py

Конвертирует Markdown в Word.

```bash
python3 tools/md_to_docx.py --input path/to/application.md --output path/to/application.docx
python3 tools/md_to_docx.py -i path/to/application.md -o path/to/application.docx --base-dir path/to
```

Поддерживаемое подмножество Markdown:

| Элемент | Поведение |
|---|---|
| `#` to `######` | стили заголовков Word |
| абзацы | основной текст с поддержкой жирного и inline code |
| списки | простые нумерованные и маркированные списки |
| fenced code | моноширинный блок кода |
| GFM-таблицы | простая таблица Word |
| `>` | цитата с отступом |
| `---` | горизонтальная линия |
| `![](path)` | изображение относительно `--base-dir` или каталога Markdown |

Если в черновике есть mermaid, перед финальным Word-конвертом запустите `mermaid_render.py`.

## docx_to_md.py

Конвертирует входные `.docx` материалы в Markdown и извлекает встроенные изображения.

```bash
python3 tools/docx_to_md.py --input path/to/design.docx --output outputs/case/design.md
python3 tools/docx_to_md.py -i a.docx -o b/out.md --media-dir b/media
```

Поддерживается OOXML `.docx`; старые `.doc` файлы нужно предварительно сохранить в новом формате.

## pptx_to_md.py

Конвертирует `.pptx` или `.ppsx` материалы в Markdown и извлекает встроенные bitmap-изображения.

```bash
python3 tools/pptx_to_md.py --input path/to/review.pptx --output outputs/case/review.md
python3 tools/pptx_to_md.py -i a.pptx -o b/out.md --media-dir b/media
```

Выход содержит отдельный Markdown-раздел на каждый слайд, извлеченный текст, простые таблицы, заметки при наличии и ссылки на изображения.

## iteration_dialog_log.py

Добавляет запись об итерации в `revision_dialog_log.md` в каталоге дела.

```bash
python3 tools/iteration_dialog_log.py --case-dir outputs/case --kind merge \
  --user "Добавлен вариант осуществления и обновлена формула." \
  --summary "Обновлены описание и зависимые пункты формулы." \
  --artifacts "Название_20260519120000.md,Название_20260519120000.docx"
```

Для исправлений используйте `--kind correct`.

## fips_search.py

Ищет российские патентные документы в ФИПС через Browserless.

```bash
python3 tools/fips_search.py "управление очередью" --limit 20
```

Для сужения большой выдачи используйте ранжированный режим:

```bash
python3 tools/fips_search.py "управление очередью" \
  --refine \
  --feature "диспетчеризация очередей" \
  --feature "приоритет обработки" \
  --effect "снижение задержки" \
  --domain "сеть связи" \
  --exclude "газоперекачивающ" \
  --top-k 10
```

`--refine` выполняет серию запросов по основной области, названию, реферату, формуле и МПК, объединяет дубликаты и добавляет к результатам `rank`, `score`, `score_reasons`, `matched_queries`. При необходимости можно добавить `--ipc "H04W 28/10"` и ограничить число открываемых карточек через `--details-limit`.

По умолчанию refined-режим запускает все сгенерированные подзапросы и открывает до 5 карточек для уточнения деталей. Для быстрой проверки можно ограничить глубину через `--max-refine-queries 3 --details-limit 0`; для более глубокого медленного прогона увеличьте `--details-limit`.

Stdout содержит одну машинно-читаемую строку:

```text
FIPS_HITS_JSON: [...]
```

Если `BROWSERLESS_WS_ENDPOINT` не задан или ФИПС недоступен, скрипт возвращает структурированный элемент с `error_code`; endpoint и token не печатаются.
