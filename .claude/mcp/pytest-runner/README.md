# pytest-runner — **отложено** ⚠️

> **Статус на 2026-05:** интеграция MCP-сервера для структурного запуска pytest **отложена**. На рынке нет зрелого опубликованного пакета. Эта папка остаётся как живая референс-документация на случай появления подходящего проекта.

## Что не получилось

Проверены три кандидата — ни один не подошёл:

| Кандидат | Проблема |
|----------|----------|
| `jwilger/mcp-pytest-runner` | GitHub 404 — репо удалено |
| `test-runner-mcp` (npm) | **404 в npm registry** (`npm view` подтверждает) — пакет упомянут только в README `privsim/mcp-test-runner`, но не публикуется |
| `privsim/mcp-test-runner` | Node-проект на GitHub: требует `git clone` + `npm run build` локально; нестабильно для long-term зависимости |
| `kieranlal/mcp_pytest_service` | 3 коммита, экспериментальный, npm-пакет не существует |

Из конфига MCP сервер `test-runner` **убран** — он стабильно падал с Failed при попытке `npx -y test-runner-mcp` (нечего скачивать).

## Текущее решение

Прямой запуск pytest через **Bash MCP** (встроенный в Claude Code) — рабочий fallback. Команды:

```powershell
# полный suite
make test

# прицельный тест через Bash MCP
python -m pytest multiprocess_framework/modules/router/tests/test_routing.py::test_field_routing -v

# по marker / -k pattern
python -m pytest -k routing -v
```

Tester / Debugger агенты — пользуются обычным `Bash` MCP. Это работает; теряем только структурный JSON-output для парсинга агентом.

## Когда вернуться

Появится один из:
- Pytest-native MCP-сервер с реальной публикацией на PyPI
- Опубликованный npm-пакет (не git-only) с поддержкой Windows
- Anthropic-official Test MCP Server

Тогда:
1. Восстановить блок `test-runner` в `.mcp.json` / `mcp.template.json`
2. Обновить этот README и SETUP_GUIDE под актуальный пакет
3. Прописать в промптах Tester/Debugger

## Когда звать

| Задача | Инструмент |
|--------|-----------|
| Прогон полного suite в CI | `make test` (как раньше) |
| Tester-агент пишет новый тест и хочет видеть фокусированный результат | **test-runner** |
| Debugger-агент запускает одиночный тест по `nodeid` | **test-runner** |
| Прогон по параметризации/marker | **test-runner** |
| Smoke перед `/ship` | `make gate` (как раньше) |

Главное value-prop: **структурный JSON-выход** вместо парсинга текста. Агент получает массив `{nodeid, status, duration, error}` — лучше для рассуждений.

## Зависимости

- **Node.js ≥ 18** (`winget install OpenJS.NodeJS.LTS`) — уже установлен (v20.20.2)
- **pytest** в проекте (уже есть)

## Быстрый старт (Windows)

Глобальная установка **не нужна** — используется `npx -y` (как в Context7). Первый запуск Claude Code сам скачает пакет в кэш npx.

```powershell
# 1. Проверка зависимостей
node --version    # v18+
npm --version

# 2. Smoke-проверка (опционально — npx скачает пакет и покажет help)
npx -y test-runner-mcp --help
```

## Подключение к Claude Code

Уже добавлено в `.mcp.json`:

```json
"test-runner": {
  "command": "npx",
  "args": ["-y", "test-runner-mcp"]
}
```

`-y` — auto-confirm для скачивания. После перезапуска Claude Code — проверь `/mcp`.

> Альтернатива: `npm install -g test-runner-mcp` — глобальная установка ускорит запуск (npx-кэш переиспользуется, но первый запуск всё равно медленнее). На многих machine может блокироваться permission-системой. С `npx -y` это не требуется.

## Использование

Один tool — `run_tests` — с параметрами:

| Параметр | Значение для Inspector_bottles |
|----------|-------------------------------|
| `command` | `"pytest multiprocess_framework/modules/X/tests -v"` |
| `framework` | `"pytest"` |
| `workingDir` | корень проекта (Claude передаёт cwd сам) |
| `timeout` | `120000` (мс) для длинных тестов |
| `env` | `{"INSPECTOR_LOG_DIR": "..."}` если нужно |

Пример агентского вызова:

```
Запусти mcp__test_runner__run_tests с command="pytest -k test_routing -v"
и framework="pytest". Покажи мне failures.
```

## Полный гайд

См. [SETUP_GUIDE.md](SETUP_GUIDE.md) — установка Node, конфигурация npm, конфликты с pytest-qt, альтернативы.

## Ссылки

- Репо: https://github.com/privsim/mcp-test-runner
- Анализ MCP-pytest tools: https://skywork.ai/skypage/en/A-Deep-Dive-into-pytest-mcp-server:-Bridging-Pytest-with-AI-Agents/
