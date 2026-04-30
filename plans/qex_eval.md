# qex eval — набор контрольных запросов для семантического поиска

Назначение: измерять качество семантического поиска **в цифрах** при любых
изменениях настроек (модель, фильтры, чанкинг, reranker).

Без этого файла любые улучшения = «кажется стало лучше». С ним = Recall@5, MRR.

## Как использовать

1. При любом изменении настроек qex (модель, `.ignore`, фильтры, reranker)
   прогнать весь набор.
2. Для каждого запроса вызвать `mcp__qex__search_code(query=..., limit=5)`.
3. Проверить, что в top-5 есть хотя бы один файл из `expect_files`.
4. Посчитать Recall@5 = (число запросов с попаданием) / (всего запросов).
5. Сравнить с предыдущим прогоном.

Цель: Recall@5 ≥ 0.90 на этом наборе.

## Структура записи

```yaml
- id: <уникальный идентификатор>
  query: <запрос на естественном языке или по ключевым словам>
  expect_files:
    - <относительный путь от корня репо>  # хотя бы один должен быть в top-5
  expect_symbols:                         # опционально — конкретные символы
    - <имя класса/функции/метода>
  notes: <заметка, если что-то важно>
```

---

## Набор запросов (starter, 10 штук — расширяй по ходу)

```yaml
# ===== Framework: router_module =====
- id: router_01
  query: класс роутера сообщений между процессами
  expect_files:
    - multiprocess_framework/modules/router_module/core/router_manager.py
  expect_symbols:
    - RouterManager

- id: router_02
  query: как RouterManager резолвит канал по имени
  expect_files:
    - multiprocess_framework/modules/router_module/core/router_manager.py
  expect_symbols:
    - _resolve_channels

# ===== Framework: process_manager_module =====
- id: process_01
  query: загрузка класса процесса по пути из строки
  expect_files:
    - multiprocess_framework/modules/process_manager_module/runner/process_runner.py
  expect_symbols:
    - _load_process_class

# ===== Framework: data_schema_module =====
- id: schema_01
  query: валидация словаря через Pydantic-модель
  expect_files:
    - multiprocess_framework/modules/data_schema_module/core/validators.py
  expect_symbols:
    - DataValidator
    - validate

# ===== Framework: frontend_module =====
- id: frontend_01
  query: протокол отправки сообщений в backend
  expect_files:
    - multiprocess_framework/modules/frontend_module/interfaces.py
  expect_symbols:
    - IRouterLike

# ===== Framework: message_module =====
- id: message_01
  query: правило dict at boundary между процессами
  expect_files:
    - multiprocess_framework/DECISIONS.md
  notes: проверяем, что архитектурные ADR попадают в поиск

# ===== hikvision_camera_module =====
- id: hikvision_01
  query: инициализация камеры hikvision
  expect_files:
    - hikvision_camera_module/core/capture.py

# ===== scripts =====
- id: scripts_01
  query: запуск тестов фреймворка
  expect_files:
    - scripts/run_framework_tests.py

- id: scripts_02
  query: валидация структуры фреймворка запрет sys.path insert
  expect_files:
    - scripts/validate.py

# ===== Services =====
- id: services_01
  query: обработка изображений crop операция
  expect_files:
    - Services/Operation_crop/
  notes: любой файл из папки засчитывается
```

## История прогонов

| Дата | Recall@5 | Изменения | Коммит |
|---|---|---|---|
| 2026-04-08 | — | baseline после whitelist-фильтра `.ignore` | TBD |

## Следующие шаги

- [ ] Расширить набор до 30 запросов (добавить v3, process_manager детали, config_module, logger_module)
- [ ] Написать скрипт `scripts/qex_eval.py`, который прогоняет все запросы и выводит Recall@5/MRR автоматически
- [ ] При падении метрик — расследовать, а не «подкрутить на глаз»
