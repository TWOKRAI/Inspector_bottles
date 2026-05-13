### Task 8.9 -- Интеграция + smoke-тесты

**Уровень:** Senior (Opus, normal thinking)
**Исполнитель:** teamlead
**Цель:** Интеграция всех компонентов Phase 8, end-to-end smoke-тесты, финальная проверка обратной совместимости с Phase 5 цепочками.

**Контекст:**
Все компоненты Phase 8 (Port schema, DAG execution, GraphView, интеракции, catalog palette, view switch, auto-layout, undo/redo) разработаны в отдельных задачах. Эта задача собирает всё вместе, проверяет интеграцию и пишет smoke-тесты для критериев приёмки фазы из мета-плана.

**Файлы:**
- `multiprocess_prototype/tests/integration/test_phase8_smoke.py` -- **создать**
- `multiprocess_prototype/frontend/widgets/graph_editor/__init__.py` -- public API пакета
- Возможные правки в любых файлах Phase 8 по результатам интеграционного тестирования

**Шаги:**

1. **Проверить public API `graph_editor` пакета:**
   - `__init__.py` экспортирует: `GraphView`, `GraphScene`, `CatalogPalette`, `ViewSwitchWidget`
   - Все импорты работают из корня прототипа

2. **Smoke-тест 1: Graph view открывает регион:**
   - Загрузить существующий `region.nodes` из Phase 5 (линейная цепочка color_detection -> blob_detection)
   - `GraphScene.load_graph(nodes, catalog)` -> проверить: 2 NodeItem'а, 1 EdgeItem
   - Позиции назначены auto-layout (position=None -> auto)
   - Визуальная проверка: нет overlapping

3. **Smoke-тест 2: Ветвление (1->2) и merge (2->1):**
   - Создать граф программно: A -> {B, C} -> D
   - A: output "out" -> B input "in" и C input "in" (ветвление)
   - B: output "out" -> D input "in1", C: output "out" -> D input "in2" (merge)
   - `GraphRunnableBuilder.build()` -> `DagRunnable`
   - `DagRunnable.execute(frame)` -> ChainResult с корректным результатом

4. **Smoke-тест 3: View switch:**
   - Загрузить нелинейный граф
   - Переключить на табличный вид -> WARN-сообщение отображается
   - Переключить обратно на граф -> все узлы/связи на месте
   - `region.nodes` идентичен до и после switch

5. **Smoke-тест 4: Undo/Redo:**
   - Добавить узел через drop (ActionBus.execute)
   - Создать связь (ActionBus.execute)
   - Переместить узел (ActionBus.execute)
   - Ctrl+Z x3 -> состояние до добавления
   - Ctrl+Y x3 -> состояние после всех операций
   - Сравнить nodes snapshot

6. **Smoke-тест 5: Обратная совместимость Phase 5:**
   - Загрузить YAML конфиг из Phase 5 (без портов в каталоге, без position в нодах)
   - `load_catalog()` -> операции получают default порты
   - `GraphRunnableBuilder.build()` -> `ChainRunnable` (линейный граф)
   - `ChainRunnable.execute(frame)` -> результат идентичен Phase 5

7. **Проверить критерии приёмки Phase 8 из мета-плана:**
   - [ ] Graph view открывает регион -> показывает узлы/связи из Phase 5 без конверсии
   - [ ] Ветвление (1->2) и merge (2->1) -- backend исполняет через DAG scheduler
   - [ ] View switch таблица <-> граф -- модель `region.nodes` идентична
   - [ ] Все графовые операции undoable через ActionBus
   - [ ] Нет миграции SchemaBase -- модель ProcessingNode из Phase 5 переиспользуется

8. **Финальный checklist:**
   - `ruff check` + `ruff format` на всех файлах Phase 8
   - `python scripts/validate.py` -- проходит
   - `python scripts/run_framework_tests.py` -- проходит
   - Все unit-тесты Phase 8 проходят
   - Все integration-тесты Phase 8 проходят

**Критерии приёмки:**
- [ ] Все 5 smoke-тестов проходят
- [ ] Все критерии из мета-плана Phase 8 выполнены
- [ ] validate.py проходит
- [ ] Нет регрессий в Phase 5 тестах
- [ ] `ruff check` + `ruff format` проходят
- [ ] `__init__.py` экспортирует public API

**Вне scope:**
- Performance-тестирование (>50 нод)
- UI-тестирование с реальными камерами

**Edge cases:**
- Конфликт между auto-layout позициями и manually set позициями при mix
- Race condition: undo во время drag

**Зависимости:** Все Task 8.1 -- 8.8
