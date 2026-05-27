# Security guidance for Inspector_bottles

Контекст для model-backed ревью плагина `security-guidance`. Описывает domain-specific угрозы и осознанные исключения, чтобы reviewer не флажил архитектурные решения как уязвимости.

## Архитектурный контекст

Это **multiprocess framework** (Python 3.12) для desktop-приложений компьютерного зрения. Не веб-сервис. Не принимает внешние HTTP-запросы. Не обрабатывает пользовательский ввод как код.

Слои импортов (enforced via `.sentrux/rules.toml`):

```
multiprocess_framework  →  Services  →  Plugins  →  multiprocess_prototype
```

Обратные импорты запрещены.

## Что НЕ является уязвимостью в этом проекте

Reviewer не должен флажить следующее как security issue:

- **`pickle` через `MessageAdapter`, `shared_resources_module`, `RouterManager`.** Это IPC между нашими собственными процессами через `multiprocessing.Queue` и `SharedMemory`. Данные никогда не приходят из недоверенного источника. Pickle здесь — by design (см. CLAUDE.md rule 1: Dict at Boundary, ADR в `multiprocess_framework/DECISIONS.md`).
- **`subprocess` / `multiprocessing.Process` для запуска воркеров.** Это `SystemLauncher` → `ProcessManagerProcess` → `ProcessModule`. Параметры берутся из конфига (`config_module`), не из пользовательского ввода.
- **`os.system` / `shell=True` в тестовых скриптах под `tests/` и `scripts/`.** Это локальные dev-инструменты, не production-код.
- **`eval` в plugin-конфигах формул** (если встретится в `Plugins/*/formulas/` или подобном). Это namespace-ограниченный domain-specific eval, не произвольное выполнение.

## На что обратить внимание (true positives)

Reviewer ДОЛЖЕН флажить:

- **Прямой доступ к Shared Memory из плагина** (`SharedMemory(...)`, `MemoryManager`, чтение по имени блока). Плагины обязаны идти через `PluginContext` middleware (ADR-120). Per-edit pattern `shm_read_in_plugin` уже это ловит — повторно подтверждай в model review.
- **Передача `SchemaBase` / `BaseModel` (Pydantic v2) через `send_message` между процессами.** Между процессами — только `dict` через `to_dict()` / `from_dict()`. Live-объекты Pydantic не pickle-safe и нарушают «Dict at Boundary».
- **`FieldRouting` без IPC-канала.** Регистр с роутингом, но без `channel=` приведёт к зависанию GUI (см. memory feedback_register_routing_hang).
- **Глобальный `taskkill /IM python` / `pkill python` / `killall python`.** В CI/IDE-окружении убивает другие легитимные процессы (см. feedback_no_global_taskkill).
- **Hardcoded credentials** где угодно вне `private/` или `.env*`. Секреты → переменные окружения (CLAUDE.md base rule 4).
- **Path traversal / unsafe path joins** при работе с `MULTIPROCESS_LOG_DIR`, `INSPECTOR_LOG_DIR`, `private/` — особенно если path формируется из конфига.
- **Прямой `INSERT`/`UPDATE` со string-форматированием** в `Services/sql/` — только параметризованные запросы.
- **`yaml.load()` без `SafeLoader`** в любом коде, читающем конфиги (`config_module`, blueprint loader). Должен быть `yaml.safe_load()`.
- **Reverse imports** (framework → Services/Plugins/prototype, Services → Plugins/prototype, Plugins → prototype). Per-edit patterns это ловят на регулярках — model review подтверждает на семантическом уровне.

## Web/HTTP-специфика — НЕ применима

Этот проект не делает следующего, поэтому соответствующие классы уязвимостей не релевантны:

- ❌ HTTP-сервер, эндпоинты, маршрутизация → SSRF, CSRF, open redirect — N/A
- ❌ Веб-формы, рендер HTML → XSS, DOM injection — N/A (PySide6 — нативный desktop GUI, не WebView)
- ❌ JWT, сессии, cookies — N/A
- ❌ CORS, CSP — N/A

Если такие проверки появятся в findings — игнорировать или помечать как «not applicable».

## Что вообще стоит проверять глубже

- **PySide6/Qt thread-safety.** GUI-операции — только из main thread; cross-thread сигналы через `Qt.QueuedConnection`. См. memory feedback_widget_qt_patterns.
- **PyTorch/ONNX model loading.** При `torch.load()` использовать `weights_only=True` (PyTorch 2.6+ default), не загружать модели из недоверенных источников.
- **Hikvision SDK / camera URIs.** Учётки от камер — только из конфига/env, не hardcoded.
- **SQL миграции (Services/sql).** Параметризация, проверка прав, бэкап до миграции.

## Ссылки

- `CLAUDE.md` (корень и `Inspector_bottles/CLAUDE.md`) — base rules, layer rules, commit format
- `.sentrux/rules.toml` — структурные инварианты (boundaries)
- `multiprocess_framework/DECISIONS.md` — индекс ADR
- ADR-120 — Plugin isolation, PluginContext API
- `docs/claude/FRAMEWORK_RULES_EXTRACT.md` — конспект правил
