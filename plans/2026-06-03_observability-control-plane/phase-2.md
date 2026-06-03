# Phase 2: Реестр sink-фабрик

**Цель фазы:** позволить добавлять новый тип sink (канала) без правки кода менеджеров —
поверх существующей фабрики `create_channel`. Это превращает «новый sink одной строкой в
dict `channel_types`» в публичный расширяемый реестр, на который будут опираться будущие
SQLChannel / SocketChannel (Phase 4).

---

### Task 2.1 — `register_sink_factory` / `create_sink` поверх `create_channel`

**Level:** Senior (Opus, normal)
**Assignee:** teamlead
**Goal:** Превратить захардкоженный `channel_types` (logger_module/channels/log_channel.py:230) в мутируемый реестр sink-фабрик с публичным API `register_sink_factory(type, cls)`, сохранив обратную совместимость `create_channel`.

**Context:** Reuse-first: фабрика `create_channel(channel_name, config)` уже централизует
создание каналов по `config.type` через локальный dict `channel_types`. Дописываем
**минимальную** дельту: вынести dict в module-level реестр + публичную функцию регистрации.
Существующие типы (`file`, `console`, `http`, `frame_trace`) остаются. StatsManager строит
свои каналы напрямую (LogStatsChannel/FileStatsChannel) — его в Итерации 1 НЕ трогаем
(его типы — задел на следующую итерацию). Реестр живёт в logger_module, т.к. там фабрика;
если потребуется общий для всех CRM — это решение Phase 4 (не сейчас).

**Files:**
- `multiprocess_framework/modules/logger_module/channels/log_channel.py` — вынести `channel_types` в module-level `_SINK_FACTORIES: Dict[str, type]`; добавить `register_sink_factory(sink_type: str, factory: type) -> None` и `get_registered_sink_types() -> list[str]`; `create_channel` читает из реестра. Поведение при неизвестном типе не меняется (`ValueError`).
- `multiprocess_framework/modules/logger_module/__init__.py` / `interfaces.py` — экспортировать `register_sink_factory` в публичный API модуля (сверься, где модуль объявляет публичные имена).
- `multiprocess_framework/modules/logger_module/tests/test_log_channels.py` (сверься через Glob) — unit: регистрируем фиктивный sink-класс, `create_channel` его создаёт; дублирующая регистрация переопределяет; неизвестный тип → `ValueError`.

**Steps:**
1. Завести `_SINK_FACTORIES` со стартовым содержимым текущего `channel_types`.
2. `register_sink_factory(sink_type, factory)`: валидация (factory — класс с `write`/наследник `LogChannel` или `IChannel`); записать в реестр.
3. `create_channel` берёт класс из `_SINK_FACTORIES.get(cfg.type)`.
4. Экспорт в `__init__.py` модуля.
5. Тест на регистрацию фиктивного `MemorySink(LogChannel)` и создание через `create_channel`.

**Acceptance criteria:**
- [ ] `python -m pytest multiprocess_framework/modules/logger_module/tests/ -q` — green.
- [ ] `from multiprocess_framework.modules.logger_module import register_sink_factory` работает.
- [ ] Регистрация нового типа + `create_channel(name, cfg(type=new))` создаёт инстанс без правки `create_channel`.
- [ ] Существующие типы (`file/console/http/frame_trace`) по-прежнему создаются.
- [ ] `python scripts/validate.py` — без новых ошибок.

**Out of scope:** общий cross-module реестр для Stats/Router; реализация SQL/Socket sink; авто-discovery sink-классов.
**Edge cases:** регистрация типа-дубля (последняя побеждает — задокументировать); None/невалидный factory → `TypeError`.
**Dependencies:** Task 1.1 (reconfigure уже использует `create_channel` через `_setup_channels`).
**Module contract:** public-api-change (новый публичный экспорт `register_sink_factory`).
