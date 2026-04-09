# process_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary)

## ADR-163: Dual Communication API (send_message vs send)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `ProcessModule` предоставляет два стиля IPC: `send_message(target, message)` → `bool` (наследие простого API) и `send(message)` → `Dict` с полями статуса (расширенный путь через `ProcessCommunication`). Потребители и тесты используют оба контракта.  
**Решение:** Сохранить оба. Не унифицировать в один метод — разные сигнатуры возврата отражают разный уровень детализации (успех/неуспех vs структурированный ответ).  
**Последствия:** Дублирование точек входа документируется; новый код может предпочитать `send`/`receive` при необходимости метаданных.

## ADR-164: ISharedResources Protocol для DI

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `ProcessModule` должен работать с очередями, реестром процессов и памятью без жёсткой зависимости от конкретного класса `SharedResourcesManager`.  
**Решение:** Конструктор принимает `Optional[ISharedResources]`; доступ к полям через protocol и `getattr` там, где контракт расширяемый.  
**Последствия:** Нет циклического импорта `process_module` → `shared_resources_module` на уровне типов ядра; моки в тестах упрощаются.

## ADR-165: Удаление backward-compat shim `state/process_state_registry.py`

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** В `process_module/state/` лежал тонкий реэкспорт `ProcessStateRegistry` из `shared_resources_module`. Grep не выявил внешних импортёров этого пути; каноничный реестр — в SRM.  
**Решение:** Удалить файл; `ProcessStateRegistry` импортировать из `shared_resources_module`. Сохранить `process_data.py` (используется, в т.ч. TYPE_CHECKING в других модулях).  
**Последствия:** Меньше дублирования путей импорта; при старых импортах из `process_module.state` — миграция на SRM.

## ADR-166: Декомпозиция `ProcessManagers.initialize()` на pipeline

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Монолитный `initialize()` (~200+ LOC) смешивал создание семи менеджеров, регистрацию в ObservableMixin, адаптеры и связь с `event_manager`.  
**Решение:** Вынести шаги в `_create_*_manager`, `_register_all_managers`, `_attach_all_adapters`, `_connect_event_manager`; публичный `initialize()` остаётся единой точкой входа. Lazy imports остаются внутри соответствующих методов.  
**Последствия:** Читаемость и изоляция изменений по одному менеджеру; поведение и порядок инициализации неизменны.

## ADR-166a: Реализация `_init_configuration` / `_init_queues` в ProcessLifecycle + делегаты на ProcessModule

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Логика инициализации конфигурации и очередей вызывается только из `ProcessLifecycle.initialize()`. Unit-тесты подменяют `process._init_configuration` / `process._init_queues` на `Mock`.  
**Решение:** Тело методов — в `ProcessLifecycle._init_configuration` / `_init_queues`; на `ProcessModule` — однострочные делегаты `self._lifecycle._init_*()`. `ProcessLifecycle.initialize()` вызывает `self.process._init_configuration()` и `self.process._init_queues()`, чтобы моки и хуки на экземпляре процесса продолжали работать.  
**Последствия:** Нет дублирования логики; точка расширения для тестов остаётся на `ProcessModule`.

## ADR-167: `importlib.import_module` для динамической загрузки воркеров

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `_create_workers_from_config` использовал `__import__(module_path, fromlist=[...])` для загрузки класса воркера по строке пути.  
**Решение:** Заменить на `importlib.import_module(module_path)` и `getattr` для класса — идиоматичный API, проще сопровождать.  
**Последствия:** Эквивалентная семантика для обычных модулей; поведение для edge-case имён пакетов предсказуемее для читателя кода.
