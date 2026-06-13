# multiprocess_prototype/domain — Архитектурные решения

## DOM-002: мульти-дисплей в главной области — поле `enabled` + маршрутизация по `sender`

**Дата:** 2026-06-13
**Статус:** принято
**Refs:** plans/dataset-circle-capture.md, ветка feat/dataset-circle-capture

### Контекст

Требование: показывать НЕСКОЛЬКО дисплеев одновременно в главной области GUI
(`ImagePanelWidget`), с toggle вкл/выкл и упорядочиванием по позиции. До этого
панель жёстко показывала единственный слот «main» (хардкод в `app.py`).

### Решение

1. **Поле `enabled: bool = True`** добавлено в `DisplayDefinition` (entity) и
   `DisplaySpec` (protocol). Default `True` → бэк-совместимость: рецепты без
   `enabled` показывают дисплей. Round-trip через `definition_to_spec` /
   `spec_to_definition_dict` и YAML рецепта.

2. **Транспорт мульти-дисплея — классификация по `sender`, НЕ per-display
   SHM-каналы.** Кадры всех дисплеев уже приходят в GUI через единый
   `data_receiver` → `DataReceiverBridge` (оба процесса draw/maskview имеют
   `chain_targets: [gui]`). Различитель — поле `sender` (имя процесса-отправителя),
   присутствует в КАЖДОМ IPC-сообщении. Привязка `blueprint.displays`
   (node_id→display_id; node_id = `process.plugin.port`) даёт карту
   `process_name → display_id`. `_on_frame_received` кладёт кадр в слот по sender,
   fallback на «main».

3. **Раскладка — в ряд, порядок по `position.x`.** `ImagePanelWidget.set_displays`
   фильтрует enabled, сортирует по `(x, y)`, пересобирает слоты. Заложено под
   свободные позиции x/y в будущем (сейчас position влияет только на порядок).

4. **Реактивность:** новое событие `DisplaysChanged` (domain) эмитится presenter'ом
   вкладки Displays при create/delete/toggle; главная панель пересобирает слоты.
   Плюс пересборка на `RecipeActivated`.

### Отвергнутые альтернативы

- **Per-display SHM-каналы `display.<id>` (рекомендация в задаче, путь PreviewWindow):**
  отвергнут. PreviewWindow подписывается на `display.<id>` через
  `register_broadcast_route`, но НИКТО не публикует в эти каналы внутри
  GUI-процесса — это заготовка Phase 4 (окно показывает «Ожидание кадров...»).
  Поднимать второй транспорт ради главной панели — дублирование; реальные кадры
  уже доступны через `data_receiver` с надёжным различителем `sender`.
- **Идентификатор дисплея через `frame_trace._from`:** отвергнут — поле живёт
  только при `INSPECTOR_FRAME_TRACE=1`, ненадёжно. `sender` есть всегда.
- **id дисплея вводит пользователь:** отвергнут по требованию владельца — id
  генерируется автоматически (`display_<N>`), поле read-only; name-default
  `display_<N>` при пустом вводе.

### Последствия

- Бэк-совместимо: рецепты с одним дисплеем / без `enabled` / без привязок →
  единственный слот «main» (старое поведение через fallback).
- **Breaking (внутренний):** `DisplaysPresenter.on_create` больше не берёт id из
  формы — тесты обновлены. `ProjectEvent` union: 15 → 16 (+`DisplaysChanged`).
- `DisplayCatalogFromRecipe.update(spec)` добавлен — обновление определения
  in-place БЕЗ потери привязок `blueprint.displays` (важно для toggle enabled;
  unregister+register снёс бы привязки).

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
