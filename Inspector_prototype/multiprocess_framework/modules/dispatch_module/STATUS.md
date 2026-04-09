# dispatch_module — Статус рефакторинга

## Текущий этап: 9 / 9

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код | 9 | Strategy Pattern; сценарии вынесены в `core/scenarios.py` (`ScenarioManager`). `dispatcher.py` сжат, legacy API удалён |
| Тесты | 9 | Все зелёные; добавлены `test_scenarios.py` и проверка отклонения старых kwargs |
| Документация | 9 | README, `DECISIONS.md` (ADR-130…132), §6.3 в `ARCHITECTURE.md` |
| Связанность | 9 | Зависит только от `base_manager` (BaseManager + ObservableMixin). Никаких внешних зависимостей |
| Дублирование | 8 | `BaseDispatcher` — lightweight-класс с чётким назначением |
| Работоспособность | 10 | Все 4 стратегии работают, explicit `strategy: "chain"` в сообщении работает корректно |

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены
- [x] Этап 1: Модуль структурирован (Strategy Pattern, типы, builders)
- [x] Этап 2: BaseManager + ObservableMixin интегрирован
- [x] Этап 3: Все 4 стратегии реализованы и работают
- [x] Этап 4: Сценарии (CHAIN_MATCH) работают с передачей данных между этапами
- [x] Этап 5: ScenarioBuilder реализован
- [x] Этап 6: Legacy API удалён (ADR-131); `AdvancedDispatcher` удалён (ADR-132)
- [x] Этап 7: Unit-тесты расширены (`test_scenarios`, отказ от старых параметров `__init__`)
- [x] Этап 8: README и interfaces.py готовы, все известные проблемы закрыты
- [x] Этап 9: Split `ScenarioManager`, документация и метрики в `plans/refactoring/00_overview.md`

## Известные проблемы

- **configs/:** `DispatcherConfig` (SchemaBase)

## История изменений

| Дата | Что сделано | Этап |
|------|-------------|------|
| 2026-03-11 | Начальное состояние, STATUS.md создан | 0 |
| 2026-03-12 | Рефакторинг документации: удалены docs/ и лишние .md, новый README.md | 8 |
| 2026-03-12 | Bug fix: `_find_handler_in_strategy` для CHAIN_MATCH передавал объект стратегии вместо `self._scenarios` | 8 |
| 2026-03-12 | Bug fix: `ChainMatchStrategy.find_handler/get_all_handlers/get_handlers_by_tag` игнорировали `handlers_storage` | 8 |
| 2026-03-12 | Bug fix: `dispatch()` — добавлена явная ветка для `strategy: "chain"` | 8 |
| 2026-03-12 | Design fix: `BaseDispatcher` переведён из ABC в конкретный lightweight-класс | 8 |
| 2026-03-12 | Tests: добавлены `overwrite_handler`, explicit chain strategy, `stop_on_error` тесты | 8 |
| 2026-04-09 | `ScenarioManager` в `core/scenarios.py`, удалён legacy `__init__` и alias `AdvancedDispatcher`; ADR-130…132 | 9 |
