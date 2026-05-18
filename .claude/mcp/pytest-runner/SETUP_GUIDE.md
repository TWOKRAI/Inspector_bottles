# pytest-runner — детальный статус

Полный обзор причин отложения и проведённого ресёрча. См. также [README.md](README.md) — короткое резюме.

## Хронология

1. **План:** интегрировать MCP-сервер `jwilger/mcp-pytest-runner` (был упомянут в lobehub-каталоге).
2. **Обнаружено:** репо `jwilger/mcp-pytest-runner` — **GitHub 404**, удалён.
3. **Поиск замены:** найден `privsim/mcp-test-runner` (Node.js, multi-framework). Его README рекомендует `npm install test-runner-mcp`.
4. **Установка на Windows:** все варианты упёрлись в две стены:
   - `npm install -g test-runner-mcp` → блок permission-системой Claude Code
   - `npx -y test-runner-mcp` (без global install) → **`404 Not Found` в npm registry**
5. **Прямая проверка:** `npm view test-runner-mcp` →
   ```
   npm error code E404
   npm error 404 Not Found - GET https://registry.npmjs.org/test-runner-mcp
   ```
   Пакет с таким именем **в npm registry не существует**.
6. **Решение:** убрать из `.mcp.json` и `mcp.template.json`. Документация остаётся как референс.

## Проверенные кандидаты

| Пакет | Стек | Живой? | Pypi/npm | Вердикт |
|-------|------|--------|----------|---------|
| `jwilger/mcp-pytest-runner` | Python | ❌ GitHub 404 | — | Удалён |
| `test-runner-mcp` (npm имя) | Node.js | — | ❌ 404 | Не опубликован |
| `privsim/mcp-test-runner` | Node.js | ✅ GitHub | ❌ нет npm-пакета | Только из git, не стабильно |
| `kieranlal/mcp_pytest_service` | Python | ⚠️ 3 коммита | ❌ | Слишком экспериментально |
| `pytest-mcp` (PyPI) | Python | ✅ PyPI | ✅ | Это **тестирование MCP-серверов**, не runner pytest |

## Альтернатива: Bash MCP

Прямой запуск pytest через встроенный `Bash` MCP **работает** и закрывает 80% сценария. Минус — стандартный stdout-output вместо структурного JSON. Для агентских циклов (Tester / Debugger) этого хватает.

Типовые команды:

```powershell
# Полный gate перед коммитом
make gate                                    # ruff + mypy + pytest + coverage
make test                                    # только pytest с coverage

# Прицельный run
python -m pytest path/to/test_file.py -v
python -m pytest -k pattern -v
python -m pytest path::test_name -v          # по nodeid

# С env
$env:INSPECTOR_LOG_DIR = "logs/test"
python -m pytest -v
```

## Когда возвращаться

Возобновить интеграцию, если появится:

1. **Anthropic-official MCP test server** — самый надёжный вариант
2. **PyPI-опубликованный pytest-MCP** с поддержкой Windows
3. **Зрелый npm-пакет** с structured pytest output (не git-only)

Чек-лист возврата:
- [ ] Добавить блок в `.mcp.json` + `mcp.template.json`
- [ ] Переписать `README.md` + этот файл под актуальный пакет
- [ ] Прописать в промптах Tester / Debugger использование `mcp__<name>__run_tests`
- [ ] Smoke-проверка на одном модуле проекта
- [ ] Документация в `.claude/mcp/README.md` (вернуть в таблицу активных)

## Полезные ссылки на будущее

- GitHub: [privsim/mcp-test-runner](https://github.com/privsim/mcp-test-runner) — следить за npm-публикацией
- Анализ: [skywork pytest-mcp-server deep dive](https://skywork.ai/skypage/en/A-Deep-Dive-into-pytest-mcp-server:-Bridging-Pytest-with-AI-Agents/)
- Список MCP-серверов: [awesome-mcp.tools](https://awesome-mcp.tools/) — фильтр по pytest
