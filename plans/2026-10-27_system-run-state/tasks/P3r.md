# Task P3r — чтение по пути узла после П3 (`backend_ctl`)

Основание: ревью CTO 2026-11-20, находка 3 (`docs/reports/2026-11-20_cto-review-1.0.md`); решение: «чинить у потребителя, тесты на оба места, до 2.4 и до пульта 6.5». Сессия полосы Ф, ветка `fix/run-state-p3-node-read`, база `dc56f14df`. Версия v2: правки стадии 0 (reviewer Sonnet, CHANGES REQUESTED 1 из 2, 7 пунктов — все применены).

## Проблема (факт, воспроизведён CTO и ревьюером на настоящем `TelemetryReadModel`)

После П3 (Task 2.8a) read-model хранит ЛИСТЬЯ (`LeafCopy`): dict-дельта по узлу раскладывается на листья.
`m.ingest("a.n", {"x": 3})` → `m.get("a.n")` = `None`; `m.get("a.n.x")` = `3`; `m.snapshot("a.n")` = `{"a.n.x": 3}`.
Потребители в `backend_ctl` спрашивают путь УЗЛА и проверяют `path in snapshot(...)`, поэтому для узла видят «пути нет»:

1. `backend_ctl/conditions.py` `_read_model_entry` (~477) — стартовая проверка `await_condition` видов `state_path` и `metric_threshold`: узел с dict-значением не матчится (`success: false`, `last_seen: None`).
2. `backend_ctl/conditions.py` `_unknown_metric_diagnosis` (~504-507): `list(snapshot(""))` и `path in observed` — тот же дефект: `metric_threshold` на узле отдаёт `unknown_metric: True`, `candidates: ['a.n.x']`. До П3 узел был значением по пути, маркера не было — регресс П3.
3. `backend_ctl/recorder.py` `ReplayDriver.state_get` (~811) — реплей отвечает `status: error, «Путь не существует»`, где живой `state.get` отдал бы вложенный dict (проверено: `state_get("a.n.x")` — ok).

## DESIGN

**Один общий помощник** в НОВОМ приватном модуле `backend_ctl/_node_read.py` (имя с `_` — без contract-lite; не пакет; `recorder.py` не тянет `conditions.py`, у `conditions.py` и `recorder.py` общий нейтральный импорт):

`read_node(drv, path) -> tuple[bool, Any]` — сам берёт `drv._telemetry_lock` (одно место блокировки; совместимо с `_StubDriver` из `test_replay_live_parity.py`, у которого есть `_telemetry_lock` и `_telemetry_model`), делает РОВНО ОДИН вызов `drv._telemetry_model.snapshot(path)` (инвариант: никаких `get()` и второго прохода — стаб модели реализует только `snapshot(prefix)`). Правила, по порядку:
1. `path` есть в снимке как лист → `(True, значение)` (значение может быть `None`: «узел со значением None» и «нет узла» — разные состояния, как сейчас). Лист-предок побеждает потомков (как `_assemble` в `leaf_copy.py`): смесь «лист `a.n.p` = 5 и потомок `a.n.p.q`» достижима через `ingest_poll_snapshot`, помощник НЕ бросает и вложенный dict там не строит.
2. Иначе, если есть ключи с префиксом `path + "."` → `(True, вложенный dict)` из листьев относительно `path` (ключи режутся по `.`; граница — точка: `a.n` не захватывает `a.n2.*`). Внутри поддерева при конфликте «лист и потомок» (`a.n.p` = 5 и `a.n.p.q`) — лист-предок побеждает, без исключения и без порядка-зависимости результата.
3. Иначе `(False, None)`. Пустой `path` (`""`): поведение НЕ меняется (для реплея `state_get("")` остаётся `error «Путь не существует: ''»`; `read_node(drv, "")` возвращает `(False, None)`; полный снимок идёт отдельным путём `snapshot("")`, не через помощник).

**Известное расхождение с живым `state.get`** (потеря информации ЛЕЖИТ в read-model, потребитель её не вернёт; чинить в ядре — отдельная задача, не здесь; фиксируем литералом, чтобы не «починили» случайно): (а) пустой dict-узел (`ingest("a.n", {})`) в read-model исчезает → `(False, None)`, живой отдаёт `{}`; (б) пустой вложенный dict внутри узла (`{"x":3,"e":{}}`) теряется → `(True, {"x": 3})`; (в) ключ с точкой в имени (`{"k.dot": 1}`) собирается как `{"k": {"dot": 1}}`.

`_unknown_metric_diagnosis`: путь «опознан», если он лист или префикс (`+ "."`) какого-то из наблюдённых ключей; всё остальное (консервативность, пустой свод → пропуск проверки, сбой чтения → пропуск) без изменений.
`conditions.py`/`recorder.py` меняются заменой чтения на `read_node`; формы ответов (`status`/`value`/`error`/`recorded`) не меняются. Вызовы под своим `_telemetry_lock` в `_read_model_entry` и `recorder.state_get` убираются (лок теперь внутри помощника). **`drv._telemetry_lock` — `threading.Lock`, НЕ `RLock`** (`driver.py:527`; проверено запуском): `read_node` под уже взятым локом не бросает, а ВЕШАЕТ поток. Поэтому: (i) в `_unknown_metric_diagnosis` свой `with drv._telemetry_lock` ОСТАЁТСЯ (ради `snapshot("")`), правило «лист или префикс» проверяется по списку `observed`, `read_node` там НЕ вызывается; (ii) тесты, зовущие боевые пути (`await_condition`, `state_get`), идут в daemon-потоке с `join`-дедлайном — иначе забытый `with` даст зависание вместо красного.
Не менять: `TelemetryReadModel`, `LeafCopy`, `driver.py`, `state_get_subtree` реплея и `telemetry_snapshot` (плоская форма намеренная).
Известное ограничение (существующее поведение, вне задачи; записать строкой в отчёт): предикат `state_path` совпадает только с дельтой РОВНО того же `path`; ожидание узла по последующим ЛИСТОВЫМ дельтам (`a.n.x` → 4) не сработает, хотя `initial_check` после правки видит собранный dict.
В отчёте — список ДРУГИХ мест репозитория, где после П3 читают путь узла (`git grep`, путь:строка), без правок; заранее известны, не оценены: `multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/io_debug_section.py:250` (`read_model.get(self._active_path)`), `multiprocess_prototype/frontend/state/bindings.py:201`, `multiprocess_framework/modules/frontend_module/state/telemetry_view_model.py:258,267`.

## FILES

- создать: `backend_ctl/_node_read.py`;
- править: `backend_ctl/conditions.py`, `backend_ctl/recorder.py`;
- тесты: новые файлы в `backend_ctl/tests/` с префиксом `test_p3r_`;
- запрещено: всё остальное, в частности `multiprocess_framework/modules/telemetry_readmodel_module/`, `state_store_module/`, `backend_ctl/driver.py`.

## REDS (acceptance; настоящий `TelemetryReadModel`, настоящий `BackendDriver`/`ReplayPlayer`; никаких шпионов на имя метода)

Поведенческие красные на базе (до кода): 4, 5 (и `last_seen`, и `unknown_metric`), 6 (остальные — 1, 2, 3, 7, 8, 9, 10 — красны только `ImportError`: `read_node` нет; поведения они НЕ доказывают; гейт «RED подтверждён» считать по 4, 5, 6).

1. Узел-dict: `ingest("a.n", {"x": 3})` → `read_node(drv, "a.n")` = `(True, {"x": 3})`; двухуровневый `{"p": {"q": 1}, "r": 2}` → тот же вложенный dict.
2. Лист `a.n.x` → `(True, 3)`; лист со значением `None` → `(True, None)`; отсутствующий `a.zz` → `(False, None)`; `read_node(drv, "")` → `(False, None)`.
3. Граница: при `a.n.x` и `a.n2.y` чтение `a.n` — только `{"x": …}`; `a.n2` — только `y`.
4. `await_condition("state_path", {"path": "a.n", "value": {"x": 3}})` на настоящем `BackendDriver` (как `test_await_condition.py`, дельта пришла ДО вызова) → `success`, `source: "read-model"`; ожидание другого dict → таймаут, `last_seen` содержит ВЛОЖЕННЫЙ dict.
5. `metric_threshold` на пути узла: не падает; `last_seen` = `{"path": "a.n", "value": {"x": 3}, …}`; порог не пересекается; в ответе НЕТ `unknown_metric`.
6. Реплей, оба пути попадания узла: (а) узел из снимка header (`_prime` → `prime(_flatten_tree(...))`), (б) узел из событий `state.changed`. В обоих `state_get("a.n")` → `status: ok`, `value` = вложенный dict, `recorded: True`; отсутствующий путь — прежний `status: error` с прежним текстом; `state_get("")` — прежний `error`.
7. Гонка: узел записан ДО старта потоков (иначе «узла нет» — легальное состояние); писатель — ТОЛЬКО `drv.dispatch_raw` (берёт лок внутри; прямой `drv._telemetry_model.ingest` из потока гоняется с читателем при любой реализации — тест недетерминирован), формы с инвариантом (`x == y` в каждой записи); читатель зовёт `read_node(drv, …)` (и отдельно `drv.await_condition(..., timeout=0)`; плечо await обязано утверждать «`last_seen` непустой и `x == y`», иначе оно вакуумно-зелёное: на откате оно читает «узла нет»). Ни `RuntimeError («dictionary changed size»)`, ни значения с `x != y`. Потоки daemon, join с дедлайном, итерации/время ограничены (писатель без паузы забивает EventHub). Ревьюер воспроизвёл гонку на прототипе без лока: 3 из 3 прогонов по 1 с — исключение; с локом — 0 из 9.
8. Расхождение с живым (литералы): `ingest("a.n", {})` → `(False, None)`; `{"x":3,"e":{}}` → `(True, {"x": 3})`; `{"k.dot": 1}` → `(True, {"k": {"dot": 1}})`.
9. Смесь: `ingest("a.n.p", 5)`, затем `ingest_poll_snapshot({"a.n.p.q": 1}, requested_at_seq=m.write_seq)` → `read_node(drv, "a.n")` не бросает, `(True, {"p": 5})`; `read_node(drv, "a.n.p")` → `(True, 5)`; и в обратном порядке записи результат тот же. Узел и лист на верхнем уровне (`a.n` = 5 и `a.n.x` = 1) → `read_node(drv, "a.n")` = `(True, 5)`.
10. Инвариант одного чтения: СВОЙ стаб модели только с `snapshot(prefix)` (не импортировать `_StubTelemetryModel` из чужого тест-модуля) проходит `read_node` без обращения к `get`.

Break-injection (предсказания лида до прогона, красные множества): (а) вернуть чтение `path in snapshot(path)` в `conditions.py::_read_model_entry` для `state_path` → красны {4, 7} (плечо await REDS 7 тоже краснеет); для `metric_threshold` → {5}; оба → {4, 5, 7}; (б) то же в `recorder.py` → {6}; (в) убрать фильтр `startswith(path + ".")` в `read_node` → ЭКВИВАЛЕНТНЫЙ мутант, красных нет (граница уже режется в `TelemetryReadModel.snapshot`); REDS 3 — регресс-страж границы ядра. Срез по `len(path)` вместо `len(path)+1` → красны {1,3,4,5,6,7,8,9,10}; (г) убрать лок в `read_node` → {7} (воспроизводимость назвать числом в отчёте; не гарантировать); (д) вернуть `path in observed` в `_unknown_metric_diagnosis` → {5}; (е) слепая сборка вложенного dict без правила «лист-предок побеждает» → {9}; (ж) в `read_node` вызвать `model.get` → {10} и три существующих теста радиуса (`test_replay_state_get_uses_backend_shape`, `test_replay_state_get_missing_path_is_error_like_live`, `test_state_get_key_sets_match_live_contract`: у `_StubTelemetryModel` нет `get`). Воспроизводимость (г): 5 из 5 прогонов красные на overlay ревьюера (macOS, 0,7 с), не гарантия.

## REPORT

Числа: красные до кода (поведенческие 4, 5, 6, 8… — перечислить) / зелёные после; радиус прогона `backend_ctl/tests` (класс по `machine_gate`); список других потребителей узла; известное ограничение предиката; пустой раздел «что осталось открытым / ненадёжно».
