---
title: "Access violation корневого гейта — досье с дампами (закрытие 4.1)"
type: investigation
date: 2026-08-12
refs: plans/observability-roadmap.md
---

# Access violation корневого гейта — досье

Предыстория: падение видели трижды до этой сессии (2026-08-11: фреймворковая сьюта ×2
на `sampling.py:213`; корневой гейт ×1 на `ml_inference/test_plugin.py`), ни разу не
поймали в файл. Правило из handoff: «ловить faulthandler-дампом в файл, а не пересказом».
Здесь — поймано трижды за три прогона, найдены и закрыты два дефекта, падение
прекратилось (5 полных гейтов подряд зелёные). В досье оставлен и разбор **ложной
первой атрибуции** — она прожила полчаса и была опровергнута пробой.

## Репро: 3 падения из 3 прогонов ДО правок

Команда каждый раз: `python -m pytest > <лог> 2>&1` (faulthandler у pytest включён по
умолчанию, дамп уходит в лог). Все три прогона — **полный состав** (см. разбор ошибки
ниже). Выдержки дословные.

| Прогон | Упал в | Дамп |
|---|---|---|
| №1 | `Services/ml_train/tests/test_trainer_export.py::test_available_archs_lists_sources` | главный поток в `pytestqt/plugin.py:220 _process_events`; рядом 19 фоновых потоков: 18 × `delta_dispatcher.py:278 _flusher_loop` + 1 нативный без Python-кадра |
| №2 | `Services/ml_train/tests/test_data.py::test_build_dataloaders_exported_with_splits` | тот же: `_process_events` (`pytest_runtest_call`), 18 flusher-потоков |
| №3 | `Services/ml_train/tests/test_trainer_export.py::test_fit_artifacts` | тот же: `_process_events` (`pytest_runtest_setup`) |

Типовая голова дампа (прогон №1):

```
Services/ml_train/tests/test_trainer_export.py::test_available_archs_lists_sources Windows fatal exception: access violation

Thread 0x00005f38 (most recent call first):
  <no Python frame>

Thread 0x0000692c (most recent call first):
  File "...\threading.py", line 359 in wait
  File "...\state_store_module\manager\delta_dispatcher.py", line 278 in _flusher_loop
  ... (всего 18 таких потоков)

Current thread 0x00008dc4 (most recent call first):
  File "...\pytestqt\plugin.py", line 220 in _process_events
  File "...\pytestqt\plugin.py", line 188 in pytest_runtest_call
  ...
```

Сигнатура едина: главный поток внутри насоса Qt-событий pytest-qt, детонация кочует по
`Services/ml_*` (первая аллокационно-тяжёлая зона после frontend), в каждом дампе — 18
утёкших flusher-потоков.

## Найденные дефекты

**Дефект 1 — 23 теста поднимали StateStoreManager и не гасили.** `initialize()`
запускает daemon-поток `StateCoalesceFlusher` (тик 0.12 с); поток держит диспетчер
сильной ссылкой (bound method в target), поэтому забытый стенд **бессмертен** — GC его
не собирает, тикает до конца прогона. Виновников назвала проба (одноразовый
pytest-плагин: после каждого теста сравнение множества живых потоков по имени, прирост
→ строка с nodeid): 18 поимённо в 4 файлах `state_store_module/tests` (7+5+3+3), ещё 5
следом поймал уже новый страж в `app_module/tests/test_orchestrator.py` — зоне, которую
корневой гейт не собирает. Из этих пяти три не гасили созданный стор, а два **подменяли
`shutdown` менеджера спаем**: вызов доказан, настоящий поток жил.

Закрыто: пары `initialize()/shutdown()` во всех 23; класс закрыт autouse-стражем
`_no_leaked_state_flushers` (`multiprocess_framework/modules/conftest.py`) — сравнение
множеств потоков до/после теста, краснеет ДОБАВИВШИЙ, утёкший поток гасится
best-effort, реестр долгоживущих стендов пуст и требует причину. Страж показан
**красным 18/18 с предсказанием набора до прогона**, после правок — зелёным.

**Дефект 2 — не дефект, а мина: matplotlib при живом PySide6 резолвит `qtagg`.**
Факт: `python -c "import matplotlib; print(matplotlib.get_backend())"` → `qtagg`.
Первый же импортёр matplotlib в тестовом процессе молча создал бы второй источник
QApplication вне qtbot-дисциплины. Закрыто строкой `MPLBACKEND=Agg` (setdefault) в
корневом `conftest.py` — **сегодня инертной** (см. пробу ниже) страховкой класса.

## Разбор ложной атрибуции — оставлен как урок

Первая версия причины звучала «QApplication создаёт matplotlib, приезжающий в ml-тесты
через ultralytics». Она опиралась на «дискриминатор»: прогон
`pytest --ignore=multiprocess_prototype/frontend` упал так же → «Qt-зоны нет, а qapp
есть». Проверка выключателя счётчиком показала: **`--ignore` зону не выключил** — в
«прогоне без frontend» исполнились 2411 frontend-тестов (каталог объявлен в
`testpaths`), состав был полным. Дискриминатор был негодным, вывод из него — ничем.

Опровергла атрибуцию проба по фактам (плагин `first_importer_probe`, полный гейт):

```
FIRST-QAPP after multiprocess_prototype/frontend/actions/middleware/tests/test_pre_auth_guard.py::TestPreAuthGuardHook::test_blocks_write_when_not_authenticated
SESSION-END: mpl_imported=False backend=None qapp=True
```

То есть QApplication создают **frontend-тесты** (штатный qtbot), а **matplotlib за весь
гейт не импортируется ни разу** — заплата Agg для сегодняшнего состава инертна, и
падение остановила не она.

## Атрибуция по остатку и её предел

Между 3/3 падений и 5/5 зелёных изменились две вещи: закрытие утечек и `MPLBACKEND=Agg`.
Вторая доказано инертна (matplotlib не импортируется) → действующая правка —
**закрытие утечек**. При p(падения) ≈ 3/4 вероятность пяти подряд зелёных без правки
≈ 0.1 %. **Микромеханизм связки** «18 вечно тикающих потоков ↔ access violation в
насосе Qt-событий» этим не доказан и в проекте не утверждается: зафиксированы дефект,
его закрытие и прекращение падений на том же составе.

## Хронология: «проблема была всегда?»

| Дата | Событие |
|---|---|
| 2026-06-13 | `91c8c988` — ml_train создан; его тесты не гоняет ни один прогонщик (невидимки) |
| 2026-07-22 | `2c2bd721` — у диспетчера появился flusher-поток (FW_STATE_COALESCE, default OFF — утечка спит) |
| Ф6.1 | `b284c561` — дефолт коалесцирования ON: каждый state_store-тест без shutdown() течёт потоком |
| 2026-08-11 | `dc8de208` (4.0) — 871 невидимый тест внесён в гейт; в тот же день впервые увидены падения |

Ингредиенты старые; взрыв стал видим в день, когда 4.0 сделал невидимые тесты
видимыми, — цена честности гейта, а не регрессия 4.0.

## Подпись

- До правок: 3 падения / 3 прогона (плюс 2 падения по одному у прошлых сессий).
- После правок: корневой гейт `6801 passed, 64 skipped` **×5 подряд** (2:01 / 1:51 /
  1:50 / 2:28 / 1:56); фреймворковая сьюта `7712 passed, 8 skipped, 0 errors` (2:54);
  `backend_ctl` живьём `642 passed` (9:44).

## Честные остатки

- Экземпляр падения фреймворковой сьюты 2026-08-11 (×2 на `sampling.py:213`) дампом в
  файл не пойман. В той сьюте state_store-тесты (и значит та же утечка) есть, поэтому
  закрытие утечки МОГЛО закрыть и его — но это не показано; после правок сьюта зелёная.
  При возврате — ловить логом в файл, как здесь.
- Микромеханизм детонации не доказан (см. «предел атрибуции» выше).
