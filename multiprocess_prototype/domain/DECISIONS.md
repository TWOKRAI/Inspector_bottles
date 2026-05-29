# multiprocess_prototype/domain — Архитектурные решения

## DOM-001: display = binding (привязка), не wire

**Дата:** 2026-05-29
**Статус:** Принято
**Refs:** plans/2026-05-27_cross-tab-architecture/phase-g.md (Task G.4.2b)

### Контекст

В Pipeline editor выход процесса можно отправить на дисплей (SHM-канал
`ui_process`). Исторически in-memory `PipelineModel` хранил это как **wire**
`{source: <выход>, target: "display.<id>.frame"}` + отдельный display-«узел».
Но durable-слои уже были binding-центричны:

- domain `DisplayInstance(node_id=<source endpoint>, display_id=<канал>)` —
  привязка выхода к каналу, без понятия «wire к дисплею»;
- рецепт на диске хранит `display_bindings: [{node_id: <выход>, display_id}]`;
- роутер адресует кадр по `display_id` (routing-значимо → принадлежит domain).

Wire-to-display жил **только** в in-memory `PipelineModel` — это был источник
рассинхрона между editor-state и domain/диском. Domain-команда `ConnectWire`
физически не может выразить связь с дисплеем: `_extract_process_from_node`
для `"display.<id>.frame"` даёт процесс `"display"`, которого нет в топологии
→ `DomainError`. Альтернатива «научить domain wire-формату дисплея» (вариант B)
размывала бы инвариант «wire = process→process» и дублировала бы `display_id`
в двух местах.

### Решение

Единица display-связи = пара **(source_output, display_id)** = один
`DisplayInstance`. Никаких display-wire'ов и display-«узлов» в editor-модели.

- **Соединение** output→дисплей = `dispatch(BindDisplay(node_id=<source>, display_id))`.
- **Удаление** = `dispatch(UnbindDisplay(node_id, display_id))`.
- **Identity по паре:** `UnbindDisplay` несёт и `node_id`, и `display_id`
  (и событие `DisplayUnbound` — тоже). Один выход может быть привязан к N каналам
  (fan-out), один канал — к N выходам (fan-in); отвязка адресует ровно одну пару.
- **No-dup:** повторная привязка той же пары → `DomainError` (зеркало запрета
  цикла в `ConnectWire`).
- **Рендеринг:** на scene — один **бокс на `display_id`** (канал), binding-ребро
  source-процесс → бокс на каждый `DisplayInstance`. Боксы строятся из
  `topology["displays"]` (`_topology_to_graph` → `GraphScene.add_display_node` /
  `load_from_data(display_nodes=...)`). Формат диска (`display_bindings`) не
  меняется — миграция рецептов не нужна.

### Альтернативы

- **Вариант B (wire-to-display в domain):** учить `ConnectWire`/инварианты
  спец-формату `"display.*"`. Отвергнут: размывает инвариант wire = process→process,
  дублирует `display_id`, оставляет две модели одного факта.
- **Ключ `UnbindDisplay` только по `node_id`:** ломает fan-out (один выход → N
  дисплеев): отвязка одного канала снесла бы все. Поэтому ключ — пара.
- **`display_id` бокса ≠ node_id бокса:** на scene id бокса = `display_id` (канал),
  это позволяет fan-in (N источников → 1 бокс) и держит `add_edge` тривиальным.

### Последствия

- Editor-state, domain и диск используют **одно** представление (binding) —
  рассинхрон wire-to-display устранён, desync-баг display-ветки закрыт.
- `PipelineModel` упрощён: убраны `remove_display`, display-ветка `add_wire`,
  display-проверки `validate()` переведены на binding-семантику (источник должен
  существовать; orphan-display более не применим).
- `io.py` конвертер схлопнут: `displays` ↔ `display_bindings` напрямую, без
  wire⇄binding-конвертации.
- `DisplayNodeItem` frame-порт получил endpoint `display.<node_id>.frame` —
  интерактивное протягивание провода распознаётся `presenter.add_wire` как
  display-target.
- **Breaking (внутренний):** `UnbindDisplay`/`DisplayUnbound` теперь требуют
  `display_id`. Все вызовы обновлены в этом же изменении.
