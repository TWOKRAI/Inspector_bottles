# test-runner-mcp — полный гайд установки

## Что это и почему такой выбор

MCP-сервер для запуска тестов с парсингом результатов в структурный формат. На вход — команда (`pytest ...`), на выход — JSON с `pass/fail/skip` по каждому test-id, длительности, трейсбэками.

Альтернативы и почему не они:

| Кандидат | Минус |
|----------|-------|
| `jwilger/mcp-pytest-runner` | Репо 404 |
| `kieranlal/mcp_pytest_service` | 3 коммита, npm-пакет неопубликован |
| `pytest-mcp` (PyPI) | Это фреймворк для **тестирования MCP-серверов**, не runner pytest |
| Bash `pytest ...` | Работает, но stdout-парсинг хуже |

`test-runner-mcp` (privsim) — живой, multi-framework, стабильный npm-пакет.

## Зависимости

| Компонент | Версия | Установка (Windows) |
|-----------|--------|---------------------|
| Node.js | ≥ 18 LTS | `winget install OpenJS.NodeJS.LTS` |
| npm | поставляется с Node | автоматически |
| pytest | уже в проекте | `uv sync` |

Проверь:

```powershell
node --version    # должно быть v18+
npm --version
pytest --version
```

## Установка

Глобальная установка **не требуется** — используем `npx -y` (как Context7). Первый запуск Claude Code скачает пакет в кэш npm (`~/AppData/Local/npm-cache/_npx` на Windows).

```powershell
# Smoke-проверка
npx -y test-runner-mcp --help
```

Если нужно ускорить запуск (избавиться от cold-start npx) — можно поставить глобально:

```powershell
npm install -g test-runner-mcp
where.exe test-runner-mcp
```

⚠️ `npm install -g` иногда блокируется permission-настройками Claude Code или системы. Если упало — оставляй `npx -y`, оно работает без глобального бинаря.

## Конфигурация MCP

В `.mcp.json`:

```json
"test-runner": {
  "command": "npx",
  "args": ["-y", "test-runner-mcp"]
}
```

`-y` — auto-confirm для скачивания/обновления пакета. После — **перезапуск Claude Code**, проверка `/mcp`.

## Использование с pytest

Сервер экспортирует один tool — `run_tests`. Параметры (типовые сценарии для проекта):

### Прогон всего suite

```
{
  "command": "python -m pytest",
  "framework": "pytest"
}
```

### Прогон тестов одного модуля

```
{
  "command": "python -m pytest multiprocess_framework/modules/router/tests -v",
  "framework": "pytest",
  "timeout": 60000
}
```

### Прогон одного теста по nodeid

```
{
  "command": "python -m pytest multiprocess_framework/modules/router/tests/test_routing.py::test_field_routing -v",
  "framework": "pytest"
}
```

### С env

```
{
  "command": "python -m pytest -v",
  "framework": "pytest",
  "env": {
    "INSPECTOR_LOG_DIR": "logs/test",
    "MULTIPROCESS_LOG_DIR": "logs/test"
  }
}
```

## Важно: PYTHONPATH и cwd

Из правил проекта: **ручной pytest запускать из корня** (иначе `ModuleNotFoundError`). test-runner-mcp получает cwd от Claude Code — это уже корень проекта. Но если будут падения с `ImportError`, явно укажи `workingDir`:

```json
{
  "command": "python -m pytest",
  "framework": "pytest",
  "workingDir": "D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles"
}
```

## Конфликт с pytest-qt

Тесты PySide6 через `pytest-qt` требуют:
- `qt_api = pyside6` в `pyproject.toml` (уже есть)
- `pytest-qt` plugin (тоже есть)
- Иногда — display server. На Windows работает «из коробки».

test-runner-mcp **прозрачен** для pytest-qt — он просто запускает `pytest` как subprocess. Никаких дополнительных настроек не нужно.

## Сравнение с make test

| Сценарий | Чем пользоваться |
|----------|------------------|
| Полный gate перед коммитом | `make gate` (ruff + mypy + pytest + coverage) |
| Прогон одного модуля для дебага | **test-runner-mcp** через агента |
| CI | `make test` (без MCP вообще) |
| Структурный анализ failures агентом | **test-runner-mcp** |

test-runner-mcp **не заменяет** `make test` — он дополняет его для агентских циклов.

## Использование в агентах

В промпт Tester / Debugger:

```
**test-runner-mcp:** для прицельного запуска конкретного теста (по nodeid
или -k pattern) — звать mcp__test_runner__run_tests. Парсить stdout
вручную не нужно — приходит структурный JSON с pass/fail/durations.
Для полного gate перед /ship — оставлять `make gate`.
```

## Troubleshooting

### `test-runner-mcp` не найден после `npm install -g`

```powershell
# Проверь npm prefix
npm config get prefix
# Обычно %APPDATA%\npm — должно быть в PATH
$env:Path += ";$env:APPDATA\npm"
```

### MCP-сервер падает на старте

Версия Node старше 18? `node --version`. Обнови через winget.

### Тесты падают по `ImportError` хотя `make test` проходит

cwd не корень проекта. Прописать `workingDir` в параметрах вызова (см. выше).

### Timeout на больших suite

```json
{ "timeout": 600000 }  // 10 минут
```

## Ссылки

- Репо: https://github.com/privsim/mcp-test-runner
- npm-пакет: https://www.npmjs.com/package/test-runner-mcp
- pytest docs: https://docs.pytest.org/
- pytest-qt docs: https://pytest-qt.readthedocs.io/
