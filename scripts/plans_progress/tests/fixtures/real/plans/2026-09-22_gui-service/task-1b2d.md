# Task 1b.2d — все правила регистра записаны описанием (спека лида, 2026-10-02)

**Статус: DONE 2026-10-02.** 1b.2d-1 — `e7f4dc8ad`, `e8aeffa54`; 1b.2d-2 — `c4dc0bc01`, `e8d7b2d2c`, `a38756a5b`, `a6984d468`.
Инъекции лида: 1b.2d-1 7/7, 1b.2d-2 13/13, правки ит.1 3/3 живы. Ревью: спека APPROVE_WITH_CHANGES → 1b.2d-1 APPROVE_WITH_NITS → 1b.2d-2 CHANGES_REQUESTED → ит.2 APPROVE_WITH_NITS (ниточка закрыта лидом).

Родитель: [`phase-1b-recipe-service.md`](phase-1b-recipe-service.md), пункт 1b.2d.
Ветка `feat/gs-1b2d` (worktree `.claude/worktrees/gs-1b2d`), стоит на слепых RED-тестах тестера
`fffefb5da` (`tests/gs-1b2d-blind`, отчёт `docs/reviews/2026-10-02_task-1b2d-tester.md`).

## Решения владельца 2026-10-02

1. **Отвергнутое значение не остаётся в регистре — чинить в 1b.2d.** Сегодня pydantic при
   `validate_assignment=True` присваивает значение и только потом зовёт `model_validator(mode="after")`;
   отказ не откатывает. Воспроизведено лидом на `OtelExportConfig`:
   `max_export_batch_size = 20480` → `rejected: «больше max_queue_size (2048)»`, `stored after reject: 20480`.
   Три места пишут голым `setattr`: `SchemaMixin.update_field` (`schema_mixin.py:270`),
   `RegistersManager.set_field_value` (`manager.py:196`), `ProcessModulePlugin.cmd_set_config`
   (`plugins/base.py:1625`, бэкенд). В последнем при правке нескольких полей часть применяется.
2. **Валидаторы `otel_export` и `line_filter` переходят в общие правила `FieldMeta`** (закрытый
   словарь), питоновских валидаторов у регистров не остаётся — контракт-тест AC4 зеленеет.
3. **1b.2c — после 1b.2d**, последовательно.

## Разбиение по решениям (каждая часть заканчивается зелёной)

### Task 1b.2d-1 — тип элементов контейнеров переживает описание
**Level:** Middle (Sonnet) · **Assignee:** developer
**Goal:** кодек `FieldInfo` переносит `list[X]` / `dict[K, V]`, копия отвергает неверный элемент как оригинал.
**DESIGN:**
- В `field_info.py` теги `list`/`dict` получают параметр элемента: в `to_dict()` ключ `item` (для `list`)
  и `key`/`value` (для `dict`) — вложенное описание того же закрытого набора тегов (рекурсивно, через
  `_type_tag`); `from_dict()` собирает `list[...]` / `dict[..., ...]` обратно.
  **Явно (правка ревью №3):** `list[dict]` → `item: {"type": "dict"}` (голый `dict` — тоже тег, ключ ЕСТЬ);
  вложенный `literal` несёт свои `choices`, иначе ключ опускается (не `Literal[None]`). Ключа нет только
  у голого `list`/`dict` и у элемента с тегом `unsupported` (`Any` и т.п.) — поведение как сегодня.
  `frontend/forms/factory/kinds.py:172` параметризованные контейнеры уже принимает — не трогать.
- Обратная совместимость payload: отсутствие `item`/`key`/`value` = голый контейнер (старый хаб).
- `tuple3int` не трогать. Типы элементов, которые реально встречаются: `int`, `dict`, `str` (`list[int]` ×6,
  `list[dict]` ×3, `dict[str, str]` ×1 — замер ревью 1b.2b-pre).
- Снять из докстринга `_build_register_copy` и ADR-RM-007 «Ограничения» пункт про параметризованные контейнеры.
**Files:** `multiprocess_framework/modules/registers_module/core/field_info.py`,
`multiprocess_framework/modules/registers_module/core/manager.py` (докстринг),
`multiprocess_framework/modules/registers_module/DECISIONS.md`,
`multiprocess_framework/modules/registers_module/tests/test_field_info_codec*.py` (тесты автора: round-trip, старый payload).
**REDS → GREEN:** `test_1b2d_copy_agrees_with_original.py::test_container_element_types_rejected_like_original` ×10.
**Out of scope:** правила, откат, Services, Plugins.

### Task 1b.2d-2 — правила описанием + атомарная запись
**Level:** Senior (Opus) · **Assignee:** teamlead — правка `SchemaBase`, базы всех регистров и конфигов.
**Goal:** правила регистров живут в `FieldMeta`, одинаково исполняются на оригинале и копии; отказ ничего не записывает.
**DESIGN (ред. 2 — после ревью спеки `ab6687e43fbbc4787`, APPROVE_WITH_CHANGES):**
- `FieldMeta(rules=...)` — закрытый словарь. Неизвестный ключ в конструкторе → `ValueError` (опечатка в
  классе видна сразу); в `FieldMeta.from_dict` неизвестный ключ правила **отбрасывается с предупреждением в лог**
  (GUI старше хаба не должен терять копию регистра целиком — `from_catalog`, `manager.py:389`). Пополняется
  только по реальной нужде. Ровно четыре правила:
  - `strip: bool` — `str.strip()` до остальных проверок (otel `endpoint`);
  - `pattern: str` + `pattern_message: str` — `re.fullmatch` по строке. otel `endpoint`:
    `https?://[^\s/?#]+/[^\s?#]*[^\s/?#][^\s?#]*` (teamlead сверяет с корпусом
    `Services/otel_export/tests/test_endpoint_signal_path_hazard.py` и вправе поправить регулярку, записав итог
    сюда). **Итог teamlead (2026-10-02): регулярка оставлена без поправок** — литерал
    `https?://[^\s/?#]+/[^\s?#]*[^\s/?#][^\s?#]*` в `Services/otel_export/config.py::ENDPOINT_RULES`; корпус:
    8/8 неполных адресов отвергнуты с `/v1/logs` и `404` в тексте, 3/3 полных приняты дословно, расхождений
    с прежним `urlparse` на корпусе нет (дрейф ниже — только вне корпуса). `pattern_message` обязан содержать `/v1/logs` и `404` (их требует корпус). **Принятый дрейф** против
    `urlparse`: отвергаются `HTTP://…` (верхний регистр схемы), адреса с `?` и `#`, пробел внутри; `http://[::1/…`
    даёт отказ валидации вместо `ValueError` из `urlparse`. Текст отказа для пустого адреса — `pattern_message`.
    Ещё два пункта дрейфа (ревью 1b.2d-2, ит.1): `http://h／x/v1/logs` (полноширинный `／`) — было отказ (NFKC
    в `urlparse`), стало принят — **ослабление**; `http://…` — было принят вместе с ``, стало отказ —
    **ужесточение**.
  - `value_pattern: str` + `pattern_message` — `re.fullmatch` для каждого значения `dict` (otel `headers`:
    `ENV_PLACEHOLDER_RE`). Сообщение называет КЛЮЧ и НЕ печатает значение. **Намеренное ужесточение:** сегодня
    `.match` пропускает `"${X}\n"`, правило — нет.
  - `choices_map: dict[str, str]` — поиск строго по `value.upper()` (не `casefold`: `"ınfo"` сегодня → `INFO`),
    иначе отказ. otel `level`: карта строится из `channel_routing_module/levels.py`, свой список имён не заводится.
  - `le_field: str` — значение поля ≤ значения названного поля; `None` с любой стороны — пропуск.
    `line_filter.dedup_radius le_field="hysteresis_margin"`, otel `max_export_batch_size le_field="max_queue_size"`.
    (`ge_field` не заводим — одного направления хватает, правка ревью №8.)
- **Где исполняются (правка ревью №4).** Поле-уровневые правила (`strip`, `pattern`, `value_pattern`,
  `choices_map`) — в `FieldMeta.__get_pydantic_core_schema__`: обёртка after-валидатором ТОЛЬКО когда `rules`
  непуст (поля без правил платят ноль; `field_validator("*")` на базе отвергнут — `AttributeError` наружу на
  нестроковом входе, ×4 цена построения у всех 130 наследников, порядок против валидаторов подкласса). Нестроковый
  вход в строковое правило → `ValueError` (= `ValidationError`), не `AttributeError`. `le_field` — в существующем
  `SchemaBase._check_field_constraints`. Итог: `__pydantic_decorators__` регистров пуст, AC4 без вычитаний.
- `to_dict()`/`from_dict()` `FieldMeta` переносят `rules` (JSON-safe: строки, bool, dict строк).
- **Атомарная запись (правки ревью №1, №2).** Один метод `SchemaMixin.apply_values(values: dict) -> tuple[bool,
  str | None]`: снимок затронутых ключей `__dict__` и копия `__pydantic_fields_set__` → `setattr` по ключам →
  при любом исключении восстановить ОБА и вернуть `(False, текст)`. Полная перевалидация через
  `model_validate({**текущие, **values})` **отвергнута**: у `otel_export` пустой дефолт `endpoint=""`, и правка
  `level` отвергалась бы по чужому полю (repro ревьюера). Текст ошибки — через
  `exc.errors(include_input=False)`: введённое значение (секрет в `headers`) не попадает в текст ни на одном
  пути. Через `apply_values` идут `update_field`, `RegistersManager.set_field_value` и `cmd_set_config`
  (`{"status": "error", "error": ...}` без исключения наружу; вызывающих по грепу: `set_field_value` 8 —
  все уже разбирают `(bool, err)`; `update_field` 3; `cmd_set_config` — 1 регистрация, прямых вызовов 0).
  `# ponytail:` **потолок** — правка двух связанных полей одним вызовом зависит от порядка ключей (допустимая
  пара `{max_queue_size: 100, max_export_batch_size: 50}` построчно отвергается). Так же и сегодня в
  `_init_register`; «всё или ничего» соблюдается. Снять — проверкой кандидата целиком, когда появится нужда.
- `set_field_value` уведомляет подписчиков и `send_callback` **сохранённым** значением (копия хранит `WARNING`,
  виджет должен получить `WARNING`, не `warn`) — правка ревью №9.
- `OtelExportConfig` и `LineFilterRegisters` теряют `field_validator`/`model_validator`; обоснования из их
  докстрингов (замер 404 на otelcol, запрет печати секрета) переезжают комментарием к `FieldMeta(rules=...)`.
- Документы: только локальные `data_schema_module/DECISIONS.md`, `registers_module/DECISIONS.md`. **Не трогать**
  `process_module/README.md`, `STATUS.md` и глобальный `multiprocess_framework/DECISIONS.md` и не запускать
  `scripts.sync` — их меняет `feat/t47d`; синхронизацию делает лид в точке слияния.
**Радиус тестов 1b.2d-2:** `Services/otel_export/tests`, `Plugins/io/otel_export/tests`, тесты `line_filter`,
`data_schema_module/tests`, `registers_module/tests` + оба файла `test_1b2d_*`.
**Files (7 → BRIEF-OVERRIDE при постановке):** `data_schema_module/core/field_meta.py`,
`data_schema_module/core/schema_base.py`, `data_schema_module/core/schema_mixin.py`,
`registers_module/core/manager.py`, `process_module/plugins/base.py` (только `cmd_set_config`),
`Services/otel_export/config.py`, `Plugins/filter/line_filter/registers.py`; + DECISIONS/README модулей.
**REDS → GREEN:** AC2 (8 тестов), AC3 оракул, AC4 контракт.
Тестер дозовом (`aabffbaa76a48548f`) до кода 1b.2d-2: (а) ужесточает 4 случая `_OneOf` до «значение не изменилось»
(6/5/512/2048) — красные и на оригинале, это ожидаемо; (б) RED на откат `update_field`; (в) RED «всё или ничего» у
`cmd_set_config` (отказ → `{"status":"error"}`, ни одно поле не изменилось); (г) RED «введённое значение не попадает
в текст ошибки» на копии (`headers={'Authorization': 'literal-secret'}`).
**Out of scope:** зона трека 4.7d (`data_receiver`, `pipeline_executor`, `plugin_runner`,
`frame_shm_middleware`, `router_manager.get_shm_stats`, `generic_process`, `Plugins/control/robot_control`);
`cmd_set_config` в `camera_service` (свой путь, отдельная находка); `blur` (регистра нет).

## Порядок

ревью спеки (reviewer `ab6687e43fbbc4787`, синхронно — ВЫПОЛНЕНО, APPROVE_WITH_CHANGES, правки внесены) →
1b.2d-1 developer и параллельно тестер дозовом добавляет RED для 1b.2d-2 (разные файлы) → инъекции лида →
тот же reviewer дозовом → 1b.2d-2 teamlead → инъекции → тот же reviewer дозовом → слияние лидом, SHA соседям.

## Открыто

- Флак: `process_module/tests/test_telemetry_default_enabled_hazards.py::…test_replace_without_default_enabled_key_reverts_the_flip`
  упал один раз в общем прогоне (радиус 1b.2d + process_module, 4333 passed); отдельно и в `process_module/tests` зелёный и на ветке (3187), и на main (3184). Ветка его не вносит — порядок прогона.

- Четвёртый путь голого `setattr` — `_init_register` (`plugins/base.py:1420-1422`, построение регистра из
  конфига): частичное применение при отказе не исследовано, в 1b.2d не входит.
- `camera_service.cmd_set_config` пишет через `_apply_field` — тот же класс дефекта отката или нет, не проверено.
- Бэкенд: что делает вызывающая сторона с исключением из `cmd_set_config` сегодня — не прослежено (1b.2c).
- Оракул тестера пробует ~40 значений; NaN, длинные строки, глубокая вложенность не пробуются.
- Пред-существующее (ревью 1b.2d-2, ит.1), follow-up, не чинить в 1b.2d: принятый `endpoint` с `user:pass@`
  печатается целиком при УСПЕШНОЙ записи — `_log_debug` в `RegistersManager.set_field_value`, `log_info applied=`
  в `ProcessModulePlugin.cmd_set_config` (`plugins/base.py:1655`), `_on_register_update`, трасса `TopologyBridge`.
