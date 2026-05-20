# Установка

Репозиторий является корнем Agent Skill: файл `SKILL.md` должен находиться в корне каталога skill.

## Codex

Рекомендуемый способ установки:

```bash
mkdir -p ~/.codex/skills
git clone <repo-url> ~/.codex/skills/patent-ru-skill
```

Если `CODEX_HOME` переопределен, используйте:

```bash
mkdir -p "$CODEX_HOME/skills"
git clone <repo-url> "$CODEX_HOME/skills/patent-ru-skill"
```

После перезапуска Codex skill должен быть доступен как `patent-ru-skill`.

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

### Поиск ФИПС через Browserless

Для официального поиска по российским патентным документам используется `tools/fips_search.py`, который подключается к отдельному Browserless-инстансу:

```bash
pip install -r tools/requirements-fips.txt
cp .env.example .env
```

В `.env` укажите полный WebSocket endpoint:

```dotenv
BROWSERLESS_WS_ENDPOINT=wss://production-sfo.browserless.io?token=YOUR_BROWSERLESS_TOKEN
```

Локальный Chromium устанавливать не нужно. Если Browserless не настроен или ФИПС недоступен, этап поиска уровня техники продолжает работу по Google Patents и другим проверяемым источникам.

## Проверка

```bash
python tools/md_to_docx.py --help
python tools/docx_to_md.py --help
python tools/pptx_to_md.py --help
python tools/mermaid_render.py --help
python tools/iteration_dialog_log.py --help
python tools/fips_search.py --help
```
