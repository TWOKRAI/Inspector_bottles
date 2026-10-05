# Task 0.4 — qt_lifetime в frontend_module

**Ред. 3 — ревью спека р1–р2 + вердикт CTO.**
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Refs:** [`plan.md`](plan.md) 0.4; [`DESIGN.md`](DESIGN.md) §2.2 («Связь с Qt»), §2.4, §3 G5/G6, §6; [`task-0.2.md`](task-0.2.md); ADR-BM-008
**Зависит от:** 0.2. **Блокирует:** 0.5 (G5, G6), 2.2, 5.1.
**Module contract:** new-lite (`core/qt_lifetime.py`) + реэкспорт в `frontend_module/interfaces.py` (public-api-change).

## Goal

`attach_qt` (область ↔ QObject), `flush_deferred_deletes` (без цикла событий), `QThreadHandle` (`Stoppable` над
`QThread`). Потребители не мигрируют.

## Контракт реализации

```python
from multiprocess_framework.modules.frontend_module.interfaces import (
    attach_qt, flush_deferred_deletes, QThreadHandle, QtTreeMismatch)

def attach_qt(scope: IScope, obj: QObject, *, name: str | None = None) -> IHandle
def flush_deferred_deletes() -> None
class QtTreeMismatch(RuntimeError): ...
class QThreadHandle:                        # Stoppable (base_manager.interfaces)
    def __init__(self, thread: QThread, *, stop: Callable[[], None] | None = None) -> None
    def request_stop(self) -> None
    def join_until(self, deadline: float) -> bool
    def close(self) -> None
```
- Импорты: stdlib, `shiboken6`, Qt-имена — из `core/qt_imports` (+`QCoreApplication`, +`QDeadlineTimer`), `base_manager.interfaces`. Импорт `base_manager.core.lifetime` запрещён (G6).
- `qt_lifetime.py` — единственное место `.deleteLater(` в новом коде (G6). Docstring lite: `Purpose / Public API /
  Stability: lite`.

### Реестр области (правило C, вердикт CTO)
- `_reg: weakref.WeakKeyDictionary[IScope, set[int]]` — C++ адреса всех живых объектов, привязанных к области.
  Добавление — в `attach_qt`; удаление — **только** в `_on_destroyed`, после `scope.close()` (не в `_QtRelease`).
  Порядок привязки не важен, `anchor` нет. **Ревью р1:** реестр — `dict[id(scope), set[int]]`, запись снимает `weakref.finalize(scope, _reg.pop, id, None)`; чтение и запись — по одному вызову C-уровня без лока (атомарны под GIL); цепочка предков собирается до снимка. Лок `threading.RLock` — только вокруг `_posted`, без вызовов: точка gc под локом закрыла бы чужую область под ним.

### `attach_qt` — порядок обязателен
1. Проверки: `obj` не `QObject` → `TypeError(f"attach_qt: ожидается QObject, получено {type(obj).__name__}")`;
   `shiboken6.isValid(obj) is False` → `ValueError("attach_qt: Qt-объект уже удалён")`;
   `QCoreApplication.instance() is None` → `RuntimeError("attach_qt: нет QCoreApplication — deleteLater некому
   доставить")`; поток: `th = obj.thread()`, допустим только `th == app.thread() or not th.isFinished()`, иначе
   `ValueError(f"attach_qt: поток объекта не работает ({type(obj).__name__}) — deleteLater не будет доставлен")`.
   Причина: объект завершённого потока после `deleteLater` + flush жив навсегда (проба f2). Живой адаптированный
   поток допустим (удаление при выходе, f4); не запущенный `QThread` — тоже (`moveToThread` до `start()`, нужно Ф5).
2. Имя: `name` или `f"{type(obj).__name__}#{n}"`, `n` из одного `itertools.count(1)` на процесс. `kind="qobject"`.
3. `scope.own(_QtRelease(_Att(obj, scope_ref, destroyed=False)), name=…, kind="qobject")`. Закрытая область →
   `own` сразу освобождает (`deleteLater`) и бросает `ScopeClosedError`; имя занято → `ValueError` (0.2). Наружу.
4. `addr = getCppPointer(obj)[0]`; под локом `_reg.setdefault(scope, set()).add(addr)`.
5. `obj.destroyed.connect(functools.partial(_on_destroyed, weakref.ref(att), weakref.ref(scope), addr))`.
- Причина: при `ScopeClosedError`/`ValueError` нет ни записи в реестре, ни подключения.
- **Обработчик не держит `obj`** (ни замыкание, ни связанный метод): связь живёт в C++, gc её не видит — обёртка
  бессмертна (Q2b).

### `_on_destroyed(att_ref, scope_ref, addr, *args)` — функция модуля
1. `att = att_ref()`; жив → `att.destroyed = True` (флаг: `_QtRelease` его пропустит).
2. `scope = scope_ref()`; `None` → вернуть.
3. `att is None` (освобождён нами) или `scope.closed` (истинно с начала `close`) → `close` не звать: повторный
   `close` ждёт первого до срока — flush висит (проба freeze: 0.704 с); на `QThread` — нарушение ADR-BM-008.
4. Иначе `scope.close()` синхронно (DESIGN §2.4: Qt удалил объект первым — область без него не нужна).
5. В конце, во всех ветках с живой `scope`: под локом `_reg.get(scope, set()).discard(addr)` — после `close` шага 4.
- `Exception` внутри → строка `logging.warning`, наружу не идёт.

### `_QtRelease` — фаза 2 области, на потоке закрывающего (любом)
1. `obj = att.obj; att.obj = None`. `obj is None`, `att.destroyed` или `not shiboken6.isValid(obj)` → вернуть.
2. Проверка Qt-предка (ниже) — вычислить, не бросать.
3. `th = obj.thread()`; `th != app.thread() and th.isFinished()` → запомнить ошибку потока.
4. `obj.deleteLater()` — **до** потери последней ссылки: он передаёт владение C++ (DESIGN §2.4); раньше потерянная
   ссылка удалила бы объект синхронно на чужом потоке. `_posted += 1` (под локом). `del obj`.
5. Несовпадение → `raise QtTreeMismatch(...)`; ошибка потока → `raise RuntimeError(f"qt-thread finished: {type} —
   поток объекта не работает, объект не будет удалён")`. Область пишет пару в `errors` (0.2) — утечка не молчит.
- Реестр не трогается. Синхронного `delete` нет (крах внутри сигнала, DESIGN §2.4).

### Проверка Qt-предка («qt-tree mismatch»), правило C
- Только когда `QThread.currentThread() == obj.thread()`; иначе проверки нет (**best-effort**, см. «Риски»).
- `me = addr(obj)`; под локом снимок: `above = ∪ _reg[s]` по строгим предкам (`scope.parent, …`);
  `owned = above ∪ (_reg[scope] − {me})`. Вызовы Qt — вне лока.
- `above` пусто → проверки нет (правило миграции: выше никто ничего не привязал).
- `obj.parent() is None` → совпадение (верхний объект; так у каждого `QTimer()` без родителя).
- Иначе цепочка `obj.parent()` до верха содержит адрес из `owned` → совпадение; нет → несовпадение. Текст:
  `f"qt-tree mismatch: {type(obj).__name__} — Qt-родитель вне объектов области '{scope.path}' и её предков"`
  (без `objectName` — вводное значение; объект называет путь `errors[0][0]`).

### `flush_deferred_deletes`
- Pre (ревью р1): не из цикла событий — `QThread.currentThread().loopLevel() > 0` → `RuntimeError` (удаление отправителя посреди сигнала).
- Нет `QCoreApplication` → возврат. Поток не `app.thread()` → `RuntimeError(f"flush_deferred_deletes: только поток
  QCoreApplication, вызван из {threading.current_thread().name}")` (с чужого потока — молча только свои объекты).
- Цикл: `before = _posted`; `sendPostedEvents(None, QEvent.Type.DeferredDelete)`; `_posted == before` → стоп.
  Предел 16 проходов, исчерпан → `logging.warning`. Причина: удаление `a` закрывает область, её `_QtRelease` ставит
  `b.deleteLater()` — один проход его не берёт (Q15). Только `DeferredDelete`: таймеры и сигналы не доставляются.

### `QThreadHandle`
- `thread` не `QThread` или `stop` не `None` и не вызываемое → `TypeError`. Ручка держит `QThread` до подтверждённой
  остановки.
- `request_stop()`: `requestInterruption()`; `quit()`; `stop()` — **один раз** за жизнь ручки. Не блокирует, любой
  поток, идемпотентно. Исключение `stop()` — область пишет в `errors`.
- `join_until(deadline)`: обёртка мертва или поток не запущен → `True`; из самого `QThread` → `isFinished()` без
  ожидания; иначе `bool(thread.wait(QDeadlineTimer(ms)))`, `ms = max(0, ceil((deadline − monotonic()) × 1000))`.
- `kill` **нет** (`terminate()` запрещён G6): не остановившийся `QThread` — выживший, объект не удаляется (нет abort
  «Destroyed while thread is still running»). Закрытие своей области изнутри `run` → `join_until` `False` (проба g5:
  0.031 с) → выживший `"r/qt"` **без** `" (self)"`: суффикс только у `spawn`-потоков (0.2).
- `close()` (после остановки): `deleteLater()` и `_posted += 1` **только** если обёртка жива и `isFinished()`; иначе (работает или запущен после закрытия) — объект остаётся прежнему владельцу, одна строка `logging.warning` (удаление работающего `QThread` — abort, ревью р1). Ссылка отпускается; повтор — no-op.

Всё, кроме flush, вызываемо с любого потока; объект удаляется на своём потоке.

## Риски
- **TOCTOU:** поток объекта может удалить его между `isValid` и `parent()` → `parent()` только на `obj.thread()`;
  окно `isValid` → `deleteLater` с чужого потока — принятый риск.
- **Best-effort:** `close` с чужого потока при настоящем несовпадении → `errors == ()` (CTO S9).
- **Фриз** `close` в `destroyed` — до `budget_s`. **Abort** при выходе до `os._exit` (Ф1) — см. 1.2.

## Steps
1. `qt_imports.py` (+2 имени); `qt_lifetime.py`; реэкспорт в `interfaces.py` (`__all__` +4, образец `app_identity`).
2. Тесты автора: 200 `attach_qt` в одну область из 4 потоков (объекты созданы на главном), `close` + flush — все
   мертвы, `errors == ()`; строки «T».
3. `core/README.md`, `DECISIONS.md` — «Владение Qt-объектами (Task 0.4)»; `STATUS.md` — строка.
4. `python scripts/validate.py`; тесты `test_qt_lifetime*.py`; ruff.

**Правила тестов (обоим наборам):**
- До импорта PySide6: `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`; только `QObject`/`QThread`;
  `app = QApplication.instance() or QApplication([])`.
- Импорт `qt_lifetime`/`interfaces` — **внутри каждого теста**: до GREEN — N failed, не одна ошибка сбора.
- Что может зависнуть (`close` с потоком, `wait`) — в daemon-потоке с `join(timeout)`; зависание = провал с текстом.
- `app.exec()`, крах, брошенный корень — только в подпроцессе (`subprocess.run(..., timeout=60)`, offscreen в env).
- Teardown: закрыть **все** корни теста, затем `flush_deferred_deletes()`. pytest-qt `processEvents` отложенные
  удаления не выполняет — teardown-flush единственный, кто удаляет. `unclosed_roots()` — на весь процесс,
  `"abandoned"` не сбрасывается: незакрытый корень портит соседям.

**Handoff:** tester (RED, на коммите спека) → teamlead (GREEN, ≤ 2 итерации, коммит, без push) → ведущий (инъекции
против обоих наборов, предсказание до прогона) → reviewer.
**Gate:** `validate.py`; тесты `frontend_module/tests/test_qt_lifetime*.py` (число passed); ruff.

## Acceptance criteria и инъекции

Фикстура: `got = []`; `root = open_scope("root", budget_s=1.0, reporter=got.append)`; `tab = root.child("tab")`;
`comp = tab.child("comp")`; `main = threading.get_ident()`; слот `on_destroyed` пишет `threading.get_ident()` в
`dthreads`. Всё на главном потоке, если не сказано иное. **R** — тестер (`test_qt_lifetime_acceptance.py`, = REDS);
**T** — автор (`test_qt_lifetime.py`).

| # | Тест | Проверка (литералы) | Инъекция → красный |
|---|---|---|---|
| Q1 T | `test_attach_returns_qobject_handle` | `attach_qt(root, QObject())`: `h.kind == "qobject"`, `re.fullmatch(r"root/QObject#\d+", h.path)`; `name="w"` → `"root/w"` | `kind` не передан |
| Q2 R | `test_close_from_worker_destroys_on_main_after_flush` | Объект без родителя, тест держит только `r = weakref.ref(obj)`; `gc.disable()`; `root.close()` в daemon, `join(5)`: `ok`; до flush `dthreads == []`; после — `[main]`, `r() is None` | `del obj` до `deleteLater` → `dthreads != [main]` |
| Q2b R | `test_abandoned_root_frees_qobject_subprocess` | Подпроцесс: `rt = open_scope("ab", budget_s=1.0)`; `attach_qt(rt, o)`; `r = weakref.ref(o)`; `del o, rt`; `gc.collect()` → печать `dead=True` | обработчик `destroyed` — `lambda: obj` → `dead=False` |
| Q3 R | `test_close_transfers_ownership_to_cpp` | Тест держит `obj`: до привязки `ownedByPython(obj) is True`; после `root.close()` — `False`, `isValid True`; после flush `isValid False` | без `deleteLater` → после flush `True` |
| Q4 R | `test_flush_after_exec_in_subprocess` | `singleShot(0, app.quit)`, страховка `singleShot(3000, …)`, `app.exec()`; затем `attach_qt` + `close` + flush; печать `before=True after=False`; `returncode == 0` | flush — no-op → `after=True` |
| Q5 R | `test_qt_deletes_first_closes_scope` | `c = QObject(p)`; `attach_qt(tab, c)`; `p.deleteLater()`; flush → `tab.closed is True`; `[(r.path, r.ok) for r in got] == [("root/tab", True)]` | `destroyed` не подключён → `False` |
| Q6 R | `test_qt_tree_mismatch_unowned_parent` (S4) | `attach_qt(tab, t)`; `f` не привязан; `c = QObject(f)`, `attach_qt(comp, c, name="c")`; `rep = comp.close()`: `ok False`, `len(errors) == 1`, `errors[0][0] == "root/tab/comp/c"`, `"qt-tree mismatch" in errors[0][1]`; после flush `isValid(c) is False` | без проверки → `errors == ()` |
| Q7 T | `test_parentless_and_owned_parent_no_mismatch` | Как Q6, но `c2 = QObject(t)`, `c3` без родителя в `comp` → `errors == ()` | «нет родителя» = несовпадение → 1 пара |
| S1 T | `test_parentless_timer_attached_first_no_mismatch` | В `tab` первым `timer` (без родителя), затем `w`; `c = QObject(w)` в `comp` → `errors == ()` | только первый привязанный → 1 пара |
| S2 R | `test_qt_deleted_cascade_no_errors` | `attach_qt(root, W)`, `attach_qt(tab, t)`; `c = QObject(t)` в `comp`, `del c`; `t.deleteLater(); del t`; flush → `[(r.path, r.ok) for r in got] == [("root/tab", True)]`, `got[0].errors == ()` | адрес убирать до `close` в `_on_destroyed` → пара `root/tab/comp/c` |
| S7 T | `test_child_scope_before_object_no_mismatch` | `attach_qt(root, W)`; `tab2 = root.child("tab2")`; `comp2 = tab2.child("comp")` (до объекта); `t` в `tab2`; `c = QObject(t)` в `comp2`; `tab2.close()` → `errors == ()`. (без `W` инъекция скрыта правилом «предки пусты») | адрес убирать в `_QtRelease` → `[("root/tab2/comp/c", "QtTreeMismatch: qt-tree mismatch…")]` |
| S3 R | `test_qt_tree_mismatch_sibling_scope` | `attach_qt(tab, t)`; `attach_qt(root.child("other"), f)`; `c = QObject(f)` в `comp`; `comp.close()`: `ok False`, `errors[0][0] == "root/tab/comp/c"`; `isValid(c)` до flush `True`, после `False` | `owned` = все области процесса → `()` |
| S6 T | `test_second_toplevel_no_mismatch` | В `tab`: `t` и `dock`; `c = QObject(dock)` в `comp` → `errors == ()` | только первый привязанный → 1 пара |
| S8 R | `test_qt_tree_mismatch_descendant_inversion` | `attach_qt(root, W)`, `attach_qt(comp, w)`; `c = QObject(w)`, `attach_qt(tab, c, name="c")`; `tab.close()`: `ok False`, `errors[0][0] == "root/tab/c"` | `owned` с потомками → `()` |
| S9 T | `test_offthread_close_skips_tree_check` | Фикстура Q6; `comp.close()` в daemon → `errors == ()` (best-effort) | без условия потока → 1 пара |
| S10 T | `test_own_dialog_helper_no_mismatch` | `attach_qt(tab, t)`; в `comp`: `dlg` и `c = QObject(dlg)` → `errors == ()` | `owned` без своей области → 1 пара |
| Q8 T | `test_attach_to_closed_scope_deletes_and_raises` | `root.close(); attach_qt(root, obj)` → `ScopeClosedError`; после flush `isValid False` | бросить до `own` → жив |
| Q9 T | `test_bad_args_and_flush_thread` | `attach_qt(root, object())` → `TypeError`; flush из daemon → `RuntimeError` с `"flush_deferred_deletes"` | без проверки потока → нет исключения |
| Q10 T | `test_qthread_cooperative_stop` | `run` до `isInterruptionRequested()` (шаг 10 мс); `root.own(QThreadHandle(t), name="qt", kind="qthread")`, `t.start()`; `root.close()` (daemon) ≤ 1.0 с, `ok`, `t.isFinished()` | без `requestInterruption` → выживший |
| Q11 R | `test_qthread_stuck_is_survivor_within_budget` | `run` ждёт `Event` до 10 с; `r = open_scope("r", budget_s=0.3)`: `close()` ≤ 0.6 с, `survivors == ("r/qt",)`, `killed == ()`, `errors == ()`; затем событие, `t.wait(5000)` | `join_until` без срока → `join(5)` истёк; `terminate` → `killed` не пуст |
| Q12 T | `test_stop_called_once` | `r = open_scope("r", budget_s=0.3)`; `t = QThread()` **не запущен**; `h = QThreadHandle(t, stop=f)`, `r.own(h, name="qt", kind="qthread")`; `h.request_stop()` дважды → `f` 1 раз; `r.close()` → `ok` | `stop()` на каждый вызов → 2 |
| Q13 T | `test_reexport_identity` | `interfaces.X is qt_lifetime.X` для четырёх имён | реэкспорт копией |
| Q14 T | `test_flush_during_foreign_close_returns_fast` | `rr = open_scope("rr", budget_s=2.0)`; `p = QObject(); o = QObject(p)`; `attach_qt(rr, o)`, затем `rr.own(Slow…)` (`join_until` спит 0.8 с); `rr.close()` в daemon; через 0.1 с `p.deleteLater()` и flush → < 0.1 с (проба 0.000) | без проверки `scope.closed` → ≈ 0.7 с (проба 0.703) |
| Q15 T | `test_flush_drains_cascaded_deletes` | `tab`: `a`, `b`, тест держит `rb = weakref.ref(b)`; `a.deleteLater()`; **один** flush → `rb() is None` | один проход → жив |
| Q16 T | `test_name_taken_leaves_no_connection` | `attach_qt(root, a, name="w")`; `attach_qt(root, b, name="w")` → `ValueError`; `c = QObject(b)`, `attach_qt(comp, c)`; `comp.close()` → ровно 1 пара `qt-tree mismatch` | реестр до `own` → `errors == ()` |
| Q17 T | `test_attach_finished_thread_raises` | Объект создан в Python-потоке, поток завершён → `ValueError` | без проверки → нет исключения |
| Q17b T | `test_attach_not_started_qthread_accepted` | `o.moveToThread(QThread())` (не запущен) → `attach_qt` без исключения | правило `isRunning()` → `ValueError` |
| Q18 T | `test_qthread_self_close_survivor` | Подпроцесс: `r = open_scope("r", budget_s=0.3)`; `run` зовёт `r.close()`, кладёт отчёт в список; ручка `name="qt"` → `survivors == ("r/qt",)`; до любого flush `t.wait(5000) is True` (иначе под инъекцией возможен abort) | из самого `QThread` вернуть `True` → `()` |

## Out of scope
- Миграция потребителей (`ThreadManager`, `bindings.py:266`, `QTimer()`, старые `deleteLater`) — Ф2/Ф5; G5/G6 — 0.5.

## Executor brief (GREEN)
```
TASK: 0.4 — qt_lifetime: attach_qt, flush_deferred_deletes, QThreadHandle   PLAN: plans/2026-10-03_lifecycle-owner-scope/plan.md
ROLE: teamlead
CHAIN: tester(RED) -> you -> lead(injections) -> reviewer
DESIGN:
  Новый core/qt_lifetime.py по разделу «Контракт реализации» (порядок шагов attach_qt, _on_destroyed, _QtRelease
  обязателен). Реестр scope -> set(C++ адрес), правило C; чистит только _on_destroyed после close. flush — цикл
  по счётчику _posted. QThreadHandle — Stoppable без kill. qt_imports: +QCoreApplication, +QDeadlineTimer.
  base_manager не менять.
FILES:
  1. multiprocess_framework/modules/frontend_module/core/qt_lifetime.py — новый
  2. multiprocess_framework/modules/frontend_module/interfaces.py — реэкспорт 4 имён
  3. multiprocess_framework/modules/frontend_module/core/qt_imports.py — +2 имени
  4. multiprocess_framework/modules/frontend_module/tests/test_qt_lifetime.py — опасности + набор T
  5. multiprocess_framework/modules/frontend_module/core/README.md — раздел
  6. multiprocess_framework/modules/frontend_module/DECISIONS.md — раздел «Владение Qt-объектами»
  BRIEF-OVERRIDE: multiprocess_framework/modules/frontend_module/STATUS.md — одна строка 0.4, только текст, тот же
  исполнитель после зелёного.
REDS (multiprocess_framework/modules/frontend_module/tests/test_qt_lifetime_acceptance.py):
  ::test_close_from_worker_destroys_on_main_after_flush  ::test_abandoned_root_frees_qobject_subprocess
  ::test_close_transfers_ownership_to_cpp  ::test_flush_after_exec_in_subprocess
  ::test_qt_deletes_first_closes_scope  ::test_qt_tree_mismatch_unowned_parent
  ::test_qt_deleted_cascade_no_errors  ::test_qt_tree_mismatch_sibling_scope
  ::test_qt_tree_mismatch_descendant_inversion  ::test_qthread_stuck_is_survivor_within_budget
TESTS: QT_QPA_PLATFORM=offscreen pytest -q --tb=short multiprocess_framework/modules/frontend_module/tests/test_qt_lifetime.py multiprocess_framework/modules/frontend_module/tests/test_qt_lifetime_acceptance.py
OUT OF SCOPE: ThreadManager, bindings.py, существующие deleteLater, QTimer без родителя, base_manager.
TRAPS: deleteLater до потери ссылки; destroyed без obj; реестр чистит только _on_destroyed; без close при scope.closed; exec() — в подпроцессе; Qt не под локом.
```

**Ревью р1:** В1 → правило C; В2 — `close` в `destroyed` синхронно с защитой, `singleShot` отклонён (нет цикла);
В3 — без `kill`.

## Для следующих спеков
- **0.5:** G6 — `.deleteLater(` только в `qt_lifetime.py`, старые — allowlist. G5 — `ownedByPython` ложь после
  `close` (Q3). G4 — код в `QThread` виден в `threading.enumerate()` как `Dummy-N` без пути области.
- **1.2:** `QThread`, закрывший свою область изнутри, — выживший без `" (self)"` (Q18): решить, ведёт ли он к
  `os._exit`. Без `os._exit` выход с работающим `QThread` в области — возможен abort.
- **5.1:** `QThreadHandle` регистрировать ДО привязки объектов этого потока: иначе LIFO останавливает поток первым
  (worker_first → `ok False`, `[("rr/w", "RuntimeError: qt-thread finish…")]`, объект жив; handle_first → `ok True`).
- **2.2 / 5.1:** привязывать каждый свой `QObject` без Qt-родителя (порядок неважен). GUI-области закрывать на
  GUI-потоке, иначе проверка дерева пропущена (S9) и G5-провал не виден. Измерить фриз `close` в `destroyed`.

## Открыто
- Предел flush 16 проходов не проверен на глубоком каскаде.
- `deleteLater` старого кода (allowlist G6) не виден счётчику `_posted`: flush не повторит проход ради него.
