# Task T1 — политика памяти GUI-процесса

**Ред. 1.** **Level:** Senior+ · **Assignee:** teamlead · **Layer:** framework (+1 строка в корне GUI прототипа)
**Refs:** [`plan.md`](plan.md) «Перестройка 2026-10-05»; [`CTO`](../../docs/reviews/2026-10-05_lifecycle-abort-root-cause-cto.md); [`task-0.4.md`](task-0.4.md)
**Зависит от:** 0.4 (`flush_deferred_deletes`). **Блокирует:** вливание в `main`, мегаплан GUI.
**Module contract:** public-api-change (`process_module/lifecycle/gc_discipline.py`) + new-lite (`frontend_module/core/qt_gc_policy.py`).
**Конвейер:** ревью спека → tester (RED, слепо) → teamlead (GREEN) → developer (механика) → lead (инъекции, прогоны) → reviewer → CTO.

## Goal

В GUI-процессе сборка мусора — только на главном потоке: автосборка выключена, сборка по тику `QTimer` и на границах.
Один механизм (`gc_discipline` + исполнитель), тонкий Qt-адаптер, одна функция включения — для корня GUI прототипа,
будущего `apps/gui_client` и фикстур тестов. Не-GUI процессы — бит-в-бит.

## Поправка к посылке CTO (по коду)

`GuiProcess(ProcessModule)` (`frontend/process.py:27`, `super().run()` :314) — heartbeat и `GcDiscipline` в GUI есть; при
`FW_GC_FREEZE=1 FW_GC_SCHEDULED=1` `_pump_scheduled_gc` собирает на потоке heartbeat. T1: `collect_scheduled` уступает владельцу.

## Контракт реализации

### Ядро — `process_module/lifecycle/gc_discipline.py` (stdlib, без Qt)

```python
class CollectionExecutor(Protocol):   # где и когда зовётся тик; сам не собирает
    def start(self, tick: Callable[[], int], *, interval_s: float) -> None: ...
    def stop(self) -> None: ...
def collect_on(executor, *, interval_s=1.0, freeze: bool | None = None, freeze_after_s=5.0,
               observe=False, log: Callable[[str], None] | None = None) -> GcCollectionOwner
def collection_owner() -> GcCollectionOwner | None
@contextmanager
def paused_gc() -> Iterator[None]                 # prev = gc.isenabled(); disable; на выходе ровно prev
@contextmanager
def suspend_collection_owner() -> Iterator[None]  # только тесты механизма
class GcCollectionOwner:
    thread_ident: int
    def tick(self) -> int
    def collect(self, *, full: bool = False) -> int
    def enforce(self) -> bool                     # True: автосборку включили извне, выключена снова
    def rearm_freeze(self) -> None
    def set_observe(self, on: bool) -> None
    def stats(self) -> GcOwnerStats
    def release(self) -> None
@dataclass(frozen=True)
class GcOwnerStats:  # 13 полей; to_dict() — только примитивы
    active: bool; executor: str; owner_thread: str; interval_s: float; observe: bool; frozen: bool
    collections: int; collected_objects: int; enabled_violations: int; foreign_collections: int
    last_pause_ms: float; max_pause_ms: float; total_pause_ms: float
```

**Слот процесса** (один: `gc` глобален):

| Из | Вызов | В | Эффект |
|---|---|---|---|
| пусто | `collect_on(ex)` | ACTIVE | `prior = gc.isenabled()`; `gc.disable()`; `ex.start(owner.tick, …)`; при `observe` — хук `gc.callbacks` |
| ACTIVE | `collect_on(тот же ex)` | ACTIVE | **тот же** объект (`is`), параметры игнорируются |
| ACTIVE | `collect_on(другой)` | — | `RuntimeError("collect_on: сборкой уже владеет другой исполнитель — сначала release()")` |
| ACTIVE | `release()` | пусто | `ex.stop()`; снять хук; `gc.unfreeze()`, если морозил владелец; восстановить ровно `prior` |
| пусто | `release()` | пусто | no-op |
| ACTIVE | `suspend_collection_owner()` | пусто на блок | тик старого → 0; `gc` = `prior`; выход: слот не пуст → освободить и `RuntimeError("suspend_collection_owner: блок оставил своего владельца")`; владелец вернулся, `gc.disable()` |

- `interval_s > 0`, `freeze_after_s >= 0`, конечные; иначе `ValueError("collect_on: interval_s и freeze_after_s — конечные, interval_s > 0")`.
- **Потоки.** Всё, кроме `stats()`/`collection_owner()`, — только поток, вызвавший `collect_on`; иначе
  `RuntimeError("GcCollectionOwner: вызов не с потока-владельца сборки")`. `stats()` — любой поток, без лока. Лок модуля —
  только на слот, под ним нет `gc.collect`.
- **`tick()`**: `enforce()`, затем по поколениям, как CPython, но на этом потоке: `gc.collect(gen)` старшего поколения,
  чей `gc.get_count()` достиг `gc.get_threshold()`; ни одно — 0, `collections` не растёт. `collect(full=True)` — `gc.collect()`.
- **`enforce()`** (всегда): `gc.isenabled()` → `enabled_violations += 1`, `gc.disable()`, лог «автосборку включили извне — выключена (нарушений=N)».
- **Заморозка.** `freeze=None` → флаг `FW_GC_FREEZE`. Вкл. → первый `tick`/`collect` не раньше `freeze_after_s`:
  `gc.collect()` + `gc.freeze()`. `rearm_freeze()`: морозил владелец → `gc.unfreeze()`, отсчёт заново (рестарт UI: иначе
  старое окно навсегда в permanent).
- **Наблюдаемость (ноль цены выкл.).** Выкл.: нет хука и `perf_counter`, растут только три счётчика-int. Вкл.:
  `*_pause_ms`; хук `gc.callbacks` на `"start"`: поток ≠ владельца → `foreign_collections += 1` (без лога, лока,
  аллокаций); раз в 60 с — строка `gc-policy: collections=… max_pause_ms=… violations=… foreign=…` в `log`.
- **`GcDiscipline`, две правки:** слот занят → `collect_scheduled` = `False` (heartbeat в GUI не собирает);
  `freeze_after_startup` с чужого потока = `False` + лог. Слот пуст → бит-в-бит как в 92fd0450f.

### Qt-адаптер — `frontend_module/core/qt_gc_policy.py` (docstring по образцу `qt_lifetime.py`)

```python
def install_gui_memory_policy(app: QCoreApplication | None = None, *, interval_s=1.0, freeze: bool | None = None,
                              freeze_after_s=5.0, observe=False, log=None) -> GuiMemoryPolicy
def gui_memory_policy() -> GuiMemoryPolicy | None
class GuiMemoryPolicy:  # collect_now() -> int; enforce() -> bool; set_observe(on); stats() -> dict; uninstall()
```

- `app is None` → `QCoreApplication.instance()` (в тестах его ещё нет). Поток ≠ `app.thread()` →
  `RuntimeError("install_gui_memory_policy: только поток QCoreApplication")` — первой проверкой, и при повторе.
- Повторный вызов (рестарт UI) — тот же объект + `owner.rearm_freeze()`.
- `_QtMainThreadExecutor`: `QTimer(parent=app)`, `round(interval_s*1000)` мс, `timeout → tick`; без приложения — подключить
  при первом `collect_now()`. Тик в цикле — только сборка: `DeferredDelete` доставит цикл.
- `collect_now()`: `enforce()`; подключить таймер, если пора; `collect(full=True)`; есть приложение и
  `loopLevel() == 0` → `flush_deferred_deletes()` (из `qt_lifetime`); `loopLevel() > 0` — без flush, без ошибки.
- `stats()` = `owner.stats().to_dict()` + `timer_attached`. Прямых `gc.*` в файле нет.

### Точки включения (единственные)

1. **Прод** `multiprocess_prototype/frontend/app.py::run_gui` — сразу после создания `QApplication`: если
   `INSPECTOR_GUI_GC_POLICY != "0"` → `install_gui_memory_policy(app, observe=INSPECTOR_GC_OBSERVE == "1",
   log=process._log_info)`. `"0"` — только для A/B на стенде.
2. **Тесты фреймворка** `modules/conftest.py`: session autouse `_gui_memory_policy` —
   `install_gui_memory_policy(None, freeze=True, freeze_after_s=0.0, observe=True)`; teardown — `stats()` в глобал,
   `uninstall()`. Function autouse `_gui_memory_boundary` (первым — teardown последним): `violated = policy.enforce()`,
   `policy.collect_now()`; `violated` → `pytest.fail("Тест оставил автосборку gc включённой: восстановите прежнее
   состояние через paused_gc()")`. `pytest_terminal_summary` — строка `gc-policy: … enabled_violations=… foreign_collections=… max_pause_ms=…`.
3. **Тесты из корня** (прототип, Services, Plugins) — корневой `conftest.py`, то же (В1). 4. **`apps/gui_client`** — тот же вызов.

### Страж — `multiprocess_framework/modules/tests/test_gc_policy_guard.py` (AST)

`git ls-files '*.py'` под `multiprocess_framework/ multiprocess_prototype/ Services/ Plugins/ apps/ backend_ctl/ examples/`;
вызовы `gc.<attr>(…)` через `ast.Call` (скрипты подпроцессов в строках не считаются). GUI-файл — импортирует
`PySide6`/`shiboken6`/`frontend_module.core.qt_imports`; тест-файл — путь с `/tests/` или `test_*.py`/`conftest.py`.

| Правило | Запрет | 92fd0450f (AST) | После T1 |
|---|---|---|---|
| R1 | не-тестовый GUI-файл: `gc.collect/enable/disable/set_threshold/freeze/unfreeze` | 0 | 0 |
| R2 | тест-файл: `gc.enable()` | 17 в 8 файлах | 1 — allowlist `test_lifetime_scope.py::worker` («намеренная автосборка на рабочем потоке; Qt-мусор снят границей») |
| R3 | GUI тест-файл: `gc.collect()` → `gui_memory_policy().collect_now()` | 4 в 2 файлах прототипа | 0 |

Allowlist `{"путь::функция": причина}`: без причины не считается, мёртвая запись — красный.

## Steps

1. tester, Brief A (слепо): A1–A4, RED-прогон (`ImportError`). 2. teamlead, Brief B: A1–A2 зелёные, A3 красный по R2/R3.
3. developer, Brief C: 10 файлов по шаблону, A3 зелёный. 4. lead: полный гейт под политикой; красные из-за расчёта на
автосборку — явная сборка на главном в тесте, не исключение в политике; > 10 таких — эскалация CTO. 5. lead: инъекции,
A4, стенд; числа — в `plan.md`. 6. reviewer (фиксированный SHA) → CTO.

**Шаблон Brief C.** `gc.disable(); try: X finally: gc.enable()` → `with paused_gc(): X` (прочие строки `finally`
остаются в `try` внутри `with`). `test_gc_discipline.py`: + фикстура файла `with suspend_collection_owner(): yield`.
`_road_cost.py`: окна замера в `paused_gc()`. `test_road_cost_contract.py`: из `_isolate_debug_hooks` убрать
`gc.enable()`; `assert gc.isenabled()` → `is before`. `test_lifetime_scope.py::worker`: тело в `paused_gc()`, внутренний
`gc.enable()` остаётся. Прототип (`test_unattended_mode.py:183`, `test_paths_section_ownership.py:89,133,135`):
`gc.collect()` → `gui_memory_policy().collect_now()`. Ещё: `test_lifetime_scope_acceptance.py`, `test_subscribers.py`,
`test_subscribers_acceptance.py`, `test_qt_lifetime_acceptance.py`.

## Acceptance criteria и инъекции

**A1** `process_module/tests/test_gc_collection_owner.py` — внутри `suspend_collection_owner()` (фикстура файла),
исполнитель-фейк пишет `start/stop`. **A2** `frontend_module/tests/test_qt_gc_policy.py` — сессионная политика, реальный
`qapp`. Всё, что может зависнуть, — daemon-поток, `join(5)`.

| # | Тест | Проверка (литералы) | Инъекция → красный |
|---|---|---|---|
| 1 | `test_collect_on_disables_and_release_restores_prior` | prior вкл.: `collect_on` → `isenabled() is False`, `release` → `True`; prior выкл. → `False` | `release` = `gc.enable()` |
| 2 | `test_same_executor_idempotent_other_rejected` | повтор `is` первый; другой → `RuntimeError`, `"уже владеет"` | замена владельца |
| 3 | `test_foreign_thread_calls_raise` | `collect()`, `release()` из daemon → `RuntimeError`, `"потока-владельца"` | без проверки потока |
| 4 | `test_enforce_heals_and_counts_once` | `gc.enable()`; `tick()` → `False`, `enabled_violations == 1`; ещё `tick()` → `1` | без `gc.disable()` |
| 5 | `test_tick_generation_aware` | порог `10**9` → `tick() == 0`, `collections == 0`; порог `1` + 100 циклов → `collections == 1`, вернул ≥ 100 | тик = `gc.collect()` |
| 6 | `test_scheduled_collect_yields_to_owner` | оба флага `FW_GC_*`=1, `freeze_after_startup()`; при владельце `collect_scheduled(100.0) is False`, после `release` `True` | без проверки слота |
| 7 | `test_observe_off_zero_cost_on_counts_foreign` | выкл.: `len(gc.callbacks)` как до, `max_pause_ms == 0.0`; вкл. → `+1`, `gc.collect()` в daemon → `foreign_collections == 1` | хук всегда |
| 8 | `test_paused_gc_restores_exact_state` | prior выкл. + внутри `gc.enable()` → `False`; prior вкл. → `True` | выход = `gc.enable()` |
| 9 | `test_freeze_deadline_and_rearm` | `freeze=True, freeze_after_s=0`: `tick()` → `get_freeze_count() > 0`; `rearm_freeze()` → `0`; `release` → `0` | `release` без `unfreeze` |
| 10 | `test_stats_dict_primitives` | ровно 13 ключей; значения `bool/int/float/str` | поле-объект |
| 11 | `test_suspend_requires_empty_slot` | `collect_on` в блоке без `release` → `RuntimeError`, `"оставил"` | выход без проверки |
| Q1 | `test_install_off_app_thread_raises` | из daemon → `RuntimeError`, `"только поток QCoreApplication"` | проверка после раннего возврата |
| Q2 | `test_timer_collects_qwidget_cycle_on_main` | `h.me = h; h.w = QWidget()`, `del h`, `qtbot.wait(2500)` → `destroyed` на главном | таймер не стартует |
| Q3 | `test_collect_now_flushes_outside_loop` | `attach_qt(root, o)`, `root.close()` в daemon, `collect_now()` → `isValid(o) is False` | без flush |
| Q4 | `test_collect_now_inside_loop_no_flush_no_error` | `collect_now()` из `singleShot(0)` в `qtbot.wait(200)` → без исключения | flush безусловно |
| Q5 | `test_worker_alloc_with_policy_survives_subprocess` | подпроцесс (`timeout=60`): 6 деревьев `QWidget`+`QTimer` в циклах, политика, поток аллоцирует 400 000 объектов, 2 тика → `returncode == 0` | без `gc.disable()` → AV (CTO 3/3) |

**A3 страж:** `test_gui_code_has_no_gc_calls` (R1), `test_tests_do_not_reenable_gc` (R2), `test_qt_tests_collect_through_policy`
(R3), `test_scanner_sees_synthetic_violation` (`"import gc\ngc.enable()\n"` → 1; не вакуумный), `test_allowlist_has_no_dead_entries`.

**A4 `scripts/gc_policy_acceptance.py`** (lead, не pytest): прогон — подпроцесс `python -X faulthandler -m pytest -q -p
no:cacheprovider …`, cwd `multiprocess_framework/modules`, `timeout` 900 с (гейт) / 300 с; падение — код ∉ {0, 1} или
`Fatal Python error`/`Windows fatal exception`; `--offscreen` → `QT_QPA_PLATFORM=offscreen`; печать
`SUMMARY <имя> crashes=X/N failed=Y gc_violations=Z platform=…`.

| Имя | Набор | Требование | Инъекция lead → ожидание |
|---|---|---|---|
| `chain` | `frontend_module/tests/test_base_tree_nav_tab.py`, `…/test_qt_event_bridge.py`, `event_module/tests/test_subscribers.py::test_release_from_gc_finalizer_under_publisher_lock_no_deadlock` (16) | 0/20 native, 0/20 offscreen | пустое тело `_gui_memory_boundary` → ≥ 1/20 (CTO 5/5) |
| `reverse` | `frontend_module/tests event_module/tests` | 0/5 native | то же → ≥ 1/5 (CTO 2/2) |
| `four` | первые два `chain` + `test_qt_lifetime.py::test_concurrent_attach_from_four_threads` | 0/20 native | `collect_on` без `gc.disable()` → ≥ 1/20 (CTO 5/5) |
| `gate` | `scripts/run_framework_tests.py` | 0/5 native, 0/2 offscreen, `enabled_violations=0` в каждом | — |

Плюс: время гейта ≤ 1.30 × базы (92fd0450f, та же машина; иначе — В2 к CTO); `foreign_collections` гейта — база
храповика. **Стенд** (`INSPECTOR_GUI_UNATTENDED=1`, 10 мин, `INSPECTOR_GC_OBSERVE=1`, `FW_GC_FREEZE` 0 и 1): `max_pause_ms`
≤ 50; RSS (Get-Process, не psutil) ≤ 1.15 × прогона с `INSPECTOR_GUI_GC_POLICY=0`. Превышение — цифры CTO, не ручки молча.

## Out of scope

Источники и храповик Qt-мусора — мегаплан GUI; Ф1–Ф6; ручка `observe` в `app.yaml`/`backend_ctl`; `ProcessModule`, heartbeat.

## Риски

- **Пауза главного потока:** тик ≈ каденции CPython; `gen2` — десятки мс (стенд). **RSS:** длинный слот — мусор копится.
- **Сторонний `gc.collect`/`gc.enable`** (site-packages, `pyqtgraph.GarbageCollector`) — R1 не видит; `enforce` лечит,
  `foreign_collections` показывает (при `observe`).
- **Граница теста:** полный `gc.collect()` (CTO: +35 мс/тест без заморозки) — порог 1.30. **PySide6** в каждом прогоне modules — ~1 с.
- **Free-threaded Python (3.13t+):** другая модель сборки — пересмотреть при переходе.

## Executor brief (GREEN)
```
TASK: T1 — политика памяти GUI-процесса   PLAN: plans/2026-10-03_lifecycle-owner-scope/plan.md
ROLE: teamlead
CHAIN: tester(RED, Brief A) -> you -> developer(Brief C) -> lead(injections) -> reviewer
DESIGN:
  gc_discipline.py: новые имена раздела «Ядро» по таблице слота и правилам потоков; GcDiscipline — только
  collect_scheduled и freeze_after_startup. Новый core/qt_gc_policy.py: QTimer(parent=app) + install/GuiMemoryPolicy,
  flush из qt_lifetime. Две conftest — «Точки включения» 2–3; app.py — одна строка. ProcessModule, heartbeat не трогать.
FILES:
  1. multiprocess_framework/modules/process_module/lifecycle/gc_discipline.py
  2. multiprocess_framework/modules/frontend_module/core/qt_gc_policy.py — новый
  3. multiprocess_framework/modules/conftest.py
  4. conftest.py (корень репо)
  5. multiprocess_prototype/frontend/app.py
  6. multiprocess_framework/modules/process_module/DECISIONS.md — ADR «Сборкой владеет поток-исполнитель»
  BRIEF-OVERRIDE: frontend_module/core/README.md, process_module/STATUS.md — только текст, после зелёного.
REDS (A1 = process_module/tests/test_gc_collection_owner.py, A2 = frontend_module/tests/test_qt_gc_policy.py):
  A1 — строки 1–7 таблицы приёмки; A2 — Q2, Q3, Q5.
TESTS: QT_QPA_PLATFORM=offscreen pytest -q --tb=short A1 A2 process_module/tests/test_gc_discipline.py
  frontend_module/tests/test_qt_lifetime.py
OUT OF SCOPE: источники Qt-мусора, ProcessModule, heartbeat, app.yaml-ручка, чужие тесты (Brief C).
TRAPS: хук gc.callbacks без лога/лока; release → prior; flush при loopLevel()==0; повторный install — тот же объект.
```
Brief A (tester): A1–A4, только эта спека. Brief C (developer): 10 файлов шага 3, BRIEF-OVERRIDE: один шаблон без логики.

## Вопросы на ревью спека

- **В1.** Корневой `conftest.py` (прототип/Services/Plugins) — в T1 или в мегаплан? **Рекомендация:** в T1: 814/2482
  тестов прототипа оставляют Qt-мусор; механизм тот же, правка — две фикстуры.
- **В2.** Граница теста — полный `gc.collect()` или по поколениям? **Рекомендация:** полный (только он доказан 0/5);
  гейт > 1.30 × базы — решение CTO по числам.
- **В3.** Заморозка в GUI — по `FW_GC_FREEZE` (дефолт выкл.) или всегда? **Рекомендация:** по флагу, как в бэкенде;
  стенд мерит оба.

## Для мегаплана GUI

- `apps/gui_client` (локально и на панели по Ethernet): `install_gui_memory_policy(app, log=…)` сразу после `QApplication`;
  от `ProcessModule` не зависит.
- `observe` — в секцию `observability` (`app.yaml`, hot-reload) и команду `backend_ctl`, с маршалом на главный поток;
  `stats()` — в телеметрию клиента.
- Храповик Qt-мусора на тест (`DEBUG_SAVEALL`) с базой из T1; правила: `QObject` создаётся и умирает на главном, без
  сильных циклов view↔presenter, `QTimer` с родителем, без лямбд на `destroyed`, без `QObject` в `QRunnable`.
