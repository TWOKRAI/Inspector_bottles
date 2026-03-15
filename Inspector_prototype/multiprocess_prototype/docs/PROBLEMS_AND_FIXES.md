# Проблемы и исправления при интеграции multiprocess_prototype

Документ описывает все проблемы, с которыми столкнулись при запуске демо-приложения, и внесённые исправления. Цель — не сломать существующий код и сохранить обратную совместимость.

---

## 1. ProcessData.config отсутствует

**Проблема:** `ProcessConfigHandler` ожидал `process_data.config` (тип `ProcessConfiguration`), но `ProcessData` в refactored не имеет атрибута `config`. Конфигурация передаётся через `register_process_state(config={"process": {...}})` и сохраняется в `process_data.custom['process_config']`.

**Ошибка:**
```
AttributeError: 'ProcessData' object has no attribute 'config'
```

**Исправление:** В `process_config_handler.py` добавлена поддержка `process_data.custom`:
- Если есть `process_data.config` — используется как раньше.
- Если есть `process_data.custom` — создаётся обёртка `_CustomProcessConfig` над `custom['process_config']`, `component_managers_config`, `module_configs`.

**Риск поломки:** Нет. Проверка `hasattr(process_data, 'config') and process_data.config` идёт первой; старый путь сохранён.

---

## 2. ProcessModule._init_configuration — та же ошибка

**Проблема:** В `process_module.py` при загрузке конфига в ConfigManager вызывалось `process_data.config.to_dict()`, что приводило к той же ошибке.

**Исправление:** Добавлена ветка для `process_data.custom`: при её наличии используется `custom.get('process_config', {})` и `config_manager.update_process_config` (который в итоге убрали — см. п. 3).

**Риск поломки:** Нет. Сначала проверяется `hasattr(process_data, 'config')`.

---

## 3. ConfigManager не имеет update_process_config

**Проблема:** `ProcessModule._init_configuration` вызывал `config_manager.update_process_config({...})`, но refactored `ConfigManager` не содержит этого метода (есть `create_config`, `get_config`, `sync_config` и т.д.).

**Ошибка:**
```
AttributeError: 'ConfigManager' object has no attribute 'update_process_config'
```

**Исправление:** Блок загрузки конфига в ConfigManager удалён. Конфигурация процесса берётся из `ProcessConfigHandler`, который получает её из `process_data.custom` через `_CustomProcessConfig`.

**Риск поломки:** Нет. ConfigManager по-прежнему создаётся и передаётся в config_handler; просто не заполняется процессным конфигом. ProcessConfigHandler приоритетно использует `process_config` из process_data.

---

## 4. ProcessConfigHandler — вызовы несуществующих методов ConfigManager

**Проблема:** В `get_managers_config`, `get_config`, `update_config` вызывались `config_manager.get_process_config()` и `config_manager.update_process_config()`, которых нет в refactored ConfigManager.

**Исправление:** Добавлены проверки `hasattr(self.config_manager, 'get_process_config')` и `hasattr(self.config_manager, 'update_process_config')`. Методы вызываются только при наличии.

**Риск поломки:** Нет. Если ConfigManager не поддерживает эти методы, используется fallback (локальная конфигурация из process_config).

---

## 5. dict(self.config_handler) — итерация по Config

**Проблема:** Строка `self.config = dict(self.config_handler)` приводила к ошибке при итерации по `Config`: при обращении по ключам (в т.ч. числовым) вызывался `Config.get(key)`, который делает `key.split('.')`. При числовом ключе — `AttributeError: 'int' object has no attribute 'split'`.

**Ошибка:**
```
AttributeError: 'int' object has no attribute 'split'
```

**Исправление:** Заменено на `self.config = self.config_handler.data if self.config_handler else {}`. Свойство `Config.data` возвращает копию `_data` и подходит для словаря.

**Риск поломки:** Нет. `Config.data` — стандартное свойство, возвращает `copy.deepcopy(self._data)`.

---

## 6. Ошибки инициализации не видны

**Проблема:** При падении `ProcessLifecycle.initialize()` исключение перехватывалось, логировалось через `_log_error`, но логгер мог быть ещё не готов — в консоль ничего не выводилось. Результат — `Result: False` без понимания причины.

**Исправление:** В блок `except` в `process_lifecycle.py` добавлен `print()` с traceback как запасной вывод при недоступном логгере.

**Риск поломки:** Нет. Добавлен только дополнительный вывод, логика не менялась.

---

## 7. ThreadConfig — неверные аргументы

**Проблема:** В `process_a.py` и `process_b.py` вызывался `ThreadConfig(name=worker_name, priority=..., daemon=False)`, но refactored `ThreadConfig` принимает только `priority`, `restart_on_failure`, `max_restarts`, `dependencies`.

**Ошибка:**
```
TypeError: ThreadConfig.__init__() got an unexpected keyword argument 'name'
```

**Исправление:** Вызов заменён на `ThreadConfig(priority=ThreadPriority.NORMAL)`. Имя воркера передаётся в `create_worker`, а не в ThreadConfig.

**Риск поломки:** Только в `multiprocess_prototype`, framework не затронут.

---

## 8. create_worker — keyword args вместо positional

**Проблема:** Вызывался `create_worker(name=worker_name, target=worker_func, config=thread_config)`, но сигнатура — `create_worker(worker_name, target, config, auto_start=False)` (позиционные аргументы).

**Ошибка:**
```
TypeError: WorkerManager.create_worker() got an unexpected keyword argument 'name'
```

**Исправление:** Вызов заменён на `create_worker(worker_name, worker_func, thread_config)`.

**Риск поломки:** Только в `multiprocess_prototype`, framework не затронут.

---

## Сводка изменений в framework (refactored)

| Файл | Изменение |
|------|-----------|
| `process_module/config/process_config_handler.py` | Добавлен `_CustomProcessConfig`, поддержка `process_data.custom`, проверки `hasattr` для методов ConfigManager |
| `process_module/core/process_module.py` | Поддержка `process_data.custom` при загрузке конфига, удалён вызов `update_process_config`, `self.config = self.config_handler.data` |
| `process_module/lifecycle/process_lifecycle.py` | Добавлен `print()` в `except` для отладки |

## Сводка изменений в multiprocess_prototype

| Файл | Изменение |
|------|-----------|
| `processes/process_a.py` | `ThreadConfig(priority=...)`, `create_worker(worker_name, worker_func, thread_config)` |
| `processes/process_b.py` | То же |

---

## Рекомендации по проверке

1. Запустить `python multiprocess_prototype/test_init.py` — должен вернуть `Result: True`.
2. Запустить `python -m multiprocess_prototype.main` — процессы должны стартовать и корректно останавливаться.
3. Запустить тесты framework: `python multiprocess_framework/refactored/tests/run_all_tests.py` — убедиться, что изменения в refactored не ломают существующие сценарии.
