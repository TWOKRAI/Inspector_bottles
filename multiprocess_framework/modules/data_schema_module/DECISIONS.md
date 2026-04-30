# DECISIONS.md — `data_schema_module`

Локальные архитектурные решения модуля. Глобальные правила фреймворка — в [`../../DECISIONS.md`](../../DECISIONS.md).

---

## ADR-DS-001 (was ADR-120): Удаление `_compat.py`
- Дата: 2026-04-09
- Статус: принято
- Контекст: Файл реэкспортировал символы для «старого» API; grep по текущий каталог не показал внешних импортов из `_compat`. Все потребители используют `from data_schema_module import …`.
- Решение: Удалить `_compat.py`; публичный контракт остаётся в `__init__.py` и канонических пакетах.
- Причина: Меньше мёртвого кода и дублирования путей импорта.
- Отклонённые альтернативы: Оставить файл «на всякий случай» — отклонено.

---

## ADR-DS-002 (was ADR-121): Удаление shim-директорий и re-export файлов
- Дата: 2026-04-09
- Статус: принято
- Контекст: После рефакторинга v2.0 остались переходные обёртки: `fields/`, `utils/`, `registry/register_discovery.py`, `registry/registers_scanner.py`, `storage/file_storage.py`, тонкие re-export в `extensions/storage_manager.py` и `extensions/process_data_container.py`. Дублировали канонические пути (`core/`, `serialization/`, `container/`, `registry/discovery.py`, `storage/`).
- Решение: Удалить shims; внутренние импорты и тесты перевести на канонические модули. Функция `_class_name_to_snake` перенесена в `registry/discovery.py` (раньше только в `registers_scanner.py`). `FileStorage` в `storage/__init__.py` импортируется из `serialization/file_storage.py`.
- Причина: Однозначные пути, меньше файлов и расхождений с `core/`.
- Отклонённые альтернативы: Оставить shims бессрочно — отклонено.

---

## ADR-DS-003 (was ADR-122): Удаление `tests_backup/`
- Дата: 2026-04-09
- Статус: принято
- Контекст: Устаревшие тесты со старыми путями (`fields/register_base` и т.д.).
- Решение: Удалить каталог целиком; регрессии покрыты актуальными тестами в `tests/`.
- Причина: Шум и ложное ощущение покрытия.
- Отклонённые альтернативы: Починить backup-тесты — отклонено (дублирование).

---

## ADR-DS-004 (was ADR-123): `extensions/` — только явный импорт
- Дата: 2026-04-09
- Статус: принято
- Контекст: Расширения (versioning, factory, tools, metrics-shim к `core.metrics`, api-обёртки) не входят в top-level `data_schema_module.__init__`.
- Решение: Сохранить `extensions/` для опциональных компонентов; `StorageManager` и `ProcessDataContainer` импортировать из `data_schema_module.storage` (реализация в `storage/`), не через удалённые shim-файлы в `extensions/`.
- Причина: Зависимости от `process_module` и др. остаются изолированными; ядро без лишних side effects при `import data_schema_module`.
- Отклонённые альтернативы: Реэкспорт StorageManager снова в корень пакета — отклонено (нарушает слойность).
