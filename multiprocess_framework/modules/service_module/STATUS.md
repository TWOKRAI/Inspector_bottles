# service_module -- Статус компонентов

**Статус:** DRAFT
**Фаза:** Phase 3 -- ServiceRegistry + первые сервисы
**Дата создания:** 2026-05-25

Модуль реестра и жизненного цикла long-running сервисов (камеры, БД, auth). ServiceRegistry хранит классы сервисов (не экземпляры), управляет lifecycle через `ServiceLifecycle` enum, обнаруживает сервисы через scanner. В отличие от PluginRegistry, сервисы не поддерживают hot-reload и имеют расширенный lifecycle (UNREGISTERED/READY/RUNNING/STOPPED/ERROR).

---

## Таблица компонентов

| Компонент | Файл | Статус | Описание |
|-----------|------|--------|----------|
| ServiceLifecycle | interfaces.py | Готов | Enum состояний: UNREGISTERED/READY/RUNNING/STOPPED/ERROR |
| IService | interfaces.py | Готов | Protocol (runtime_checkable): name, start, stop, get_status |
| ServiceRegistry | registry.py | Запланирован (Task 3.2) | Singleton-реестр с декоратором @register_service |
| ServiceScanner | scanner.py | Запланирован (Task 3.3) | discover(*dirs) для автоматического поиска service.py |

**Тестов:** 0 (smoke-проверка isinstance пройдена; полные тесты -- Task 3.2)

---

## Статус интеграции

| Компонент | Интеграция | Статус |
|-----------|------------|--------|
| **interfaces.py** | IService (Protocol) | Готов |
| | ServiceLifecycle (StrEnum) | Готов |
| **ServiceRegistry** | singleton + @register_service | Запланирован (Task 3.2) |
| **scanner** | discover(*dirs) | Запланирован (Task 3.3) |
| **ServiceStateAdapter** | sync Registry <-> state.services.* | Запланирован (Task 3.5) |

---

## TODO

### Task 3.2 -- ServiceRegistry (singleton + @register_service + list/get/filter)

Singleton-реестр сервисов с декоратором, методами list/get/filter, unit-тестами (>=15).

### Task 3.3 -- ServiceScanner (discover) + регистрация существующих сервисов

Автоматический поиск service.py, добавление @register_service к существующим Services/.

### Task 3.4 -- README.md + DECISIONS.md

Полная документация модуля.

### Task 3.5 -- ServiceStateAdapter

Двусторонняя синхронизация ServiceRegistry <-> state.services.*.

---

## Известные ограничения

- Модуль пока содержит только контракт (interfaces.py), реализация Registry/Scanner -- следующие задачи.
- `IService` Protocol не проверяет сигнатуры методов при `isinstance()` -- только наличие атрибутов (ограничение Python runtime_checkable).

---

## История выпусков

| Дата | Событие | Статус |
|------|---------|--------|
| 2026-05-25 | Task 3.1: IService Protocol + ServiceLifecycle enum + STATUS.md | Готово |
