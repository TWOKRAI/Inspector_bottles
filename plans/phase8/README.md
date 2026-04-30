# Plan: Phase 8 -- Графовый редактор + порты в каталоге

**Дата:** 2026-04-23
**Статус:** DRAFT

## Обзор

Phase 8 расширяет систему обработки до полноценного визуального DAG-редактора. Модель `ProcessingNode` из Phase 5 переиспользуется как есть -- добавляются порты в каталог операций (`ProcessingOperationDef`), полноценная DAG-валидация в `GraphRunnableBuilder`, и графический UI на QGraphicsScene/QGraphicsView с undo/redo через ActionBus (Phase 7).

## Архитектурные решения

1. **Модель не меняется.** `ProcessingNode` уже содержит `position`, `inputs`, `NodeInput.output_port`. Расширяется только `ProcessingOperationDef` (порты) и `GraphRunnableBuilder` (DAG-валидация).
2. **Port -- новая схема.** `Port(name, data_type, optional)` -- описывает вход/выход операции в каталоге. Тип порта (`"image"`, `"mask"`, `"detections"`) используется для валидации совместимости связей.
3. **DAG execution.** `ChainRunnable.execute()` в Phase 5 линеен (один `current_frame`). Для DAG нужен `DagRunnable` с маршрутизацией данных по портам.
4. **View switch.** Табличная и графовая view работают с одной моделью `region.nodes`. Переключатель -- кнопка в UI, состояние в presenter.

## Граф зависимостей задач

```
Task 8.1 (Port schema + каталог)
    |
    v
Task 8.2 (DAG-валидация + DagRunnable)  <-- зависит от 8.1
    |
    v
Task 8.3 (GraphScene + NodeItem/PortItem/EdgeItem)  <-- зависит от 8.1
    |
    +--> Task 8.4 (Интеракции: drag, Del, контекстное меню)  <-- зависит от 8.3
    |
    +--> Task 8.5 (Catalog palette + drag-drop)  <-- зависит от 8.3
    |
    v
Task 8.6 (View switch: таблица <-> граф)  <-- зависит от 8.3, 8.4
    |
    v
Task 8.7 (Auto-layout Sugiyama)  <-- зависит от 8.3
    |
    v
Task 8.8 (Undo/Redo графовых операций через ActionBus)  <-- зависит от 8.4
    |
    v
Task 8.9 (Интеграция + smoke-тесты)  <-- зависит от всех
```

## Параллелизм

- **8.1** -- стартовая, без зависимостей
- **8.2** и **8.3** -- параллельно после 8.1 (backend и frontend)
- **8.4**, **8.5**, **8.7** -- параллельно после 8.3
- **8.6** -- после 8.3 + 8.4
- **8.8** -- после 8.4
- **8.9** -- финальная интеграция

## Оценка трудоёмкости

| Задача | Уровень | Оценка |
|--------|---------|--------|
| 8.1 Port schema + каталог | Middle+ | 0.5 дня |
| 8.2 DAG-валидация + DagRunnable | Senior+ | 2 дня |
| 8.3 GraphScene + Items | Senior+ | 3 дня |
| 8.4 Интеракции | Senior | 2 дня |
| 8.5 Catalog palette | Middle+ | 1 день |
| 8.6 View switch | Middle+ | 1 день |
| 8.7 Auto-layout | Senior | 1.5 дня |
| 8.8 Undo/Redo | Middle+ | 1 день |
| 8.9 Интеграция | Senior | 1.5 дня |
| **Итого** | | **~13.5 дней (~2.5-3 нед)** |

## Файлы задач

- [Task 8.1](task_8_1.md) -- Port schema + расширение каталога
- [Task 8.2](task_8_2.md) -- DAG-валидация + DagRunnable
- [Task 8.3](task_8_3.md) -- GraphScene + NodeItem/PortItem/EdgeItem
- [Task 8.4](task_8_4.md) -- Интеракции (drag, Del, контекстное меню)
- [Task 8.5](task_8_5.md) -- Catalog palette + drag-drop
- [Task 8.6](task_8_6.md) -- View switch таблица <-> граф
- [Task 8.7](task_8_7.md) -- Auto-layout (Sugiyama)
- [Task 8.8](task_8_8.md) -- Undo/Redo графовых операций
- [Task 8.9](task_8_9.md) -- Интеграция + smoke-тесты

## Риски и ограничения

1. **QGraphicsScene performance.** При >50 узлах могут быть тормоза. Mitigation: LOD (level of detail) в NodeItem, отложенная отрисовка.
2. **DAG execution.** Текущий `ChainRunnable` предполагает один `current_frame`. DAG с ветвлениями требует маршрутизации промежуточных данных по портам. Новый `DagRunnable` наследуется от общего интерфейса, но логика execute принципиально другая.
3. **Обратная совместимость.** Существующие операции (ColorDetection, BlobDetection) имеют 1 вход "in" / 1 выход "out". Миграция каталога через default-значения -- минимальный риск.
4. **Undo/Redo** графовых операций (connect/disconnect/move) должен быть атомарным -- один Action на одну операцию. Группировка move через coalescing (как слайдер).
