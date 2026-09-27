# T2.K — модель робота (RobotModel/ScaraModel), отчёт разработчика

**Дата:** 2026-09-27 · **Роль:** developer · **Ветка:** `wt/t2k-dev` (из `feat/robot-protocol-v2` @ c2a5c28f)

## Что сделано

1. `Services/robot_comm/kinematics.py` (новый) — `RobotModel(typing.Protocol)`,
   `ScaraModel` (закрытая формула FK/IK, `l1=325.0`/`l2=275.0`, ⚑ GATE-1 —
   знак руки: `hand=0` -> `J2>=0`, `hand=1` -> `J2<=0`), `chain_points`
   (база/локоть/инструмент, Z всех трёх = Z позы), `check_point`/`check_segment`
   как чистое делегирование в `programs/geometry.py` (И6: вторая правда о
   зоне не заводится), `make_model(spec)` (`_MODELS = {"scara": ScaraModel}`,
   неизвестный `type` -> `ValueError` со списком известных).
2. `Services/robot_comm/server/sim_core_v2.py` — конструктор
   `RobotSimCoreV2(regs=None, *, fw_build=0, model=None)`, `self.model`
   выставляется ДО `_boot()`; три места проверки зоны (`_check_motion` x2,
   `_progress_jog`) переведены на `self.model.check_point`/`check_segment`;
   `check_point, check_segment` убраны из импорта `geometry` (`Workspace`
   остался); добавлен `joints()` (T2.V — суставы текущей позы через
   `self.model.ik`); строка в докстринге модуля про T2.K.
3. `Services/robot_comm/tests/test_kinematics_v2_internal.py` (новый,
   3 теста, хазарды автора): clamp `c2` на границе досягаемости не даёт
   `math.acos` упасть (проверено вручную и без clamp — падает,
   `math domain error`); `ik` отклоняет NaN/inf позу -> `None`; `fk(ik(pose))`
   не вносит ±360°-сдвиг в RZ (J4-wrap).
4. `Services/robot_comm/README.md`, `Services/robot_comm/server/README.md` —
   по абзацу про модельный шов.

## Приёмка

```
PYTHONPATH=$PWD .venv/bin/python -m pytest -q --tb=short Services/robot_comm/tests/
```
`727 passed, 5 skipped, 2 xpassed` — было `724 passed, 5 skipped, 2 xpassed`
до T2.K (+3 = новый `test_kinematics_v2_internal.py`); `test_kinematics_v2.py`
10/10 зелёные; `test_sim_v2_core.py`/`test_sim_v2_motion.py` (+`_internal`
пары) — числа не изменились, значит поведение по умолчанию (модель не
передана) не сдвинулось.

```
ruff check Services/robot_comm/kinematics.py Services/robot_comm/server/sim_core_v2.py
```
`All checks passed!`

## Что я интерпретировал, а не вывел из брифа буквально

- `chain_points` Z: бриф говорит «Z всех трёх = pose Z» — читал это как
  `joints[2]` (переданный Z), не как пересчитанный `fk(joints)[2]` (они
  численно совпадают, т.к. `fk` просто пробрасывает Z без изменений, но
  реализация берёт исходный `z` напрямую, а не через второй вызов `fk`).
- `make_model` передаёт все поля спецификации, кроме `"type"`, как kwargs в
  конструктор класса (`ScaraModel(**kwargs)`) — бриф не называл механизм
  прокидывания `l1`/`l2` явно, это самый прямой путь, других полей у
  `ScaraModel` нет.
- В `joints()` докстринге упомянул T2.V (окно-вид) — бриф явно называет этот
  метод «для окна-вида», сама T2.V не в scope этой задачи.

## Что осталось открытым / ненадёжным в моей работе

- Хазард-тест на "стретч-сингулярность" бьёт по границе `_REACH_TOL=1e-9`
  через `math.nextafter` — проверяет именно clamp, но НЕ проверяет поведение
  чуть ДАЛЬШЕ допуска (`r > reach_max + tol`), где корректно должно вернуться
  `None`; эта ветка покрыта только приёмочным `test_unreachable_returns_none`
  на грубых значениях (700мм), не на границе допуска.
- Длины звеньев (`l1=325.0`, `l2=275.0`) — заглушка по брифу (`P_WS_R_MAX`
  default=600), реальные значения с шильдика робота не подставлены (plan §9
  q1, вне scope этой задачи).
- Не проверял `make_model` с частичной спецификацией (`{"type": "scara"}` без
  `l1`/`l2` — берёт dataclass-дефолты) отдельным тестом; логически очевидно
  из `**kwargs` в конструктор, но не задокументировано assertion'ом.
- Не запускал break-injection сам — по протоколу это задача ведущего
  (`teamlead`/`lead`), не разработчика; предсказанный набор тестов, которые
  должны упасть при снятии clamp: весь `test_kinematics_v2_internal.py`
  тест №1 (`test_ik_stretched_singularity_does_not_raise_on_float_c2_overshoot`)
  и приёмочный `test_fully_stretched_boundary` — оба используют границу
  `r == l1+l2`.
- Не проверял поведение `RobotModel` Protocol на runtime `isinstance`
  (Protocol без `@runtime_checkable`) — бриф не просил, но значит
  `isinstance(core.model, RobotModel)` не сработает, если кому-то
  понадобится в будущем (тест приёмки проверяет `isinstance(core.model,
  ScaraModel)`, конкретный класс, не Protocol).

Boundary: task closed. /compact (focus: files + tests + plan path).
