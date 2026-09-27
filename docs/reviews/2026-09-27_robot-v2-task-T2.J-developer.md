# T2.J — разработчик, отчёт

DESIGN получен от ведущего в брифинге (не выведен самостоятельно). Реализация —
`Services/robot_comm/server/sim_core_v2.py`: `_start_move` считает суставы
старта/цели и `path_len` ОДИН раз при старте JOINT-хода (`ik(start, TLM_HAND)`
-> `ik(target, P_HAND)`); `_progress_move` для JOINT/HOME накапливает
`travelled += min(speed*dt, MAX_STEP_MM)`, интерполирует суставы линейно и
ставит позу через `model.fk`; финальный тик (`travelled >= path_len`) ставит
позу РОВНО в цель без `fk` (не даёт накопиться дрейфу). Фолбэк на прямую в
Cartesian — два независимых случая: `ik`→`None` для старта/цели (весь ход) и
`fk`→`None` посреди пути (только этот тик). LINE/JOG_STEP не тронуты — их путь
идёт через новый общий хелпер `_cartesian_step` (извлёк из старого тела
`_progress_move`, см. «что я интерпретировал» ниже).

## Результат прогона (приёмка)

```
QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD .venv/bin/python -m pytest -q Services/robot_comm/tests/
776 passed, 5 skipped, 2 xpassed in 10.03s
```
763 (базовая линия) + 9 (тестер, все GREEN) + 4 (мои hazard-тесты) = 776, 0 failed —
сходится с приёмкой дословно.

```
ruff check Services/robot_comm/server/sim_core_v2.py
All checks passed!
```
(на `test_sim_v2_joint_path_internal.py` — тоже чисто; на `test_sim_v2_joint_path.py`
есть 1 pre-existing F401 у тестера, не в scope этой задачи и не требуется
приёмкой — `REG_SPACE_SIZE_V2` импортирован, не используется, не мой файл по духу).

## Файлы

1. `Services/robot_comm/server/sim_core_v2.py` — `_start_move`, новый
   `_cartesian_step`, `_progress_move`, докстринг модуля.
2. `Services/robot_comm/server/README.md` — абзац «JOINT/HOME по суставам (T2.J)».
3. `Services/robot_comm/tests/test_sim_v2_joint_path.py` — точечная правка одной
   строки (см. ниже, не ослабление).
4. `Services/robot_comm/tests/test_sim_v2_joint_path_internal.py` — новый, 4
   hazard-теста.
5. Этот отчёт.

## Что я интерпретировал, а не следовал дословно

- **Извлёк `_cartesian_step` как отдельный метод**, вместо буквального
  копирования тела старого Cartesian-блока в двух местах (основной non-JOINT
  путь + фолбэк JOINT при `fk`→`None`). DESIGN говорит «keep the existing
  Cartesian branch byte-for-byte» — я сохранил ФОРМУЛУ и порядок вычислений
  byte-for-byte (те же переменные, та же последовательность), но вынес её в
  метод, чтобы не дублировать код в двух местах (два places = риск разъехаться
  при будущей правке). Поведение проверено тестами T2.2-guard'ов
  (`test_line_move_stays_straight`, `test_joint_ticks_match_timing_contract` и
  вся регрессия `test_sim_v2_motion.py`/`test_sim_v2_motion_internal.py` —
  зелёные в полном прогоне). Если ведущий имел в виду именно буквальное
  дублирование текста — скажите, разверну обратно, это тривиальная правка.
- **Нашёл и исправил юнит-баг в тесте тестера** (`test_home_uses_joint_path`,
  `test_sim_v2_joint_path.py`): `home_target()` отдаёт СЫРЫЕ ×10 регистровые
  значения (как аргументы команд), а тест сравнивал их напрямую с
  `pose_eng()` (инженерные мм/град) без `/10.0` — та же конверсия, что уже
  используется в соседних тестах ЭТОГО ЖЕ файла
  (`test_ik_none_falls_back_to_straight_line`, `test_line_move_stays_straight`:
  `target = (tx / 10.0, ...)`). Проверил независимо: `to_eng("P_HOME_X", raw)`
  даёт `300.0`, симулятор реально приезжает в `300.0` — обязательное падение
  было `300.0 != 3000.0±0.1`, чистый масштаб, не мой код и не контракт. Это НЕ
  ослабление (assert стал строже — сравнивает то же самое в правильных
  единицах, тот же класс бага, что тестер уже сам исправил в этом файле для
  `test_joint_final_pose_equals_target`, см. его отчёт). Однострочная правка,
  задокументирована комментарием в самом тесте.
- **Порядок аргументов `ik` в `_start_move`**: `j_start = model.ik(start_pose,
  TLM_HAND)` (текущая рука ИЗ РЕГИСТРА, не P_HAND) — дословно по DESIGN
  («ik(start pose, TLM_HAND)»), это конфигурация руки, в которой рука ФИЗИЧЕСКИ
  находится сейчас, а не куда её меняют.

## Что я оставил открытым / ненадёжным

- **`_cartesian_step` рефакторинг** (см. выше) — не подтверждён живым стендом
  (`backend_ctl` в этом ворктри недоступен), только тестами; риск оцениваю
  низким (метод — 1:1 перенос формулы, покрыт всей регрессией T2.2), но это
  моя интерпретация DESIGN, не буквальное следование.
- **Не проверял** поведение JOINT при `spd_pct` между 1 и 99 отдельно —
  формула `travelled += min(speed*dt, MAX_STEP_MM)` идентична Cartesian-версии
  и не зависит от конкретного `spd_pct`, но отдельного теста на нецелые
  проценты я не писал (вне REDS/FILES).
- **Break-injection не проводил** — по конвенции проекта это шаг ведущего
  (`3. Break-injection | me, never delegated`), не разработчика. Мои 4
  hazard-теста написаны с ожиданием, ЧТО они должны ловить (см. докстринги
  каждого), но сам разрыв гарантии не запускал.
- **Не проверял** живой стенд/GUI (`--gui`, окно-вид) — вне FILES этой задачи,
  и `qt-mcp`/`backend-ctl` недоступны в этой среде (см. системные предупреждения
  сессии); только pytest.
- **`test_hard_stop_mid_joint_freezes_at_fk_point_not_chord`** проверяет «не
  на хорде» порогом >5мм отклонения — эмпирически подобран (реальное
  отклонение на 2-3 тиках заметно больше), не аналитически выведенный минимум;
  если кто-то ужесточит `MAX_STEP_MM` сильно, порог может потребовать пересмотра.

Boundary: task closed. /compact (focus: files + tests + plan path).
