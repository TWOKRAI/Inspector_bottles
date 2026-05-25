# service_module -- Статус компонентов

**Статус:** IN_PROGRESS
**Фаза:** Phase 3 -- ServiceRegistry + первые сервисы
**Дата создания:** 2026-05-25

Модуль реестра и жизненного цикла long-running сервисов (камеры, БД, auth). ServiceRegistry хранит классы сервисов (не экземпляры), управляет lifecycle через `ServiceLifecycle` enum, обнаруживает сервисы через scanner. В отличие от PluginRegistry, сервисы не поддерживают hot-reload и имеют расширенный lifecycle (UNREGISTERED/READY/RUNNING/STOPPED/ERROR).

---

## Таблица компонентов

| Компонент | Файл | Статус | Описание |
|-----------|------|--------|----------|
| ServiceLifecycle | interfaces.py | Готов | Enum состояний: UNREGISTERED/READY/RUNNING/STOPPED/ERROR |
| IService | interfaces.py | Готов | Protocol (runtime_checkable): name, start, stop, get_status |
| ServiceEntry | registry.py | Готов | dataclass-запись реестра: name, cls, lifecycle, meta |
| ServiceRegistry | registry.py | Готов | Singleton-реестр с декоратором @register_service |
| register_service | registry.py | Готов | Декоратор регистрации класса в singleton при импорте |
| DiscoveryResult | scanner.py | Готов | dataclass: loaded, failed, total |
| discover | scanner.py | Готов | Рекурсивный поиск service.py через importlib |
| ServiceStateAdapter | service_state_adapter.py | Готов (Task 3.5, c3b6c89) | Двусторонняя sync Registry ↔ state.services.* |

**Тестов:** 53 (26 test_registry.py + 15 test_scanner.py + 12 test_service_state_adapter.py)

---

## Статус интеграции

| Компонент | Интеграция | Статус |
|-----------|------------|--------|
| **interfaces.py** | IService (Protocol) | Готов |
| | ServiceLifecycle (StrEnum) | Готов |
| **registry.py** | ServiceRegistry singleton + @register_service | Готов |
| **scanner.py** | discover(*dirs) → DiscoveryResult | Готов |
| **Services/webcam_camera/service.py** | @register_service добавлен | Готов |
| **Services/sql/service.py** | @register_service | Готов |
| **Services/hikvision_camera/service.py** | @register_service | Готов |
| **Services/auth/service.py** | @register_service | Готов |
| **ServiceStateAdapter** | sync Registry ↔ state.services.* | Готов (Task 3.5, c3b6c89) |

---

## TODO

### Task 3.7 -- Action-кнопки start/stop/restart + биндинг статуса из state

Подключить кнопки к реальным вызовам `ServiceRegistry.get(name).cls().start()/stop()`, отображать статус из `state.services.<name>.status`.

### Task 3.8 -- ADR-129 + scripts/sync (глобальный журнал DECISIONS.md)

Добавить ADR-129 в `multiprocess_framework/DECISIONS.md`, запустить `python -m scripts.sync`.

---

## Известные ограничения

- `IService` Protocol не проверяет сигнатуры методов при `isinstance()` — только наличие атрибутов (ограничение Python runtime_checkable).
- `ServiceRegistry` не хранит экземпляры сервисов — инстанцирование при вызове `start()` является ответственностью application-слоя (Task 3.7).
- `clear()` предназначен только для изоляции тестов; в production вызывать не следует.

---

## История выпусков

| Дата | Событие | Статус |
|------|---------|--------|
| 2026-05-25 | Task 3.1: interfaces.py — IService Protocol + ServiceLifecycle enum + STATUS.md | Готово |
| 2026-05-25 | Task 3.2: registry.py — ServiceRegistry singleton, ServiceEntry, @register_service, 26 тестов | Готово |
| 2026-05-25 | Task 3.3: scanner.py — discover + DiscoveryResult, 15 тестов, integration smoke 4 сервиса | Готово |
| 2026-05-25 | Task 3.4: README.md + DECISIONS.md (ADR-SM-001/002/003) + STATUS.md → IN_PROGRESS | Готово |
| 2026-05-25 | Task 3.5: ServiceStateAdapter — двусторонняя sync Registry ↔ state.services.*, 12 тестов (c3b6c89) | Готово |
| 2026-05-25 | Task 3.6: ServicesTab → ServiceRegistry, ServicePathsSubtabWidget, AppContext.service_registry(), bootstrap в app.py | Готово |
