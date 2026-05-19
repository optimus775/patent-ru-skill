# Структура skill

## Принципы

- `SKILL.md` остается короткой входной точкой: триггеры, инструменты, маршрут по prompt-файлам.
- Детальные инструкции находятся в `prompts/`, чтобы агент читал только нужный этап.
- `tools/` содержит детерминированные утилиты для конвертации Office, Markdown/Word, mermaid, поиска ФИПС и журналирования итераций.
- `examples/` содержит только демонстрационные исходные материалы; результаты запусков пишутся в `outputs/`.

## Каталоги

| Путь | Описание |
|---|---|
| `SKILL.md` | имя `patent-ru-skill`, workflow российской заявки |
| `prompts/intake.md` | сбор границ и типа объекта |
| `prompts/project_scan.md` | сканирование материалов и Office-конвертация |
| `prompts/patent_points_analyzer.md` | выделение и выбор технического решения |
| `prompts/prior_art_search.md` | поиск уровня техники через Google Patents и ФИПС |
| `prompts/disclosure_builder.md` | сборка описания, формулы, реферата и фигур |
| `prompts/template_reference.md` | шаблоны и примеры формулировок |
| `prompts/disclosure_self_check.md` | внутренняя проверка комплекта |
| `prompts/iteration_context.md` | общие правила итераций |
| `tools/` | `md_to_docx.py`, `docx_to_md.py`, `pptx_to_md.py`, `mermaid_render.py`, `iteration_dialog_log.py`, `fips_search.py` |
| `docs/` | PRD и описание структуры |
| `examples/` | пример входных материалов |

## Выходные файлы

По умолчанию итоговые документы сохраняются в `outputs/{case}/`:

```text
{название_изобретения}_{YYYYMMDDHHmmss}.md
{название_изобретения}_{YYYYMMDDHHmmss}.docx
revision_dialog_log.md
```

Старые версии не перезаписываются без прямой просьбы пользователя.
