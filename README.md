<div align="center">

# patent-ru-skill

> Skill для подготовки материалов российской патентной заявки: анализ проекта, отбор технического решения, уровень техники, описание изобретения, формула, реферат и фигуры.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-mermaid%2Fmmdc-339933.svg)](https://nodejs.org/)
[![AgentSkills](https://img.shields.io/badge/AgentSkills-Standard-green)](https://agentskills.io)

[Возможности](#возможности) | [Установка](#установка) | [Использование](#использование) | [Структура](#структура) | [Пример](#пример) | [Документы](#документы)

</div>

---

## Возможности

| Возможность | Описание |
|---|---|
| Сканирование проекта | Читает документы, код, схемы и Office-материалы; `.docx`/`.pptx` перед анализом конвертируются в Markdown |
| Отбор решения | Выделяет кандидатные технические решения, проверяет техническую проблему, результат и существенные признаки |
| Уровень техники | Временно сохраняет CNIPA-first workflow из исходного форка; переход на ФИПС запланирован отдельной задачей |
| Российская структура | Готовит описание изобретения, формулу, реферат и фигуры по российской логике заявки |
| Фигуры | Использует `mermaid` как рабочий формат схем и `tools/mermaid_render.py` для PNG/Word |
| Итерации | Дорабатывает уже созданный комплект новым файлом и ведет `revision_dialog_log.md` |
| Self-check | Проверяет достаточность раскрытия, формулу, терминологию, уровень техники, реферат и фигуры |

## Установка

### Claude Code

```bash
mkdir -p .claude/skills
git clone <repo-url> .claude/skills/patent-ru-skill
```

### Cursor

Поместите полный каталог репозитория в один из путей skills, поддерживаемых Cursor, например:

```bash
mkdir -p ~/.cursor/skills
git clone <repo-url> ~/.cursor/skills/patent-ru-skill
```

После перезапуска Cursor проверьте, что skill виден в Settings / Rules или доступен через `/patent-ru-skill`.

### Зависимости

Базовые инструменты Office/Word:

```bash
pip install -r requirements.txt
```

Опционально для текущего CNIPA-поиска:

```bash
pip install -r tools/requirements-cnipa.txt
python -m playwright install chromium
```

Для рендера `mermaid` нужен Node.js. Рекомендуемый вариант:

```bash
cd tools
npm install
```

## Использование

Примеры запросов агенту:

```text
Используй patent-ru-skill и подготовь материалы российской заявки по проекту ./docs.
```

```text
Нужно выделить патентоспособное решение, подготовить описание изобретения, формулу, реферат и фигуры.
```

```text
Доработай существующий файл outputs/case/Способ..._20260519120000.md: добавь новый вариант осуществления и обнови формулу.
```

## Структура

```text
patent-ru-skill/
├── SKILL.md                    # входная точка skill
├── prompts/                    # поэтапные инструкции агенту
├── tools/                      # конвертация Office/Word, mermaid, CNIPA, журнал итераций
├── docs/                       # PRD и структура проекта
├── examples/                   # демонстрационный набор исходных материалов
├── outputs/                    # пользовательские результаты, игнорируются Git
├── requirements.txt
├── INSTALL.md
└── LICENSE
```

## Пример

Демонстрационные исходные материалы лежат в `examples/example_batch_job_scheduler/knowledge/`. Они показывают типовой набор: архитектурные заметки, Office-файлы и код. Результаты полного запуска создаются в `outputs/{case}/` и не коммитятся.

## Документы

- [SKILL.md](SKILL.md) - триггеры и основной workflow.
- [INSTALL.md](INSTALL.md) - детали установки.
- [tools/README.md](tools/README.md) - конвертация Markdown/Word, Office, mermaid и CNIPA.
- [docs/PRD.md](docs/PRD.md) - продуктовая логика.
- [docs/skill-structure.md](docs/skill-structure.md) - структура репозитория.
- [prompts/template_reference.md](prompts/template_reference.md) - шаблоны описания, формулы, реферата и фигур.

MIT License © исходный форк [handsomestWei](https://github.com/handsomestWei/)
