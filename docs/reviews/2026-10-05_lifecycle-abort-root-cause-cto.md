# Abort гейта на Windows: корень и вердикт CTO (2026-10-05)

План: [`lifecycle-owner-scope`](../../plans/2026-10-03_lifecycle-owner-scope/plan.md), раздел «Перестройка 2026-10-05».
Сессия ведущего: aab3cfb2; артефакты прогонов — в её scratchpad (`cto_probe/`, `logs/*.native`, `inv_abort/`),
плюс `C:/Users/INNOTECH/AppData/Local/Temp/inv_diag/` (не в репо).

## Механизм (воспроизведено, вход → выход)

Python-владеемые Qt-объекты (`QWidget`, `QTimer` без родителя) попадают в циклы ссылок; циклический сборщик
мусора срабатывает на **не-главном** потоке и разрушает их там. Автосборка запускается на любом потоке, который
аллоцирует память (роутер, логгер, `QRunnable`, тестовые потоки), — явный `gc.collect()` не нужен.

| Проба | Результат |
|---|---|
| 6 деревьев QWidget + QTimer в цикле, 60 мс цикла событий, `gc.collect()` на главном | 3/3 выжил |
| то же, `gc.collect()` в потоке | 3/3 access violation |
| то же, поток только аллоцирует (gc включён) | 3/3 access violation (падение при выходе ОС-потока) |
| то же, `gc.disable()` + QTimer 20 мс на главном: collect + `sendPostedEvents(DeferredDelete)` | 3/3 выжил |
| pytest `test_base_tree_nav_tab` → `test_qt_event_bridge` → тест со сборкой в потоке | 5/5 abort; offscreen 3/3 |
| то же с плагином политики (gc off, collect на главном, flush после теста) | **0/5**, 16 passed |
| `frontend_module` + `event_module` (обратный гейту порядок) | 2/2 abort; с политикой 0/2, 678 passed (+35 мс/тест) |
| `test_concurrent_attach_from_four_threads` (0.4) после tree_nav + event_bridge | 5/5 abort; `gc.callbacks`: сборка gen1 на `Thread-4 (worker)` → segfault. Сам 0/20 — тот же механизм, не дефект `qt_lifetime` |
| полный гейт `main` 53b8c94fc, 5 прогонов | 0/5 (частота «1 из 4» сегодня не воспроизведена) |
| подмножество `frontend_module/tests` + `logger_module/tests/test_console_backpressure.py` | ~70% abort; в дампе h03 сборка шла на `router_module/core/_receiver.py:136 _worker` |

Нативные стеки (символы по экспортам, без PDB — имена приблизительные):
- рабочий поток: `subtype_dealloc → SbkDeallocWrapper → QWidget::~QWidget → QObjectPrivate::deleteChildren → QWidget::destroy → rip=мусор`;
- главный поток: `abort ← _purecall ← ~QObject (Qt6Core) ← QtWidgets.pyd ← Shiboken::BindingManager::runDeletionInMainThread ← pending calls`.
Гипотеза (не проверена исходниками Shiboken): часть дерева удаляется на рабочем потоке, часть откладывается на главный —
двойное удаление одного C++-объекта.

Масштаб (зонд `DEBUG_SAVEALL`): Qt-мусор оставляют 99/649 тестов `frontend_module` (≥103 Python-владеемых объекта) и
814/2482 тестов прототипа (≥1762). Источники: циклы вкладка ↔ презентер ↔ вид (`frontend_module/widgets/tabs/base_tree_nav_tab.py:119`,
`mvp_pattern.py:44`), `QTimer()` без родителя (`components/base/traits/debounce_trait.py:19`), лямбды на `destroyed`,
держащие виджет (прототип `pipeline/tab.py:180`, `state/bindings.py:266`), `QObject` внутри `QRunnable`
(`sandbox.py:149-171`, `request_runner.py:130`).

## Вердикт CTO

**ACCEPT WITH CONDITIONS** политике памяти GUI-процесса; **BLOCK** посылке Ф5 «миграция GUI-корней закрывает abort».

- Правильная архитектура, не костыль: инвариант «Python-владеемый QObject умирает только на главном потоке; сборка
  мусора вне главного потока в GUI-процессе запрещена» — верен по построению (прецедент pyqtgraph `GarbageCollector`).
- Условия: не второй механизм — расширить `process_module/lifecycle/gc_discipline.py` исполнителем сборки, Qt-адаптер
  тонкий в `frontend_module`; наблюдаемость (нарушения, длительность); страж на `gc.collect`/`gc.enable` (12 мест
  `gc.enable()` в тестах восстанавливают «включено», 4 ломали политику); тесты вызывают ту же функцию сессионной фикстурой.
- Посылка брифа «heartbeat с `FW_GC_SCHEDULED` собирает в GUI-процессе» **не подтверждена**: `ProcessModule` в GUI нет
  (`multiprocess_prototype/frontend/app.py:461`); источники автосборки там — 28 точек запуска потоков.
- Альтернатива «Qt владеет всем» работает, но неполна (pyqtgraph, `MagicMock`, сторонний код) — храповик, не пол.
- План Ж: 0.1–0.3 FREEZE до потребителя, 0.4 KEEP, 0.5 CUT, Ф1/Ф3/Ф4 FREEZE, Ф2/Ф5 — заменить.

## Открыто

- Нативный стек без PDB/cdb; точный путь двойного удаления не назван.
- Пауза главного потока при сборке и рост RSS на живом GUI-стенде не мерены.
- Почему Linux CI (offscreen, 6 × ~11 040 тестов) без abort — не выяснено.
- `tests/test_module_tiers.py::test_no_test_dir_is_invisible_to_every_runner` красный на копиях дерева по коротким путям — не разобран.
