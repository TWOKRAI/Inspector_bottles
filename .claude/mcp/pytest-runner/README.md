# pytest-runner (test-runner-mcp) — структурный запуск pytest

[test-runner-mcp](https://github.com/privsim/mcp-test-runner) — мульти-фреймворковый MCP-сервер на Node.js. Даёт агенту структурный (parseable) запуск pytest вместо парсинга `stdout`. Поддерживает pytest, jest, bats, flutter, go, rust.

## ⚠️ Статус выбора пакета

Первоначально упомянутый `jwilger/mcp-pytest-runner` — **репо больше не существует** (404). Из живых альтернатив:

| Пакет | Зрелость | Стек | Решение |
|-------|----------|------|---------|
| `privsim/mcp-test-runner` | Активен, multi-framework | Node.js (npm) | **Берём** |
| `kieranlal/mcp_pytest_service` | 3 commit, эксп. | Python | Слишком сырой |
| Прямой запуск через Bash MCP | — | — | Workable fallback |

Если в будущем появится зрелый Python-native pytest-MCP — заменим. Сейчас Node-вариант стабильнее.

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
