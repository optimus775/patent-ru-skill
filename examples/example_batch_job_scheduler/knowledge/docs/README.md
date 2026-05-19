# docs / проектные материалы и Office-примеры

## Markdown

| Файл | Описание |
|---|---|
| `architecture.md` | Текстовое описание архитектуры планировщика пакетных задач |

## Word / PowerPoint

Файлы используются для проверки `tools/docx_to_md.py` и `tools/pptx_to_md.py`. Они описывают тот же вымышленный пример, что и `architecture.md`.

По правилам `prompts/project_scan.md` агент должен сначала конвертировать `.docx` и `.pptx` в Markdown, а затем читать полученные `.md` файлы. Отдельные PNG из `sample_assets/` не требуют самостоятельного анализа, если они уже продублированы во вложениях Office.

| Файл | Описание |
|---|---|
| `sample_architecture_review.docx` | Вымышленная заметка архитектурного обзора с вложенными PNG |
| `sample_scheduler_deck.pptx` | Вымышленная презентация с несколькими слайдами |
| `sample_assets/sample_fig_modules.png` | Схема модулей без текстовых подписей |
| `sample_assets/sample_fig_queue.png` | Схема очереди и узлов без текстовых подписей |
