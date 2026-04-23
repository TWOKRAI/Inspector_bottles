### Task 8.1 -- Port schema + расширение каталога

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Добавить модель `Port` и расширить `ProcessingOperationDef` полями `input_ports` / `output_ports` с типами для валидации совместимости. Мигрировать существующие операции на default-порты.

**Контекст:**
Каталог операций (`ProcessingOperationDef`) сейчас не описывает входы/выходы операций. Для графового редактора (Phase 8) нужно знать, какие порты есть у каждой операции, чтобы валидировать связи и отрисовывать порты на узлах. Существующие операции (color_detection, blob_detection) имеют один вход ("in", тип "image") и один выход ("out", тип "image"). Новые операции (splitter, merger, mask_overlay) смогут иметь произвольное количество портов.

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/registers/processor/catalog/schemas.py` -- добавить `Port`, расширить `ProcessingOperationDef`
- `Inspector_prototype/multiprocess_prototype_v3/registers/processor/catalog/loader.py` -- без изменений (YAML loader автоматически подхватит новые поля через Pydantic)
- `Inspector_prototype/multiprocess_prototype_v3/registers/processor/catalog/port_types.py` -- **создать**: enum/константы допустимых типов данных портов
- `Inspector_prototype/multiprocess_prototype_v3/tests/unit/test_port_schema.py` -- **создать**: тесты

**Шаги:**
1. Создать файл `port_types.py` с константами типов данных портов:
   ```
   PORT_TYPE_IMAGE = "image"       # numpy.ndarray BGR
   PORT_TYPE_MASK = "mask"         # numpy.ndarray grayscale / binary
   PORT_TYPE_DETECTIONS = "detections"  # list[dict]
   PORT_TYPE_CONTOURS = "contours"      # list[numpy.ndarray]
   PORT_TYPE_ANY = "any"           # любой тип (для универсальных операций)
   ```
   Также таблица совместимости `COMPATIBLE_TYPES: dict[str, set[str]]` -- какой output_type может подключаться к какому input_type. Например: `"image"` совместим с `"image"` и `"any"`.

2. В `schemas.py` добавить модель `Port(SchemaBase)`:
   ```python
   @register_schema("PortV3")
   class Port(SchemaBase):
       name: str          # "in", "out", "mask_in", "overlay_out" и т.д.
       data_type: str     # один из PORT_TYPE_* констант
       optional: bool = False  # если True -- порт не обязателен для работы операции
   ```

3. Расширить `ProcessingOperationDef` двумя полями с default-значениями:
   ```python
   input_ports: List[Port] = Field(
       default_factory=lambda: [Port(name="in", data_type="image")]
   )
   output_ports: List[Port] = Field(
       default_factory=lambda: [Port(name="out", data_type="image")]
   )
   ```
   Default-значения обеспечивают обратную совместимость -- существующие YAML-файлы каталога не нужно менять.

4. Добавить validator в `ProcessingOperationDef`: имена портов уникальны внутри input_ports и внутри output_ports.

5. Написать тесты:
   - Десериализация `ProcessingOperationDef` без портов -> default `[Port("in","image")]` / `[Port("out","image")]`
   - Десериализация с явными портами
   - Validator: дубли имён -> ValidationError
   - Функция `are_ports_compatible(output_port, input_port)` из `port_types.py`

**Критерии приёмки:**
- [ ] `Port` модель зарегистрирована через `@register_schema`
- [ ] `ProcessingOperationDef` имеет `input_ports` и `output_ports` с default
- [ ] Существующий YAML-каталог загружается без изменений (`load_catalog` работает)
- [ ] Тест: `are_ports_compatible("image", "image") == True`
- [ ] Тест: `are_ports_compatible("mask", "image") == False`
- [ ] Тест: `are_ports_compatible("image", "any") == True`
- [ ] Validator отклоняет дублирующиеся имена портов
- [ ] `ruff check` + `ruff format` проходят

**Вне scope:**
- Не менять `ProcessingNode` или `NodeInput` (уже содержит `output_port`)
- Не менять YAML-файлы каталога (default достаточно)
- Не менять `GraphRunnableBuilder` (Task 8.2)

**Edge cases:**
- Операция без входов (source node, например "frame_source") -- `input_ports=[]`
- Операция без выходов (sink node, например "logger") -- `output_ports=[]`
- `optional=True` порт -- не обязателен для валидации связей

**Зависимости:** нет
