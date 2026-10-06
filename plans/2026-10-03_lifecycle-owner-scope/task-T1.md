# Task T1 — политика памяти GUI-процесса

**Ред. 4.** **Level:** Senior+ · **Assignee:** teamlead · **Layer:** framework (+1 строка в корне GUI прототипа)
**Refs:** [`plan.md`](plan.md) «Перестройка 2026-10-05»; [`CTO`](../../docs/reviews/2026-10-05_lifecycle-abort-root-cause-cto.md); [`task-0.4.md`](task-0.4.md)
**Зависит от:** 0.4 (`flush_deferred_deletes`). **Блокирует:** вливание в `main`, мегаплан GUI.
**Module contract:** public-api-change (`process_module/lifecycle/gc_discipline.py`) + new-lite (`frontend_module/core/qt_gc_policy.py`).
**Конвейер:** tester (A) → teamlead (B) → developer (C1, C2) → lead (гейт) → developer (D) → lead (A4, инъекции, стенд) → reviewer → CTO.

## Ред. 2 — что изменено

- R-1: «Порядок старта», следствия (а)–(д). R-2…R-5: строки 4, 5, 6, 9 A1. R-6/R-7: Q2 детерминирован, Q4 — доказательство вызова.
- R-8: Q5 — контроль «политика выкл. → AV». R-9: строка 12. D-3/R-19: выход `suspend` → `rearm_freeze()`, строка 13.
- R-10: «Потоки». R-11: фикстуры корня — те же имена, хук сводки — один. R-12/D-2: шаг 4 — Brief D. R-13/D-1: A4 пишет lead.
- R-14/D-5: В4 к CTO. R-15/D-4: повтор `collect_on` — лог. R-16: `Stability`/Pre/Post. R-17/D-9: «Стоимость».
- R-18/D-7: C1 + C2, один developer. D-6: allowlist R2 = 4. D-8: В1–В3 решены. Пробелы: импорты Q3, относительные импорты, лог «раз в 60 с» — со стенда.

## Ред. 4 — что изменено (ревью кода р1 + арбитраж CTO D1–D3, 2026-10-06)

Источник — [`docs/reviews/2026-10-06_task-T1-review-r1-and-cto-arbitration.md`](../../docs/reviews/2026-10-06_task-T1-review-r1-and-cto-arbitration.md).
Ред. 3 (раздела не было): `log=None` → `get_std_logger`; граница по росту `enabled_violations`.

- **D1, тик.** Вход — только `count[0] > threshold[0]`; поколение — старшее с `count > threshold` (строго, было `>=`).
  Страж long_lived из Python недоступен — вместо него ограничение по времени: gen2 тиком не чаще `full_interval_s`
  (новый параметр `collect_on`/`install_gui_memory_policy`, 60.0, конечный, `>= 0`, 0 — без ограничения) с последней
  полной сборки владельца любого происхождения, иначе gen1; отсчёт — от установки. `collect(full=True)` — без ограничения.
  Текст `ValueError` границ — новый (ниже).
- **D2, наблюдаемость.** `GcOwnerStats` — 17 полей (+ `full_collections`, `max_pause_ms_gen0`, `max_pause_ms_gen1`,
  `max_pause_ms_full`); A1 стр. 10: литерал 13 → 17. Строка раз в 60 с + `full=… max_gen0=… max_gen1=… max_full=…`.
- **D3, граница.** `collect(*, full=False, refreeze=False)`, `collect_now(*, refreeze=False)`; обе фикстуры границы —
  `collect_now(refreeze=True)`. Прод — никогда.
- **Ревью №1, мёртвая политика.** Граница первой проверкой — `pytest.fail("Политику памяти сняли посреди сессии: …")`;
  `collect_now`/`enforce` мёртвой политики — строка лога + `RuntimeError`; `install` вместо мёртвой ставит новую.
- **Ревью №5.** Отказ `attach` с чужого потока — одна строка лога с именем потока.
- **Ревью №3, авторские тесты** (не слепые): A1 — `test_bounds_rejected`, `test_freeze_none_reads_flag`,
  `test_gen2_not_more_often_than_full_interval`, `test_tick_enters_only_above_gen0_threshold_strict`,
  `test_collect_full_refreeze`; A2 (подпроцессы) — `test_uninstall_restores_and_reinstall_same`,
  `test_collect_now_on_dead_policy_raises`, `test_install_replaces_dead_policy`, `test_attach_refusal_logged`;
  хазард — `test_gc_policy_boundary_hazard.py::test_boundary_fails_when_policy_released`.

## Goal

В GUI-процессе сборка мусора — только на главном потоке: автосборка выключена, сборка по тику `QTimer` и на границах.
Один механизм (`gc_discipline` + исполнитель), тонкий Qt-адаптер, одна функция включения — для корня GUI прототипа,
будущего `apps/gui_client` и фикстур тестов. Не-GUI процессы — бит-в-бит.

## Порядок старта (поправка к посылке CTO, по коду)

`process_runner.py:139` `process.run()` (главный поток дочернего) → `frontend/process.py:314` `super().run()` →
`process_module.py:1146-1147` `heartbeat.start()` → `:1155-1156` `GcDiscipline(...).freeze_after_startup()` →
`process.py:316` `run_gui` → `app.py:63` `QApplication` → `install_gui_memory_policy`. Заморозка — до установки, слот пуст.

- (а) `FW_GC_FREEZE=1 FW_GC_SCHEDULED=1`: `GcDiscipline` делает collect + freeze + disable (`gc_discipline.py:66-75`) →
  `prior = False`, `release` вернёт `False`. Иначе `prior = True`.
- (б) Между заморозкой и установкой heartbeat может собрать на своём потоке; из Qt есть только `DataReceiverBridge`
  (`process.py:59`, жив через `self._bridge`). Риск низкий, принят.
- (в) `gc.unfreeze()` глобален: `rearm_freeze`/`release` снимают и стартовую заморозку (`_frozen` остаётся `True`). Цена — скорость, принято.
- (г) В `collect_scheduled` проверка слота и `gc.collect` разнесены: ≤ 1 сборка heartbeat сразу после установки. Принято.
- (д) `process_heartbeat.py:478-479` глотает исключения → `collect_scheduled` **первым** проверяет слот, `False`, не бросает.

`QApplication` переживает рестарт UI (ревьюер: два цикла `instance() or QApplication` + `exec` — тот же `id`, `QTimer(parent=app)`
жив) → повторный `install` — тот же объект. Комментарий `app.py:102` «новый app» неверен — вне объёма.

## Контракт реализации

### Ядро — `process_module/lifecycle/gc_discipline.py` (stdlib, без Qt)

```python
class CollectionExecutor(Protocol):   # где и когда зовётся тик; сам не собирает
    def start(self, tick: Callable[[], int], *, interval_s: float) -> None: ...
    def stop(self) -> None: ...
def collect_on(executor, *, interval_s=1.0, freeze: bool | None = None, freeze_after_s=5.0,
               full_interval_s=60.0, observe=False, log: Callable[[str], None] | None = None) -> GcCollectionOwner
def collection_owner() -> GcCollectionOwner | None
@contextmanager
def paused_gc() -> Iterator[None]                 # prev = gc.isenabled(); disable; на выходе ровно prev
@contextmanager
def suspend_collection_owner() -> Iterator[None]  # только тесты механизма
class GcCollectionOwner:
    thread_ident: int
    def tick(self) -> int
    def collect(self, *, full: bool = False, refreeze: bool = False) -> int  # refreeze — только с full
    def enforce(self) -> bool                     # True: автосборку включили извне, выключена снова
    def rearm_freeze(self) -> None
    def set_observe(self, on: bool) -> None
    def stats(self) -> GcOwnerStats
    def release(self) -> None
@dataclass(frozen=True)
class GcOwnerStats:  # 17 полей (ред. 4); to_dict() — только примитивы
    active: bool; executor: str; owner_thread: str; interval_s: float; observe: bool; frozen: bool
    collections: int; collected_objects: int; enabled_violations: int; foreign_collections: int
    last_pause_ms: float; max_pause_ms: float; total_pause_ms: float
    full_collections: int; max_pause_ms_gen0: float; max_pause_ms_gen1: float; max_pause_ms_full: float
```

Docstring модуля и новых публичных имён — `Stability: lite`, `Pre:`/`Post:` (сейчас `Stability` в файле — 0).
`log=None` → `get_std_logger(__name__).info` из `logger_module` (ред. 3: голый `logging.getLogger` запрещён стражем `test_std_logger_guard.py`).

**Слот процесса** (один: `gc` глобален):

| Из | Вызов | В | Эффект |
|---|---|---|---|
| пусто | `collect_on(ex)` | ACTIVE | `prior = gc.isenabled()`; `gc.disable()`; `ex.start(owner.tick, …)`; `observe` → хук `gc.callbacks` |
| ACTIVE | `collect_on(тот же ex)` | ACTIVE | тот же объект (`is`), параметры прежние (рестарт UI зовёт `install` снова); отличия → одна строка лога (текст — A1 стр. 2; имена через «, » в порядке сигнатуры), без исключения |
| ACTIVE | `collect_on(другой)` | — | `RuntimeError("collect_on: сборкой уже владеет другой исполнитель — сначала release()")` |
| ACTIVE | `release()` | пусто | `ex.stop()`; снять хук; морозил владелец → `gc.unfreeze()`; ровно `prior` |
| пусто | `release()` | пусто | no-op |
| ACTIVE | `suspend_collection_owner()` | пусто на блок | тик старого → 0; `gc` = `prior`. Выход: слот не пуст → освободить, `RuntimeError("suspend_collection_owner: блок оставил своего владельца")`; владелец вернулся, `gc.disable()`; морозил → `rearm_freeze()` |
| пусто | `suspend_collection_owner()` | пусто | `gc` не трогается; выход — та же проверка |

- `interval_s > 0`, `freeze_after_s >= 0`, `full_interval_s >= 0`, все конечные; иначе
  `ValueError("collect_on: interval_s, freeze_after_s и full_interval_s — конечные, interval_s > 0, остальные >= 0")` (ред. 4).
- **`tick()`** (ред. 4, D1): `enforce()`; вход только при `count[0] > threshold[0]` (иначе 0, `collections` не растёт);
  `gc.collect(gen)` старшего поколения с `count > threshold` (строго). По порогам как CPython; страж long_lived из Python
  недоступен — вместо него ограничение по времени: gen2 не чаще `full_interval_s` с последней полной сборки владельца
  (gen2 тиком, `collect(full=True)`, сборка перед заморозкой; отсчёт — от установки), иначе gen1.
  `collect(full=True)` — `gc.collect()`, по времени не ограничен.
- **`collect(full=True, refreeze=True)`** (ред. 4, D3): после полной сборки `gc.freeze()`, владелец «морозил» — снимают
  `release`/`rearm_freeze`/выход `suspend`. `refreeze` без `full` — `ValueError`. Только граница теста; прод — никогда
  (объект, замороженный живым и умерший позже, резидентен до `unfreeze`; тест с `gc.unfreeze()` → следующая граница —
  полная сборка всей кучи).
- **`enforce()`**: `gc.isenabled()` → `enabled_violations += 1`, `gc.disable()`, лог «автосборку включили извне — выключена (нарушений=N)».
- **Заморозка.** `freeze=None` → флаг `FW_GC_FREEZE`. Вкл. → первый `tick`/`collect` не раньше `freeze_after_s`:
  `gc.collect()` + `gc.freeze()`. `rearm_freeze()`: морозил владелец → `gc.unfreeze()`, отсчёт заново.
- **Наблюдаемость (ноль цены выкл.).** Выкл.: нет хука и `perf_counter`, растут счётчики-int (`collections`,
  `collected_objects`, `full_collections`, `enabled_violations`). Вкл.: `*_pause_ms`, в том числе по виду сборки
  `max_pause_ms_gen0/gen1/full` (full — gen2 тиком, `collect(full=True)`, сборка перед заморозкой); хук на
  `"start"`: поток ≠ владельца → `foreign_collections += 1`; раз в 60 с — строка `gc-policy: collections=… max_pause_ms=…
  violations=… foreign=… full=… max_gen0=… max_gen1=… max_full=…` в `log` (не в приёмке: часы не внедряемы; проверка — стенд).
- **`GcDiscipline`, две правки** (слот пуст → бит-в-бит 92fd0450f): `collect_scheduled` — первой строкой слот занят → `False`;
  `freeze_after_startup` при занятом слоте с потока ≠ владельца → `False` + лог ровно
  `GcDiscipline: freeze_after_startup пропущен — сборкой владеет другой поток`; с потока владельца — как было.

**Потоки.**
- Кроме `stats()`, `collection_owner()`, `paused_gc()` — только поток `collect_on`; иначе
  `RuntimeError("GcCollectionOwner: вызов не с потока-владельца сборки")`.
- Под локом модуля — **только** чтение/запись ссылки слота; владелец создаётся **до** лока (аллокация под локом при живой
  автосборке → финализатор входит в лок → взаимоблокировка; прецедент `qt_lifetime.py:24-31`). `collection_owner()` и
  проверка в `collect_scheduled` — атомарное чтение без лока.
- Хук `gc.callbacks` — без лога, лока, Qt-вызова и контейнеров: только `+= 1`. `stats()` — любой поток, без лока; поля не согласованы — принято.
- `paused_gc()` — любой поток (C1 кладёт его в daemon-тела: `test_subscribers.py::_bounded` :28-36, `worker` :429). Риск вне
  политики: вложенные на двух потоках (A prev=`True`, B prev=`False`; A включает, B выключает) оставят `gc` выключенным; строка в docstring.

### Qt-адаптер — `frontend_module/core/qt_gc_policy.py` (docstring по образцу `qt_lifetime.py`, `Stability: lite`)

```python
def install_gui_memory_policy(app: QCoreApplication | None = None, *, interval_s=1.0, freeze: bool | None = None,
                              freeze_after_s=5.0, full_interval_s=60.0, observe=False, log=None) -> GuiMemoryPolicy
def gui_memory_policy() -> GuiMemoryPolicy | None
class GuiMemoryPolicy:  # collect_now(*, refreeze=False) -> int; enforce() -> bool; set_observe(on); stats() -> dict; uninstall()
```

- `app is None` → `QCoreApplication.instance()` (в тестах может не быть). Поток ≠ `app.thread()` →
  `RuntimeError("install_gui_memory_policy: только поток QCoreApplication")` — первой проверкой, и при повторе.
- Повтор — тот же объект + `owner.rearm_freeze()` + подключить таймер, если приложение есть, а таймера нет.
  Прежняя политика мертва (её владельца нет в слоте: сняли мимо `uninstall`) — строка лога, она забыта, ставится новая
  (новый объект; ред. 4).
- Мёртвая политика: `collect_now()`/`enforce()` — строка лога и
  `RuntimeError("GuiMemoryPolicy: владелец сборки снят — политика не действует")` (ред. 4, ревью №1).
- Один приёмник строк на политику: `log` или `get_std_logger(__name__).info`; его получают ядро и исполнитель.
- `_QtMainThreadExecutor`: `QTimer(parent=app)`, `round(interval_s*1000)` мс, `timeout → tick`; без приложения — таймер при
  первом `collect_now()` или повторном `install`. Тик — только сборка: `DeferredDelete` доставит цикл. Приложение на
  чужом потоке → таймер не подключается, одна строка лога с именем потока до первого успешного подключения (ред. 4, ревью №5).
- `collect_now(*, refreeze=False)`: `enforce()`; таймер, если пора; `collect(full=True, refreeze=refreeze)`; приложение есть и `loopLevel() == 0` →
  `flush_deferred_deletes()` (`qt_lifetime`); `loopLevel() > 0` — без flush, без ошибки.
- `uninstall()` повторно — no-op. `stats()` = `owner.stats().to_dict()` + `timer_attached`. Прямых `gc.*` нет.

### Точки включения (единственные)

1. **Прод** `multiprocess_prototype/frontend/app.py::run_gui`, сразу после `:63`: `INSPECTOR_GUI_GC_POLICY != "0"` →
   `install_gui_memory_policy(app, observe=INSPECTOR_GC_OBSERVE == "1", log=process._log_info)`. `"0"` — A/B на стенде.
2. **`multiprocess_framework/modules/conftest.py`**: session autouse `_gui_memory_policy`: `pre = gui_memory_policy()`;
   `policy = pre or install_gui_memory_policy(None, freeze=True, freeze_after_s=0.0, observe=True)`; teardown —
   `config.gc_policy_stats = policy.stats()`, `uninstall()` только при `pre is None`. Function autouse `_gui_memory_boundary`
   (первым — teardown последним): setup `mark = policy.stats()["enabled_violations"]`; teardown — первой проверкой
   `not policy.stats()["active"]` → `pytest.fail("Политику памяти сняли посреди сессии: слот владельца сборки пуст — тест освободил его (release/uninstall)")`
   (ред. 4: проверка до `collect_now`, иначе её опередит `RuntimeError` мёртвой политики); `policy.enforce()`,
   `policy.collect_now(refreeze=True)` (ред. 4, D3), `violated = policy.stats()["enabled_violations"] > mark` (ред. 3: тик таймера в `processEvents()` pytest-qt лечит раньше границы); `violated` →
   `pytest.fail("Тест оставил автосборку gc включённой: восстановите прежнее состояние через paused_gc()")`.
3. **Корневой `conftest.py`** (прототип, Services, Plugins; В1): **те же имена и тела** фикстур, в `modules/` их перекрывает
   п. 2. Из корня грузятся обе (`pyproject.toml:155` — `state_store_module/tests`), из `modules/` корень — нет (`modules/pytest.ini`).
   `pytest_terminal_summary` — **один**, в `modules/conftest.py`: `gc-policy: … enabled_violations=… foreign_collections=…
   max_pause_ms=…` из `config.gc_policy_stats` (прогон только прототипа строки не даёт — принято). R3 зависит от п. 3:
   без него `gui_memory_policy()` → `None`.
4. **`apps/gui_client`** — как п. 1.

### Страж — `multiprocess_framework/modules/tests/test_gc_policy_guard.py` (AST)

`git ls-files '*.py'` под `multiprocess_framework/ multiprocess_prototype/ Services/ Plugins/ apps/ backend_ctl/ examples/`;
`gc.<attr>(…)` через `ast.Call` (строки-скрипты не считаются: `test_qt_lifetime.py:542,594,636`, `test_qt_lifetime_acceptance.py:207`).
GUI-файл — импорт `PySide6`/`shiboken6` или модуля на `qt_imports`, **и относительный** (`ImportFrom.module` на `qt_imports`,
любой `level`). Тест-файл — `/tests/` в пути или `test_*.py`/`conftest.py`. Ключ — `путь::` + внутренний `def`.

| Правило | Запрет | 92fd0450f (AST) | После T1 |
|---|---|---|---|
| R1 | не-тестовый GUI-файл: `gc.collect/enable/disable/set_threshold/freeze/unfreeze` | 0 | 0 |
| R2 | тест-файл: `gc.enable()` | 17 в 8 файлах | 4, все в allowlist |
| R3 | GUI тест-файл: `gc.collect()` → `gui_memory_policy().collect_now()` | 4 в 2 файлах прототипа | 0 |

Allowlist `{"путь::функция": причина}`: без причины не считается, мёртвая запись — красный. Ровно 4:
`base_manager/tests/test_lifetime_scope.py::worker` («намеренная автосборка на рабочем потоке; Qt-мусор снят границей») и
`process_module/tests/test_gc_collection_owner.py::` строк 1, 4, 8 A1 («тест механизма: включает автосборку намеренно,
enforce/paused_gc восстанавливают»).

## Steps

1. **tester, Brief A** (слепо): A1, A2, A3; RED (`ImportError`).
2. **teamlead, Brief B**: A1–A2 зелёные, A3 красный только по R2/R3.
3. **developer** (Middle+, не junior: тела на потоках): **C1**, затем тот же агент по agentId — **C2**. C1 от В1 не зависит,
   C2 — после Brief B (корневая фикстура). Итог: A3 зелёный.
4. **lead**: полный гейт под политикой → node id красных из-за расчёта на автосборку. **developer, Brief D**: в каждом — явная
   сборка на главном в тесте (Qt — `gui_memory_policy().collect_now()`), не исключение в политике; FILES = список lead
   (> 6 файлов — два брифа). > 10 тестов → эскалация CTO до правки.
5. **lead**: пишет A4, инъекции, стенд; числа — в `plan.md`. 6. reviewer (фиксированный SHA) → CTO.

`MF/` = `multiprocess_framework/modules/`.
**C1** — `gc.disable(); try: X finally: gc.enable()` → `with paused_gc(): X` (прочее из `finally` — в `try` внутри `with`). FILES:
1. `MF/base_manager/tests/test_lifetime_scope.py` :381; `worker` :429-442 — тело в `paused_gc()`, `gc.enable()` :438 остаётся,
   :442 уходит, `set_threshold(*old)` остаётся
2. `MF/base_manager/tests/test_lifetime_scope_acceptance.py` :907, :1644
3. `MF/event_module/tests/test_subscribers.py` :147
4. `MF/event_module/tests/test_subscribers_acceptance.py` :316, :343
5. `MF/frontend_module/tests/test_qt_lifetime_acceptance.py` :178–187

**C2** — особые случаи. FILES:
1. `MF/process_module/tests/test_gc_discipline.py` — фикстура (function scope) `with suspend_collection_owner(): yield`;
   **удалить** `gc.enable()` :32, :42, :53, :88 (`gc.disable` перед `try` нет — шаблон не подходит; состояние вернёт выход
   `suspend`); `gc.unfreeze()` остаются (выход — `rearm_freeze`).
2. `MF/tests/_road_cost.py` :109, :244 — окна замера в `paused_gc()`.
3. `MF/tests/test_road_cost_contract.py` — `gc.enable()` :54, :58 убрать; `assert gc.isenabled()`
   :149, :160 → `is before` (`before` — в начале теста).
4. `multiprocess_prototype/frontend/tests/test_unattended_mode.py` :183 и
5. `multiprocess_prototype/frontend/widgets/tabs/plugins/tests/test_paths_section_ownership.py` :89, :133, :135 —
   `gc.collect()` → `gui_memory_policy().collect_now()`.

TESTS C2: пять файлов + импортёры `_road_cost`: `MF/tests/test_road_cost_hazards.py`,
`MF/process_module/tests/test_f2_numbers_disabled_cost_bench.py`, `MF/process_module/tests/test_plugin_stats_road.py`.

## Acceptance criteria и инъекции

### A1, A2 — тесты механизма (tester, слепо)

**A1** `process_module/tests/test_gc_collection_owner.py`, без Qt: фикстура (function scope) `with suspend_collection_owner(): yield`;
фейк-исполнитель пишет `start/stop`. **A2** `frontend_module/tests/test_qt_gc_policy.py`: сессионная политика, `qapp`.
Может зависнуть → daemon, `join(5)`. `gc`/пороги — в `try/finally`.

| # | Тест | Проверка (литералы) | Инъекция |
|---|---|---|---|
| 1 | `test_collect_on_disables_and_release_restores_prior` | `gc.enable()` явно (prior сессии — не опора); `collect_on` → `isenabled() is False`, `release` → `True`; с `gc.disable()` → `False` | `release` = `gc.enable()` |
| 2 | `test_same_executor_idempotent_other_rejected` | повтор `is`; с `interval_s=2.0` → `is`, лог `== ["collect_on: повторный вызов с другими параметрами — оставлены прежние (interval_s)"]`; другой → `RuntimeError`, `"уже владеет"` | замена владельца |
| 3 | `test_foreign_thread_calls_raise` | `collect()`, `release()` из daemon → `RuntimeError`, `"потока-владельца"` | без проверки потока |
| 4 | `test_enforce_heals_and_counts_once` | `gc.enable()`; `tick()` → `isenabled() is False`, `enabled_violations == 1`; `tick()` → `1` | без `gc.disable()` |
| 5 | `test_tick_generation_aware` | `set_threshold(10**9, 10**9, 10**9)` → `tick() == 0`, `collections == 0`; `set_threshold(1)` + 100 циклов → `collections == 1`, вернул ≥ 100; `finally` — прежние пороги | тик = `gc.collect()` |
| 6 | `test_scheduled_collect_yields_to_owner` | `FW_GC_*`=1; `freeze_after_startup()` **до** `collect_on` (как в проде); `collect_scheduled(100.0) is False`; после `release` — `True` | без проверки слота |
| 7 | `test_observe_off_zero_cost_on_counts_foreign` | выкл.: `len(gc.callbacks)` как до, `max_pause_ms == 0.0`; вкл. → `+1`, `gc.collect()` в daemon → `foreign_collections == 1` | хук всегда |
| 8 | `test_paused_gc_restores_exact_state` | prior выкл. + внутри `gc.enable()` → `False`; prior вкл. → `True` | выход = `gc.enable()` |
| 9 | `test_freeze_deadline_and_rearm` | `freeze=True, freeze_after_s=0`: `tick()` → `get_freeze_count() > 0`; `rearm_freeze()` → `== 0`; `tick()` → `> 0`; `release()` → `== 0` | `release` без `unfreeze` |
| 10 | `test_stats_dict_primitives` | ровно 17 ключей (ред. 4, было 13); значения `bool/int/float/str` | поле-объект |
| 11 | `test_suspend_requires_empty_slot` | `collect_on` в блоке без `release` → `RuntimeError`, `"оставил"` | выход без проверки |
| 12 | `test_freeze_after_startup_foreign_thread_refused` | `FW_GC_FREEZE=1`; `collect_on` на главном; `GcDiscipline(log=got.append).freeze_after_startup()` в daemon → `False`; `got == ["GcDiscipline: freeze_after_startup пропущен — сборкой владеет другой поток"]`; `get_freeze_count()` не изменился | без проверки потока |
| 13 | `test_suspend_exit_rearms_freeze` | `collect_on(…, freeze=True, freeze_after_s=0)`, `tick()`; блок `suspend` с `gc.unfreeze()`; после выхода `collect()` → `get_freeze_count() > 0` | выход без `rearm_freeze` |
| Q1 | `test_install_off_app_thread_raises` | из daemon → `RuntimeError`, `"только поток QCoreApplication"` | проверка после раннего возврата |
| Q2 | `test_timer_collects_qwidget_cycle_on_main` | ниже | таймер не стартует |
| Q3 | `test_collect_now_flushes_outside_loop` | ниже | без flush |
| Q4 | `test_collect_now_inside_loop_no_flush_no_error` | `singleShot(0, slot)` в `qtbot.wait(200)`, `slot` зовёт `collect_now()`, исключения — в список → вызван ровно 1 раз, список пуст | flush безусловно (бросит при `loopLevel() > 0`) |
| Q5 | `test_worker_alloc_with_policy_survives_subprocess` | подпроцесс (`timeout=60`): 6 деревьев `QWidget`+`QTimer` в циклах, политика, поток аллоцирует 400 000 объектов, 2 тика → `returncode == 0` | ниже |

- **Q2.** `policy.collect_now()`; предусловие `policy.stats()["timer_attached"] is True`. `h.me = h; h.w = QWidget()`;
  `h.w.destroyed.connect(on_d, Qt.ConnectionType.DirectConnection)`, `on_d` пишет `threading.get_ident()` в `seen`; `del h`;
  `keep = [[] for _ in range(1000)]` (живые: счётчик gen0 ≥ 700, первый тик соберёт gen0);
  `qtbot.waitUntil(lambda: seen, timeout=2500)`; `seen == [threading.get_ident()]`.
- **Q3.** `from multiprocess_framework.modules.base_manager import open_scope`,
  `from multiprocess_framework.modules.frontend_module.interfaces import attach_qt`; `root = open_scope("t1-q3", budget_s=1.0)`;
  `o = QObject(); attach_qt(root, o)`; `root.close()` в daemon; `policy.collect_now()` → `shiboken6.isValid(o) is False`.
- **Q5.** AV может не воспроизводиться (CTO: на Linux CI abort нет, cto.md:56). Инъекцию lead пишет только на Windows native с
  контролем «политика выкл. → AV в N/N»; контроль не упал → в `plan.md` «тест не различает на этой машине», не «зелёный».

### A3 — страж (tester), A4 — прогоны (lead)

**A3:** `test_gui_code_has_no_gc_calls` (R1), `test_tests_do_not_reenable_gc` (R2), `test_qt_tests_collect_through_policy` (R3),
`test_scanner_sees_synthetic_violation` (`"import gc\ngc.enable()\n"` → 1; `from ..core.qt_imports import X` + `gc.collect()`
→ R1 = 1), `test_allowlist_has_no_dead_entries`.

**A4 `scripts/gc_policy_acceptance.py`** (lead, шаг 5; не pytest): подпроцесс `python -X faulthandler -m pytest -q -p no:cacheprovider …`,
cwd `multiprocess_framework/modules`, `timeout` 900 с (гейт) / 300 с; падение — код ∉ {0, 1} или `Fatal Python error`/
`Windows fatal exception`; `--offscreen` → `QT_QPA_PLATFORM=offscreen`; печать `SUMMARY <имя> crashes=X/N failed=Y gc_violations=Z platform=…`.

| Имя | Набор | Требование | Инъекция lead → ожидание |
|---|---|---|---|
| `chain` | `frontend_module/tests/test_base_tree_nav_tab.py`, `…/test_qt_event_bridge.py`, `event_module/tests/test_subscribers.py::test_release_from_gc_finalizer_under_publisher_lock_no_deadlock` (16) | 0/20 native, 0/20 offscreen | пустое тело `_gui_memory_boundary` → ≥ 1/20 (CTO 5/5) |
| `reverse` | `frontend_module/tests event_module/tests` | 0/5 native | то же → ≥ 1/5 (CTO 2/2) |
| `four` | первые два `chain` + `test_qt_lifetime.py::test_concurrent_attach_from_four_threads` | 0/20 native | `collect_on` без `gc.disable()` → ≥ 1/20 (CTO 5/5) |
| `gate` | `scripts/run_framework_tests.py` | 0/5 native, 0/2 offscreen, `enabled_violations=0` в каждом | — |

Контроль не упал → «не различает», как Q5. Время гейта ≤ 1.30 × базы (медиана 3 прогонов на 92fd0450f, та же
машина); `foreign_collections` гейта — база храповика. **Стенд** (`INSPECTOR_GUI_UNATTENDED=1`, 10 мин, `INSPECTOR_GC_OBSERVE=1`,
`FW_GC_FREEZE` 0 и 1): `max_pause_ms` ≤ 50; RSS (Get-Process) ≤ 1.15 × прогона с `INSPECTOR_GUI_GC_POLICY=0`; строка
«раз в 60 с» в логе. Превышение — цифры CTO.

## Out of scope

Источники и храповик Qt-мусора — мегаплан GUI; Ф1–Ф6; ручка `observe` в `app.yaml`/`backend_ctl`; `ProcessModule`, heartbeat; `app.py:102`.

## Риски

- **Пауза главного:** тик ≈ каденции CPython; `gen2` — десятки мс (стенд). **RSS:** длинный слот — мусор копится.
- **Сторонний `gc.collect`/`gc.enable`** (site-packages, `pyqtgraph.GarbageCollector`) — R1 не видит; `enforce` лечит, `foreign_collections` видит.
- **Граница теста:** полный `gc.collect()` (CTO: +35 мс/тест без заморозки) — порог 1.30. PySide6 в прогоне modules — ~1 с.
- **`gc.unfreeze()` в тестах** (`test_gc_discipline.py`, A1 9, 13) снял бы заморозку сессии → время гейта от порядка.
  Закрыто: выход `suspend` → `rearm_freeze()`. **Free-threaded Python** — пересмотреть при переходе.

## Executor brief B (GREEN)
```
TASK: T1 — политика памяти GUI-процесса   PLAN: plans/2026-10-03_lifecycle-owner-scope/plan.md
ROLE: teamlead
CHAIN: tester(RED, Brief A) -> you -> developer(C1, C2) -> lead(gate, Brief D, injections) -> reviewer
DESIGN: разделы «Ядро» (слот, «Потоки», Stability/Pre/Post; GcDiscipline — только две правки), «Qt-адаптер» (QTimer(parent=app),
  flush из qt_lifetime), «Точки включения» 1–3 (две conftest, app.py — одна строка) этой спеки.
FILES:
  1. multiprocess_framework/modules/process_module/lifecycle/gc_discipline.py
  2. multiprocess_framework/modules/frontend_module/core/qt_gc_policy.py — новый
  3. multiprocess_framework/modules/conftest.py
  4. conftest.py (корень репо)
  5. multiprocess_prototype/frontend/app.py
  6. multiprocess_framework/modules/process_module/DECISIONS.md — ADR «Сборкой владеет поток-исполнитель»
  BRIEF-OVERRIDE: frontend_module/core/README.md, process_module/STATUS.md — только текст, после зелёного.
REDS (весь A1/A2 красен по ImportError; несущие): A1 строки 1, 2, 4, 5, 6, 9, 12, 13; A2 Q2, Q3.
TESTS: QT_QPA_PLATFORM=offscreen pytest -q --tb=short A1 A2 process_module/tests/test_gc_discipline.py
  frontend_module/tests/test_qt_lifetime.py
OUT OF SCOPE: источники Qt-мусора, ProcessModule, heartbeat, app.yaml-ручка, чужие тесты (C/D), app.py:102.
TRAPS: под локом только слот, владелец до лока; хук без лога/лока/контейнеров; release → prior; flush при loopLevel()==0;
  повторный install — тот же объект + таймер; collect_scheduled не бросает.
```
Brief A (tester): A1–A3, только эта спека. C1/C2/D (developer): FILES из «Steps», BRIEF-OVERRIDE: шаблон без логики.

## Вопросы

- **В1, В2, В3 — решены lead:** корневой `conftest.py` — в T1 (814/2482 тестов прототипа оставляют Qt-мусор); граница —
  полный `gc.collect()`, база — медиана 3; заморозка в GUI — по `FW_GC_FREEZE`, стенд мерит оба.
- **В4 — открыт, CTO на приёмке T1:** где жить ядру для `apps/gui_client`. Сейчас `process_module/lifecycle/gc_discipline.py`
  (размещение CTO); импорт тянет ядро `ProcessModule` через `lifecycle/__init__.py` и `__init__` пакета: ~2289 модулей,
  ~1058 мс (замер ревьюера, не повторён).

## Стоимость (оценка)

5 агентов × ~56k старта = 280k + работа: tester ~90k, teamlead ~150k, developer ~110k (C1 45k, C2 45k, D 20k), reviewer
~80k, CTO ~100k = 530k. Итого **≈ 0.81 M токенов** (0.6–1.1 M); второй круг ревью и D > 6 файлов — сверх; lead — не входит.

## Для мегаплана GUI

- `apps/gui_client`: `install_gui_memory_policy(app, log=…)` сразу после `QApplication`. Импорт ядра сегодня — ~1 с,
  ~2289 модулей ядра `ProcessModule`; от `ProcessModule` **зависит**. Размещение — В4.
- `observe` — в `observability` (`app.yaml`, hot-reload) и `backend_ctl`, с маршалом на главный поток; `stats()` — в телеметрию.
- Храповик Qt-мусора на тест (`DEBUG_SAVEALL`), база из T1; `QObject` живёт и умирает на главном, `QTimer` с родителем;
  без сильных циклов view↔presenter, лямбд на `destroyed`, `QObject` в `QRunnable`.
