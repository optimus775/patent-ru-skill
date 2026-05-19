# Установка

Репозиторий является корнем Agent Skill: файл `SKILL.md` должен находиться в корне каталога skill.

## Claude Code

Установка в проект:

```bash
mkdir -p .claude/skills
git clone <repo-url> .claude/skills/patent-ru-skill
```

Глобальная установка:

```bash
mkdir -p ~/.claude/skills
git clone <repo-url> ~/.claude/skills/patent-ru-skill
```

В средах Claude Code и совместимых хостах переменная `CLAUDE_SKILL_DIR` обычно указывает на каталог skill. В prompt-файлах пути вида `${CLAUDE_SKILL_DIR}/tools/...` должны разрешаться в этот каталог.

## Cursor

Поместите полный каталог репозитория в один из путей:

| Система | Рекомендуемый путь |
|---|---|
| Linux / macOS | `~/.cursor/skills/patent-ru-skill/` |
| Windows | `%USERPROFILE%\.cursor\skills\patent-ru-skill\` |

Пример:

```bash
mkdir -p ~/.cursor/skills
git clone <repo-url> ~/.cursor/skills/patent-ru-skill
```

После перезапуска Cursor skill должен быть доступен как `patent-ru-skill`.

## Зависимости

### Базовые инструменты

Нужны для конвертации Word/PowerPoint и генерации `.docx`:

```bash
pip install -r requirements.txt
```

### Mermaid

Для преобразования fenced `mermaid` в PNG нужен Node.js и `mmdc`.

Рекомендуемый локальный вариант:

```bash
cd tools
npm install
```

Если `mmdc` не находит Chrome, выполните:

```bash
npx puppeteer browsers install chrome-headless-shell
```

### CNIPA-поиск

CNIPA-поиск временно сохранен без изменения логики. Для его работы:

```bash
pip install -r tools/requirements-cnipa.txt
python -m playwright install chromium
```

Если зависимости CNIPA не установлены, этап поиска уровня техники может использовать WebSearch и другие открытые источники.

## Проверка

```bash
python tools/md_to_docx.py --help
python tools/docx_to_md.py --help
python tools/pptx_to_md.py --help
python tools/mermaid_render.py --help
python tools/iteration_dialog_log.py --help
```
