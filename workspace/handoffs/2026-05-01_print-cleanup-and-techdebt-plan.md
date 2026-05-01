---
date: 2026-05-01
topic: print() cleanup done — plan remaining tech-debt (ShmRegistry race, import logging, loguru, coverage)
machine: macOS
branch: main
---

## Session goal

Профессиональная оценка фреймворка выявила итоговый балл 7.2/10 и топ-5 проблем.
Задача сессии — устранить 🔴1 (print()) и спланировать остальные.

## Done

- **Убраны все 33 production `print()` из `multiprocess_framework/` и `multiprocess_prototype/`** (23 файла)
- Классы с ObservableMixin (base_manager, observable_mixin, process_module, command_manager) → `_log_*()`
- Redundant prints в process_lifecycle удалены (дублировали `_log_error` выше)
- Utility-классы без ObservableMixin (dispatch strategies, theme managers, system_launcher, spawner, shm, etc.) → `import logging; _logger = logging.getLogger(__name__)`
- Обновлены 2 теста: `capsys` → `caplog` (stdlib logging не пишет в stdout)
- Итог: `python scripts/run_framework_tests.py` — 2460 passed, 1 failed (pre-existing баг `test_cmd_process_list_returns_dict` — AttributeError `_process_monitor`)

## What did NOT work

- **Прямое использование LoggerManager в utility-классах** (dispatch strategies, ThemeManager и др.) невозможно сейчас: они создаются в bootstrap до инициализации LoggerManager. Нужен отдельный рефакторинг (console channel + DI через конструктор).
- **Тесты на вывод в stdout** (`capsys`) сломались после перехода на `logging` — поведение изменилось (logging по умолчанию не пишет в stdout, а в caplog). Два теста обновлены.

## Key decisions made

- **stdlib `logging` как промежуточный шаг** для utility-классов без ObservableMixin. Обоснование: они не участвуют в DI-цепочке процессов; передача LoggerManager потребует изменения API всех сигнатур. Это следующий рефакторинг, не этот.
- **Docstring-примеры и demo-скрипты** оставлены с `print()` — правильно, не production-код.
- **CLI tools** (`multiprocess_framework/tools/module_validator.py`, `validate_all_modules.py`) оставлены с `print()` — правильно, терминальный вывод.

## Remaining tech-debt (из оценки 7.2/10)

### 🔴 Приоритет 2 — ShmRegistry race condition (Сложность: Малая)
**Файл:** `multiprocess_framework/modules/shared_resources_module/memory/shm_registry.py` (или аналогичный)
**Проблема:** `ShmRegistry._write()` пишет JSON без файловой блокировки → race condition при concurrent `register()` из нескольких процессов.
```python
# Два процесса → потеря записей:
self._path.write_text(json.dumps(names), ...)  # /dev/shm/ на Linux
```
**Фикс:** `fcntl.flock(f, fcntl.LOCK_EX)` на Unix / `msvcrt.locking` на Windows. Или использовать `filelock` (уже в deps?).
**Важно:** `ProcessStateRegistry` тоже хранит `Dict[str, ProcessData]` без Lock() — задокументировать как инвариант "только из одного треда" или добавить Lock.

### 🟡 Приоритет 3 — Убрать оставшиеся `import logging` (Сложность: Малая)
После этой сессии добавилось ещё ~14 файлов с `import logging`. Общий план:
1. Добавить **console channel** в `LoggerManager` (target = stdout, без файла)
2. Передавать `logger_manager` через конструктор в utility-классы (BaseStrategy, ThemeManager, SystemLauncher, Adapters и др.)
3. Убрать все `import logging; _logger = ...`

**Console channel** — минимальный вариант:
```python
# logger_module/channels/console_channel.py
class ConsoleChannel(LogChannel):
    def write(self, record: LogRecord) -> None:
        print(f"[{record.level}] {record.message}", flush=True)
```
Тогда `_fallback_log` в LoggerManager использует свой собственный console channel.

### 🟡 Приоритет 4 — loguru (Сложность: Малая)
**Файл:** `pyproject.toml`
**Проблема:** `loguru` в dependencies, нигде не используется.
**Фикс:** либо удалить из `pyproject.toml`, либо заменить stdlib logging на loguru везде (более богатый API, цветной вывод, лучший traceback). Решить до следующего рефакторинга логирования.

### 🟢 Приоритет 5 — Coverage measurement (Сложность: Малая)
**Фикс:**
```bash
pip install pytest-cov
pytest --cov=multiprocess_framework --cov-report=html --cov-fail-under=70
```
Добавить в `scripts/run_framework_tests.py` или отдельный `scripts/check_coverage.py`.
**Цель:** 70% как порог (сейчас нет метрики, реальный % неизвестен).

### 🔵 Следующий большой шаг (не в топ-5, но важно)
**LoggerManager console channel + устранение всех `import logging`:**
- Добавить `ConsoleChannel` в `logger_module`
- Сделать `BaseStrategy.__init__(dispatcher_name, logger=None)` — принимать логгер
- `ChannelRoutingManager` при создании стратегий передаёт `self._log_warning`
- Убрать `import logging` из ~14 новых файлов

## Next step

Открыть новый чат и выполнить **🔴 Приоритет 2**: добавить файловую блокировку в `ShmRegistry._write()` — найти файл, добавить `fcntl.flock` (Unix) с fallback на threading.Lock для in-process защиты, написать тест на concurrent write.

## Files changed

```
multiprocess_framework/modules/base_manager/adapters/base_adapter.py
multiprocess_framework/modules/base_manager/core/base_manager.py
multiprocess_framework/modules/base_manager/mixins/observable_mixin.py
multiprocess_framework/modules/dispatch_module/strategies/chain_match.py
multiprocess_framework/modules/dispatch_module/strategies/exact_match.py
multiprocess_framework/modules/dispatch_module/strategies/fallback_match.py
multiprocess_framework/modules/dispatch_module/strategies/pattern_match.py
multiprocess_framework/modules/frontend_module/managers/theme_manager.py
multiprocess_framework/modules/frontend_module/managers/theme_presets_manager.py
multiprocess_framework/modules/frontend_module/managers/yaml_persistence_store.py
multiprocess_framework/modules/logger_module/core/logger_manager.py
multiprocess_framework/modules/process_manager_module/launcher/spawner.py
multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py
multiprocess_framework/modules/process_manager_module/runner/class_loader.py
multiprocess_framework/modules/process_manager_module/tests/test_process_runner.py
multiprocess_framework/modules/process_manager_module/tests/test_system_launcher.py
multiprocess_framework/modules/process_module/communication/process_communication.py
multiprocess_framework/modules/process_module/configs/process_config_handler.py
multiprocess_framework/modules/process_module/core/process_module.py
multiprocess_framework/modules/process_module/lifecycle/process_lifecycle.py
multiprocess_framework/modules/shared_resources_module/memory/platform/shm.py
multiprocess_prototype/frontend/managers/theme_presets_manager.py
multiprocess_prototype/main.py
```
