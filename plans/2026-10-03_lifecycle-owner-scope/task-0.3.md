# Task 0.3 — Subscribers в event_module

**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Refs:** [`DESIGN.md`](DESIGN.md) §2.1, §2.2, §2.5(а), §3, §4 D3, §6; [`task-0.2.md`](task-0.2.md); ADR-BM-008
**Зависит от:** 0.2. **Блокирует:** 0.5, 2.1, 3.1. **Ред. 3** — ревью спека р1, р2.
**Module contract:** event_module — new-lite; base_manager — public-api-change (`IScope.note_emits_after_close`, docstring `Reporter`).

## Goal

`event_module/subscribers.py` — один список подписчиков для всех издателей: `add(cb, *, owner: IScope) -> IHandle`,
`emit` по снимку вне лока, флаг `active`, `errors`, `emits_after_close` в отчёт владельца. `EventBus` не мигрирует (3.1).

## Files

| Файл | Что |
|---|---|
| `multiprocess_framework/modules/event_module/subscribers.py` | новый: `Subscribers` |
| `multiprocess_framework/modules/event_module/__init__.py` | реэкспорт `Subscribers` |
| `multiprocess_framework/modules/base_manager/interfaces.py` | `IScope.note_emits_after_close`; docstring `Reporter` — третий вид вызова |
| `multiprocess_framework/modules/base_manager/core/lifetime.py` | реализация `note`; `_Acc` суммирует счётчик |
| `multiprocess_framework/modules/event_module/tests/test_subscribers.py`, `multiprocess_framework/modules/base_manager/tests/test_lifetime_scope.py` | тесты автора |
| документы | `event_module/{README,STATUS}.md`; `event_module/DECISIONS.md` — EVT-003 (`Subscribers`; «leaf» → «зависит от `base_manager.interfaces`»); `base_manager/README.md` (строки `Reporter`, `IScope` :42); ADR-BM-008 «Канал счётчика (Task 0.3)» + `python -m scripts.sync`; `docs/MODULE_TIERS.md` |

Тестер — `event_module/tests/test_subscribers_acceptance.py` и `base_manager/tests/test_lifetime_note_acceptance.py`.

**Против plan.md:** (1) `event_module/interfaces.py` и `event_bus.py` не меняются (S15; `Subscribers` — деталь
издателя, DESIGN §2.2; `Subscription` — 3.1, D6). (2) Правка base_manager: в `IScope` нет канала к отчёту — В1.
(3) MODULE_TIERS: ярус `optional` прежний, меняется только текст; `test_module_tiers.py` текст не проверяет.

## Контракт реализации

### `Subscribers`
```python
from multiprocess_framework.modules.event_module import Subscribers

class Subscribers:
    def __init__(self, name: str) -> None
    def add(self, cb: Callable[..., object], *, owner: IScope) -> IHandle
    def emit(self, *args: object, **kwargs: object) -> int   # число доставок без исключения
    errors: tuple[tuple[str, str], ...]                       # property, первые 20 пар
    error_count: int                                          # property, все исключения подписчиков
    emits_after_close: int                                    # property, все отклонённые доставки
    def __len__(self) -> int                                  # подписки в хранилище
```
- Файл начинается с `from __future__ import annotations` (обязательно — S13), в docstring модуля строка `Purpose:`,
  в модуле `__all__ = ["Subscribers"]` (contract-lite, `scripts/pre_report_gate.py:181`).
- Импорты: stdlib и `base_manager.interfaces`; `base_manager.core.lifetime` — нет (G6).
- `name`: не `str` → `TypeError(f"Subscribers: name — ожидается str, получено {type(name).__name__}")`; пустая или с
  `/` → `ValueError("Subscribers: name — нужна непустая строка без '/'")` (значение в текст не идёт).
- `owner`: keyword-only, без умолчания, аннотация ровно `IScope` (эталон для G2 в 0.5).
- **Хранилище:** `dict[int, _Sub]` по `seq`, порядок вставки = порядок `add`. `_Sub` — `__slots__` (`seq`, `cb`,
  `owner_ref`, `active`, `path`), без `__eq__`. Удаление — только `dict.pop(seq, None)`; пересборки присваиванием нет.
  Причина (р1 п.6): gc-финализатор может войти в этот же поток посреди секции под `RLock` — удаление без Python-кода
  и без потери параллельной вставки.

### `add`
- `cb` не вызываемое → `TypeError(f"Subscribers '{name}': cb — ожидается вызываемое, получено {type(cb).__name__}")`.
- `owner` без метода `own` (включая `None`) или без поддержки `weakref` →
  `TypeError(f"Subscribers '{name}': owner — ожидается IScope, получено {type(owner).__name__}")`.
- `seq` — один `itertools.count(1)` на процесс (иначе два издателя с одним `name` заняли бы одно имя); имя записи
  `f"{name}#{seq}"`, путь ручки `f"{owner.path}/{name}#{seq}"`, `kind="subscription"`.
- Порядок: `_Sub(..., owner_ref=weakref.ref(owner), active=True)` (`weakref.ref` **без колбэка**) → `owner.own(_Release,
  …)` → под локом вставка, **только если `sub.active`** (владелец мог закрыться между `own` и вставкой).
- Владелец закрыт/закрывается → `own` освобождает `_Release` и бросает `ScopeClosedError`; `add` его пропускает.
  Возврат — ручка `owner.own`; издатель её не хранит.

### `_Release` — вызываемое в записи владельца
- Держит `weakref.ref(издатель)` и `_Sub`. Вызов: `sub.active = False`; издатель жив → под его локом
  `pop(sub.seq, None)`; отпустить `_Sub`. Не бросает, повтор — no-op. `cb` не обнуляется (снимок рассылки).
- После смерти издателя запись остаётся во владельце до его закрытия или `h.close()` — цена принята.

### `emit`
- Под локом `snapshot = tuple(store.values())`; доставка вне лока в порядке `add`. Для каждой подписки:
  1. `not sub.active` → не доставлять, под локом `pop(sub.seq, None)`; владелец мёртв или `owner.closed` → +1
     отклонённых, иначе (`h.close()` при открытом владельце) — без счёта.
  2. `sub.active`, но `owner_ref() is None` (владелец собран без `close`, G3) → не доставлять, +1, `pop`; одна строка
     `logging.warning` на первый такой случай у издателя.
  3. Иначе `cb(*args, **kwargs)`; `Exception` → пара `(sub.path, f"{type(e).__name__}: {e}")`, рассылка идёт дальше.
- Реентрантно (`emit`, `add`, `h.close()`, `owner.close()` из `cb`): добавленная в текущую рассылку не попадает,
  закрытая — в её остаток не попадает.
- Отклонённые копятся по владельцу; после цикла — **один** `owner.note_emits_after_close(n)` на живого владельца, вне
  лока (при закрытом корне каждый вызов — вызов reporter'а).
- **Окно чужого потока** (docstring класса и README, р1 п.7): после возврата `close()` владельца или `h.close()`
  подписчик может получить ещё одну рассылку, начатую другим потоком раньше. В одном потоке окна нет (S3, S6).

### Счётчики, лок
- `errors` — первые 20 пар, `error_count` — все, `emits_after_close` — все отклонённые; все три меняются **под локом
  издателя** (р1 п.8). `logging.warning` — вне лока, на первые 20 ошибок. Исключения подписчиков в отчёт владельца не
  идут: там ошибки закрытия (0.1, D3).
- Лок — `threading.RLock` (урок 0.2 р1: gc-финализатор на любом аллоцирующем потоке, в том числе внутри `with`). Под
  локом нет чужого кода (`cb`, `own`, `note`, `logging`). Чтение `active` без лока опирается на GIL (DESIGN §6).

### Канал — `IScope.note_emits_after_close(self, n: int) -> None`
- Без умолчания (`emit` всегда передаёт пакет). Docstring: «★5а. `n` доставок в эту область отклонены — она
  закрывается или закрыта. Не бросает из-за состояния, любой поток, ресурсов не зовёт.»
- `n`: `bool`/не `int` → `TypeError(f"note_emits_after_close: n — ожидается int, получено {type(n).__name__}")`;
  `n < 1` → `ValueError("note_emits_after_close: n — нужно int ≥ 1")`.
- Цель — первая область цепочки `self, self.parent, …` не в состоянии `closed` (открыта или закрывается): под её локом
  `+n` в `_extra` — в отчёт идущего или следующего `close`. Проверка состояния и прибавка — та же секция лока, что
  финальный блок `_close`.
- Вся цепочка закрыта → вне лока reporter получает **третий вид вызова** (р1 п.5): `CloseReport(path=self.path,
  elapsed_s=0.0, survivors=(), killed=(), errors=(), emits_after_close=n)` — признак: `elapsed_s == 0.0`, пустые
  списки, счётчик ≥ 1. Reporter'а нет → строка `logging.warning`. Docstring `Reporter` и ADR-BM-008 называют три вида:
  закрытие области, досрочное `IHandle.close`, «после закрытия цепочки», и правило: отчёт досрочно закрытой
  некорневой области несёт счётчик 0, счётчик — в отчёте родителя. Код выхода — по возврату `root.close()`.
- `_Acc.emits`; `merge` суммирует `emits_after_close`, `report()` передаёт.
- **Передача родителю (ревью р2, исправление «A»).** Область, закрытая **не** родителем и имеющая родителя, отдаёт
  накопленный счётчик вызовом `parent.note_emits_after_close(n)` — вне лока и **до** `_done.set()`; в её собственном
  отчёте `emits_after_close == 0`. Закрытая родителем — сливает счётчик в его отчёт, как сейчас. Корень держит счётчик
  в своём отчёте. Итог: возврат `root.close()` — полный счётчик при любом порядке. Цена: отчёт не говорит, от какого
  ребёнка счётчик (счётчик издателя остаётся). Поведение 0.2 не меняется.
- Выжившие/ошибки досрочно закрытого ребёнка — семантика 0.2 (см. «Для следующих спеков», 1.2). `ok` счётчик не учитывает.

## Steps
1. `interfaces.py` (`note`, docstring `Reporter`) → 2. `lifetime.py` (`_Acc.emits`, `note`; прочее поведение 0.2 не
   меняется) → 3. `subscribers.py`, `__init__.py`.
4. Тесты автора: `add` против `owner.close()` из другого потока, 200 итераций — неактивных в хранилище нет (инъекция
   «вставка без проверки `active`» → красный); `_Release` из gc-финализатора внутри `with` лока посреди `emit` — без
   дедлока и потери вставки; 8 потоков × 1000 `note` в ребёнка при `root.close()` — отчёт корня + отчёты третьего вида = 8000;
   гонка `c.close()`/`root.close()` × 100 — корень всегда 3 (инъекция «передача после `_done.set()`» → красный не каждый раз).
5. Документы; `python -m scripts.sync`. 6. `python scripts/validate.py`, тесты, ruff.

Блокирующее — в daemon-потоке с `join(timeout)`; зависание = провал с текстом. **Handoff:** tester (RED) → teamlead
(GREEN, ≤ 2 итерации, без push) → ведущий (инъекции, предсказание до прогона) → reviewer. **Gate:** `validate.py`,
тесты `event_module` + `base_manager` (число passed), ruff.

## Acceptance criteria и инъекции

Фикстура: `got = []`; `root = open_scope("root", budget_s=1.0, reporter=got.append)`; `pub = Subscribers("pub")`;
`calls = []`; подписчик `X` пишет `"X"` в `calls`. `G = [(r.path, r.emits_after_close) for r in got]`.

`event_module/tests/test_subscribers_acceptance.py`:

| # | Проверка | Инъекция → красный |
|---|---|---|
| S1 | `h = pub.add(A, owner=root)`: `h.kind == "subscription"`, `re.fullmatch(r"root/pub#\d+", h.path)`, `len(pub) == 1` | `kind` не передан |
| S2 | A, B, C на `root`: `pub.emit(1) == 3`, `calls == ["A", "B", "C"]` | обратный порядок |
| S3 | A закрывает `hB` в своём вызове: `emit() == 2`, `calls == ["A", "C"]`, `emits_after_close == 0`; следующий `emit` → ещё `"A", "C"`; `len(pub) == 2` | **убрать проверку `active`** → `["A", "B", "C"]` (из 0.2) |
| S4 | A добавляет D в своём вызове: текущий → `["A","B","C"]`, следующий добавляет `["A","B","C","D"]` | обход живого хранилища |
| S5 | Свежий `pub`; B бросает `ValueError("boom")`: `emit() == 2`, `calls == ["A", "C"]`, `errors == ((hB.path, "ValueError: boom"),)`, `error_count == 1`. Ещё 24 рассылки (всего 25) → `len(errors) == 20`, `error_count == 25` | убрать `try`; убрать потолок |
| S6 | `tab = root.child("tab")`; A на `root`, B на `tab`; A вызывает `tab.close()`: `calls == ["A"]`, `emits_after_close == 1`, `root.close().emits_after_close == 1`, `G == [("root/tab", 0), ("root", 1)]` | `emit` не зовёт `note` → `("root", 0)` |
| S7 | `x = open_scope("x", budget_s=1.0, reporter=got.append)`; A, B, C на `x`; A вызывает `x.close()`: `calls == ["A"]`, `emits_after_close == 2`, `G == [("x", 0), ("x", 2)]` | `note` на каждую подписку → `("x",1),("x",1)` |
| S8 | `pub.add(A)` → `TypeError`; `owner=None` → `TypeError`, в тексте `"owner"`; `pub.add(1, owner=root)` → `TypeError` | убрать проверку `owner` → `AttributeError` вместо `TypeError` |
| S9 | `root.close(); pub.add(A, owner=root)` → `ScopeClosedError`; `len(pub) == 0`; `emit() == 0`; `calls == []` | `add` глотает `ScopeClosedError` |
| S10 | `gc.disable()`; `h = pub.add(A, owner=root)`; `r = weakref.ref(pub)`; `del pub` → `r() is None` без `gc.collect()`; `h.close().ok is True` | `_Release` держит издателя сильно |
| S11 | Презентер ↔ `pub` (держит `pub`, `pub` — его метод), владелец `p = root.child("p")`; `gc.disable()`; `p.close()`; ссылки теста удалены → weakref презентера мёртв | `_Release` не убирает `sub` |
| S12 | `o = open_scope("o", budget_s=1.0)`; A на `o`; `ro = weakref.ref(o)`; `del o, h; gc.collect()`; `ro() is None`; `emit() == 0`, `calls == []`, `emits_after_close == 1`, `len(pub) == 0` (`"o"` останется `abandoned` в `unclosed_roots()`) | убрать ветку «`owner_ref() is None`» → `["A"]` |
| S13 | `p = inspect.signature(Subscribers.add).parameters["owner"]`: `p.kind is KEYWORD_ONLY`, `p.default is Parameter.empty`, `p.annotation in ("IScope", IScope)` | `owner: IScope \| None = None` |
| S14 | A, B, C на `root`. A при первом вызове ставит `a_in` и ждёт ≤ 2 с событие `e`. Поток добавления **стартует после `a_in`** и ставит `e` сразу после возврата из первого `pub.add`; затем 500 × (`h = pub.add(D, owner=root)`; `h.close()`), параллельно 4 потока × 500 `emit`: все вышли за 10 с, `e.wait` вернул `True`, исключений нет, `len(pub) == 3` | `cb` под локом → `add` ждёт лок, `e.wait` → `False` (проба ревьюера: 2.08 с) |
| S15 | `git diff --exit-code <коммит спека> HEAD -- multiprocess_framework/modules/event_module/event_bus.py multiprocess_framework/modules/event_module/interfaces.py` → код 0; `event_module/tests/test_event_bus.py` зелёный без правок | правка `EventBus` в 0.3 |

`base_manager/tests/test_lifetime_note_acceptance.py`:

| # | Проверка | Инъекция → красный |
|---|---|---|
| N1 | `c = root.child("c")`; `c.note_emits_after_close(2)`; `root.close().emits_after_close == 2` | `_Acc.merge` не суммирует → 0 |
| N2 | `c.close()`; `c.note_emits_after_close(3)`: отчёт `c` в `got` — 0; `root.close().emits_after_close == 3` | цель — сама закрытая область → 0 |
| N3 | `root.close(); root.note_emits_after_close(1)`: последний в `got` — `path "root"`, `emits_after_close 1`, `elapsed_s 0.0`, `survivors == killed == errors == ()`, `ok True`. Без reporter'а — `caplog` со строкой, где есть `"root"` | молчаливый возврат |
| N4 | `note(0)` → `ValueError`; `note(True)`, `note(1.0)` → `TypeError` | убрать проверку `bool` |
| N5 | Три порядка, свежий `root` с reporter'ом, `c = root.child("c")`, `c.note_emits_after_close(3)`. **child_first:** `c.close(); root.close()`. **root_first:** `root.close()`. **overlap:** `c` владеет вызываемым, которое ставит `inside` и ждёт `go`; T2 (daemon) — `c.close()`; после `inside` T1 (daemon) — `root.close()`; дождаться, пока `root.live()` покажет `{"path": "root/c", "state": "stopping"}` (запись с этими ключами), затем `go.set()`; `join(5)` обоих. В каждом: `root.close()` вернул `emits_after_close == 3`; отчёт `root/c` в `got`, если есть, — `0` | нет передачи родителю → child_first: корень `0` |

## Out of scope
`EventBus`, `ActionBus`, SRM, `Subscription` — 3.1; другие издатели — Ф2/Ф3; стражи — 0.5.

## Executor brief (GREEN)
```
TASK: 0.3 — Subscribers и канал emits_after_close   PLAN: plans/2026-10-03_lifecycle-owner-scope/plan.md
ROLE: teamlead
CHAIN: tester(RED) -> you -> lead(injections) -> reviewer
DESIGN:
  Новый event_module/subscribers.py: Subscribers(name), dict[seq -> _Sub(__slots__)] под RLock, удаление pop(seq).
  add: owner.own(_Release, name=f"{name}#{seq}", kind="subscription"), затем вставка, если active. emit: снимок под
  локом, доставка вне лока по active, один owner.note_emits_after_close(n) на владельца после цикла.
  base_manager: IScope.note_emits_after_close(n) + docstring Reporter (interfaces.py); lifetime.py — note, _Acc.emits;
  область, закрытая не родителем, отдаёт счётчик parent.note_emits_after_close(n) вне лока до _done.set().
  Прочее поведение lifetime.py, event_bus.py, event_module/interfaces.py не менять. Детали — «Контракт реализации».
FILES:
  1. multiprocess_framework/modules/event_module/subscribers.py — новый
  2. multiprocess_framework/modules/event_module/__init__.py — реэкспорт
  3. multiprocess_framework/modules/base_manager/interfaces.py — note + docstring Reporter
  4. multiprocess_framework/modules/base_manager/core/lifetime.py — note + _Acc.emits
  5. multiprocess_framework/modules/event_module/tests/test_subscribers.py — опасности (Steps 4)
  6. multiprocess_framework/modules/base_manager/tests/test_lifetime_scope.py — канал
  BRIEF-OVERRIDE: документы (multiprocess_framework/modules/event_module/{README,STATUS,DECISIONS}.md,
  multiprocess_framework/modules/base_manager/{README,DECISIONS}.md, multiprocess_framework/docs/MODULE_TIERS.md)
  — тот же исполнитель после зелёного, только текст.
REDS:
  multiprocess_framework/modules/event_module/tests/test_subscribers_acceptance.py::
    test_add_returns_subscription_handle, test_emit_delivers_in_add_order, test_reentrant_unsubscribe_skips_closed,
    test_subscriber_exception_isolated_and_counted, test_closed_child_owner_counted_in_root_report,
    test_owner_closed_inside_emit_one_note_per_owner, test_add_to_closed_owner_raises_not_listed,
    test_handle_does_not_keep_publisher_alive
  multiprocess_framework/modules/base_manager/tests/test_lifetime_note_acceptance.py::
    test_note_from_closed_child_reaches_parent_report, test_root_report_counts_child_notes_under_close_race
TESTS: pytest -q --tb=short multiprocess_framework/modules/event_module multiprocess_framework/modules/base_manager
OUT OF SCOPE: event_bus.py, event_module/interfaces.py, издатели вне event_module.
TRAPS: RLock; под локом нет чужого кода; вставка после own и при active; только dict.pop(seq), без пересборки;
  weakref.ref(owner) без колбэка; счётчики под локом.
```

## Вопросы на ревью спека
В1 (канал — `IScope.note_emits_after_close`) и В2 (собранный владелец не получает доставку, она считается) приняты в р1–р2.

## Для следующих спеков
- **0.5:** G2 — эталон `owner` в `Subscribers.add`.
- **1.2:** счётчик полон в `root.close()`, у досрочно закрытой некорневой области — 0. Выжившие/ошибки такого ребёнка
  (0.2): «ребёнок первым» — нет в отчёте корня, перекрытие — дважды у reporter'а. Отчёты третьего вида — в `emergency_log`.
- **2.1:** издатель короче владельца оставляет no-op запись во владельце — решить `Subscribers.close()`.
