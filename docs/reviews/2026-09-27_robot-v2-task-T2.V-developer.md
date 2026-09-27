# T2.V — окно-вид симулятора: отчёт разработчика

**Роль:** developer. **Цепочка:** blind tester (RED, уже в ворктри) -> я (GREEN) -> лид (break-injection) -> reviewer.

## Что сделано

Новый пакет `Services/robot_comm/gui/` (единственное Qt-место `robot_comm`, И9):

- `__init__.py` — однострочный докстринг.
- `sim_view.py` — `SimView(QWidget)` (read-only вид сверху: зона, цепи звеньев
  модели, шлейф TCP, статус, `clicked(x, y)` по ЛКМ) + `DemoDriver` (единственный
  писатель, mailbox-паттерн тестов + прямой `STOP_REQ`) + `main()`.

Тесты:

- `tests/test_sim_view.py` — слепой RED-файл лида, уже был в ворктри.
  9/9 GREEN сразу после реализации, без правок теста.
- `tests/test_sim_view_internal.py` — 10 моих хазард-тестов: обратность
  `widget_to_robot` на 4 размерах виджета, `refresh()` без исключений на
  `joints() is None` и на FAULT, инвариант seq `DemoDriver` (не совпадает со
  stale `RES_SEQ` после «рестарта», растёт между вызовами), инвариант raw-
  значения `STOP_REQ` (меняется на каждый `stop()`, отличается от stale
  регистра).

`README.md` — раздел «Окно-вид симулятора v2» (запуск, что показывает, что
заглушка — длины звеньев SCARA).

## Break-injection (мои хазард-тесты)

Два break'а против `stop()` (проверка, что тесты не vacuous):

1. Убрал цикл `while value == current` (коллизия с уже лежащим в регистре
   значением) и зафиксировал `value = STOP_LEVEL["HARD"]` (константа, не
   растёт) → `test_demo_driver_stop_value_changes_every_call` и
   `test_demo_driver_stop_value_differs_from_stale_register_content` оба
   упали (`assert 2 not in {2}`, `assert 2 != 2`). Ожидание совпало с
   наблюдением.

Файл восстановлен из копии сразу после проверки (diff чистый).

Break против `DemoDriver._seq` старта (не с `RES_SEQ`, а с 0) НЕ убил тест
`test_demo_driver_seq_never_repeats_stale_res_seq_after_boot` при
`stale_seq=42` — первый сгенерированный seq (`0+1=1`) случайно не совпал.
Это слабость МОЕЙ проверки break-injection (не самого теста: тест по-прежнему
проверяет правильный инвариант и правильно построен на конкретном сценарии
рестарта), а не теста — оставляю как открытый пункт ниже, лид может
перепроверить с `stale_seq=1`.

## Приёмка

```
QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD .venv/bin/python -m pytest -q Services/robot_comm/tests/
754 passed, 5 skipped, 2 xpassed in 9.96s
```

(baseline 735 passed + 5 skipped + 2 xpassed; +19 новых тестов из test_sim_view.py (9) и test_sim_view_internal.py (10) = 754 — совпадает.)

```
ruff check Services/robot_comm/gui Services/robot_comm/tests/test_sim_view_internal.py
All checks passed!
```

```
QT_QPA_PLATFORM=offscreen python -c "from Services.robot_comm.gui.sim_view import main"
```
— без ошибок импорта.

Дополнительно (не входит в acceptance, но по `verify-done`): собрал окно
вручную offscreen (`QApplication` + `SimView` + `DemoDriver` + кнопки + таймер
тика), покликал по кнопкам и `driver.goto`, погонял `processEvents()` 0.25 с,
сделал `view.grab()` — без исключений, `status_text()`/`scene_chains()`
осмысленные. Лид сам откроет настоящее окно (по брифу).

## Что я интерпретировал, а не вывел из брифа

- **Имена активности в статусе** — бриф говорит «IDLE/PTP/JOG/FAULT names from
  sim_core_v2 TLM_ACTIVITY_* constants», но не уточняет, показывать ли их
  литерально (`IDLE`/`PTP`/…) или переводить на русский. Показал литерально
  (`активность: PTP`) — по-русски был бы «статус» текст, а не «имя константы»,
  как сказано в брифе. Ни один тест это не проверяет напрямую.
- **Масштаб/margin отрисовки** (`_MARGIN_PX=20`, `_ZONE_MARGIN=1.1`) — бриф
  просит «uniform scale fit to the zone r_max with margin», числа не назвал —
  взял разумные константы, `widget_to_robot` — точная обратная им при любых
  значениях (проверено тестом на 4 размерах), так что сами числа не влияют на
  корректность контракта.
- **`DemoDriver._send`/`stop()` не тикают `core`** — вывел из теста
  `test_click_maps_to_robot_and_moves` (клик, затем `run_until_idle`, без
  промежуточного `core.tick()`) и раздела DESIGN про `main()` (таймер тика —
  отдельно). Не совсем «выведено из брифа» дословно, но подтверждено RED-тестом.
- **Заголовок окна и `SimView`** — поставил `setWindowTitle` только на
  верхнее `QWidget` в `main()`, не на сам `SimView` (он не top-level, когда
  встроен в layout).

## Что осталось открытым / ненадёжным

- **Слабость собственного break-injection на seq-тесте** (см. выше) —
  инвариант в коде правильный (проверил логикой: `_seq` стартует от
  `RES_SEQ`, инкремент на 1 каждый `_send`, поэтому первый сгенерированный
  seq гарантированно `!= RES_SEQ`), но мой break не подтвердил это на выбранном
  `stale_seq=42` — совпадение первого шага (0+1=1≠42) скрыло дефект. Тест
  структурно верен, слабость в выбранном контрпримере при верификации, не в
  самом файле теста.
- **Визуальная корректность отрисовки** (зона/сектор/цепи/шлейф/цель на
  экране) НЕ проверена глазами — только программно (`grab()` без исключений,
  непустой pixmap). Лид по цепочке сам откроет окно вживую (это явно в его
  части задачи).
- **Тонкая линия трансформации `+X вправо, +Y вверх`** — реализована и
  математически протестирована (обратность), но не сверена с реальной формой
  сектора J1 на экране (визуально сектор мог бы оказаться зеркальным/повёрнутым
  относительно ожиданий владельца — числа верны, ориентация на глаз не
  проверялась).
- **DemoDriver.home()/servo()** не покрыты отдельным assert-тестом на
  корректность opcode/argc (только smoke в
  `test_demo_driver_seq_increments_across_calls` для servo, и ручной offscreen
  smoke выше) — RED-файл их не требует явно, дизайн описывает их как простые
  однострочные обёртки над `_send`, риск низкий, но не формально доказан
  break-injection'ом.

## Файлы

- `Services/robot_comm/gui/__init__.py` (новый)
- `Services/robot_comm/gui/sim_view.py` (новый)
- `Services/robot_comm/tests/test_sim_view.py` (RED лида, уже в ворктри — не менял)
- `Services/robot_comm/tests/test_sim_view_internal.py` (новый)
- `Services/robot_comm/README.md` (правка)
- `docs/reviews/2026-09-27_robot-v2-task-T2.V-developer.md` (этот файл)
