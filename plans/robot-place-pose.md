# План: поза укладки x/y/z/r в CVT-задании робота (доворот)

**Slug:** `robot-place-pose`
**Статус:** P1 (Python протокол) + P2 (Lua укладка) DONE — 116 тестов robot_comm/driver зелёные
(parity yaml↔карта + place wire/lifecycle/PC-конверсия), ruff чист. Lua-исходник правлен в репо —
**прошить и проверить на роботе** (имя 4-й оси WritePoint R/C/A). Осталось P3 (связка съём↔укладка).

**ВЫБОР (PC-side, владелец + рекомендация):** доворот → абсолютный R считает ПК, НЕ Lua.
Драйвер в `_deliver` опрашивает реальный R инструмента (телеметрия, `read_position().rz_deg`) и
шлёт `place_rz = реальный R + доворот` (абсолют). Lua просто ставит присланный R. Плюс: калибровка
угла (`angle_zero_deg`/`angle_invert` в word_layout) тюнится в Python БЕЗ перепрошивки робота.
`R_BASE` в Lua остался только как нейтраль точки укладки (восстановление для place_flag=0 jobs).
**Парность:** правка протокола = **Lua + registers.py одним коммитом** (см. registers.py:4-5).

## Цель

Робот-укладчик кладёт каждую букву в СВОЙ слот под СВОИМ доворотом. Сейчас CVT-задание
несёт только точку съёма, а кладёт в ОДНО фиксированное место (`GL_PLACE` из config) без
поворота. Добавляем в задание полную позу укладки **x, y, z, r** (выход `word_layout`).

## Решения владельца (2026-06-16)

1. **Съём — лента движется, трекинг.** Функция забора с отслеживанием УЖЕ в `run_job`
   (`CVT_VelIn` → `MovL("GL_PICK")` → `CVT_VelOut`, строки 431-440) — НЕ трогаем, переиспользуем.
   `job_x/job_y/job_ecap` остаются (камера + компенсация по энкодеру: px=job_x, py=job_y+trav).
   **Меняем ТОЛЬКО сторону укладки.**
2. **При заборе угол всегда один** — робот хватает диск в ФИКС. ориентации `R_BASE`
   (текущий R точек = −100; уточнить на роботе).
3. **При укладке** R = `R_BASE + place_rz` (доворот от `word_layout`).
4. **После укладки вернуть поворот** R → `R_BASE` (4-я ось не накапливает; следующий
   захват в той же ориентации).

## Протокол: новые регистры (свободный блок 0x1140+)

| Имя | Адрес | Тип | Смысл |
|-----|-------|-----|-------|
| `place_x` | 0x1140 | W, ×10, s16 | X укладки, мм |
| `place_y` | 0x1141 | W, ×10, s16 | Y укладки, мм |
| `place_z` | 0x1142 | W, ×10, s16 | Z укладки, мм |
| `place_rz` | 0x1143 | W, ×10, s16 | доворот, ° (добавляется к R_BASE) |
| `place_flag` | 0x1144 | W | 0 = укладка в config GL_PLACE (как сейчас, обратная совместимость); 1 = по job place_* |

`place_flag` — для обратной совместимости: старые рецепты (одно-корзинный сортировщик)
шлют `send_job(x,y)` без place → `place_flag=0` → робот кладёт в config GL_PLACE как сейчас.

## Lua `run_job` (cvt_universal_full.lua) — изменение

Сейчас (строка 441): `MovP("GL_PLACE")` — фикс. место. Станет:
```lua
-- читать place при приёме задания (рядом с job_x/job_y/job_enc, строки 726-732):
job_place_x  = ReadModbus(0x1140,"W")/XY_SCALE
job_place_y  = ReadModbus(0x1141,"W")/XY_SCALE
job_place_z  = ReadModbus(0x1142,"W")/XY_SCALE
job_place_rz = ReadModbus(0x1143,"W")/XY_SCALE
job_place_fl = ReadModbus(0x1144,"W")

-- в run_job, вместо MovP("GL_PLACE"):
if job_place_fl == 1 then
  WritePoint("GL_PLACE","X", job_place_x)
  WritePoint("GL_PLACE","Y", job_place_y)
  WritePoint("GL_PLACE","Z", job_place_z)
  WritePoint("GL_PLACE","R", R_BASE + job_place_rz)   -- доворот при укладке
  MovP("GL_PLACE")
  DELAY(GRIP_S)                                        -- отпустить (DO_GRIP 0)
  WritePoint("GL_PLACE","R", R_BASE)                   -- ВЕРНУТЬ поворот (4-я ось не копит)
  MovL("GL_PLACE")                                     -- довернуть на месте (Z поднять до home по пути)
else
  MovP("GL_PLACE"); DELAY(GRIP_S)                      -- старое поведение (config место)
end
MovP("GL_HOME")
```
Детали к проверке на роботе: имя 4-й оси в `WritePoint` (R/C/A — у Delta SCARA), значение
`R_BASE` (−100?), порядок «вернуть R» vs «поднять Z» (вернуть R лучше после подъёма, чтобы
не задеть положенный диск). Уточнить при прошивке.

## Python-слой (тестируемо, без робота)

1. **`registers.py`** + **`delta_universal3.yaml`**: +5 регистров (парно с Lua, один коммит).
2. **`client.py`**: `send_job(x, y, e_capture, place=None)` — если `place=(px,py,pz,prz)`,
   пишет place_* + `place_flag=1` в той же транзакции ПЕРЕД `job_flag` (маркер последним).
   `place=None` → как сейчас (`place_flag` не трогаем/0).
3. **`robot_driver.py`**: `enqueue_job` принимает опц. place; `_op_enqueue_job` читает
   `place_x/y/z/rz` из args.
4. **`robot_io`** (`plugin.py`): не ронять `z_mm/r_deg` — форвардить place в `robot_enqueue_job`
   (job из `word_layout.robot_job`: x_mm,y_mm = ?, z_mm,r_deg = place). **ВОПРОС связки:**
   `word_layout` даёт МЕСТО (x,y) — это `place_x/place_y`; точка СЪЁМА (job_x/job_y) приходит
   из калибровки камера→робот (ШАГ 3, отдельный узел). robot_io должен получить ОБЕ позы.
5. **`word_layout`**: выход уже `{x_mm,y_mm,z_mm,r_deg}` → это place. Маппинг в robot_io.

## Связка съём↔укладка (важно, решить в реализации)

Задание роботу несёт ДВЕ позы: съём `(job_x,job_y)` (камера) + укладка `(place_x/y/z/rz)`
(word_layout). Варианты доставки в одно `robot_enqueue_job`:
- (A) узел калибровки даёт `{pick_x,pick_y}`, word_layout даёт `{x,y,z,r}=place` → объединить
  в robot_io (или новый форвардер) в одно задание;
- (B) пока съёма нет (тест укладки) — `place_flag=1`, pick = config/дом, робот едет в place с rz.

## Фазы

- **P1 — Python протокол** (registers/yaml/client/driver/robot_io) + тесты (FakeRobotTransport).
  Тестируемо, без робота, обратимо.
- **P2 — Lua `run_job`** (парно с P1, один коммит) → прошивка на роботе, проверка на железе.
- **P3 — связка съём↔укладка** (узел калибровки pick + объединение в задание).

## Открытые вопросы
- `R_BASE` и имя 4-й оси в `WritePoint` — уточнить на роботе.
- Источник `pick_x/pick_y` (калибровка камера→робот, ШАГ 3 рецепта) — отдельно.
- Порядок «вернуть R / поднять Z» при укладке (не задеть диск).
