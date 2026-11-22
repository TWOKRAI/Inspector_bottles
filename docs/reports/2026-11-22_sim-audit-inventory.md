# Сим-аудит · опись «не проверено на симе» · 2026-11-22

Полоса «Н · сим-аудит», сессия inspector-bottles-ee [534a0e], дерево `../Inspector_bottles--lane-sim-audit`, ветка `test/sim-wire-audit` (от `main` = `e1cd3f85e`).
Опись собрал агент `Explore` (haiku, только чтение; qex не индексирован, поиск `git grep` и `Read`). Ключевые факты ниже пересверены лидом по коду (помечены «✔ лид»). Остальное — слова источников, не проверенные лидом.

## 1. Опись (ядро из промпта полосы)

| № | Не проверено на симе | Источник (path:line) | Статус |
|---|---|---|---|
| 1 | Дубли и потеря диска повторяющейся буквы (Е, Р, И) | `plans/release-1.0/tasks/1.2.result.md:16`; `scripts/alpha_sim/README.md:154` (Е×4, Р×2, И×2 в B; Е×3 в C); `docs/reports/2026-11-12_release-1.0_alpha-rerun.md:125` | заявлено не проверенным (3 прогона, потерь не было) |
| 2 | Декодирование каждого `CVT_JOB` в мм и ° против расчёта (`pixel_to_robot` → ячейка → `rz`) | расчёта в `logic.py` нет: только литералы `_PICK_X/_PICK_Y/_A2/_A3` (`:224–232`); `pixel_to_robot` — `Plugins/processing/pixel_to_robot/plugin.py:42` | расчёта в скрипте α не найдено |
| 3 | Остаток 0,3 мм по `py` (−342,3 против расчёта −342,6) | `1.2.result.md:16`; `alpha-rerun.md:52` («остаток не объяснён») | не объяснён; число −342,6 есть только в docs |
| 4 | Уникальность `CMD_SEQ` | `logic.py:104–105` (регэкспы) — проверки уникальности нет | не найдено |
| 5 | Пара «команда ↔ ответ с тем же `RES_SEQ`» | `logic.py:112`, `:139`; `alpha-rerun.md:39` («77 команд без несовпадения» — одна сверка tester) | частично |
| 6 | S9: ответ `system_shutdown` не в `--dump` | `1.2.result.md:15`; `run_alpha.py:280` `"replies": {}` ✔ лид (создаётся пустым, нигде не заполняется) | подтверждено кодом |
| 7 | «Домой» при диске в полёте, n=1 | `docs/reports/2026-11-22_pult_recheck-run-gate.md:32` | n=1, повтора нет |
| 8 | Кнопки GUI «Домой»/«ОСТАНОВИТЬ»/ленты в `ready` | `pult_recheck-run-gate.md:31` | не нажимались |
| 9 | «✕», ветка «Yes» | `pult_recheck-run-gate.md:31`; код `multiprocess_prototype/frontend/widgets/tabs/services/control_panel/widget.py:287` | не проверена (модалку закрыл сторож) |
| 10 | `run_alpha.py` с `--autostart` | `pult_recheck-run-gate.md:33`; `scripts/alpha_sim/README.md:37–39` | не гонялся |
| 11 | S6 одним прогоном: поле «Слово», смена слова на ходу | `pult_recheck-run-gate.md:12–13` | n=1, B 8/9 (сеть) |
| 12 | Строка C-104 в `system.log` | `docs/handoffs/2026-11-22_R2-merge-request.md:27`; код `Plugins/io/robot_io/plugin.py:275`; тест `Plugins/io/robot_io/tests/test_c104_real_objects.py:169` | на стенде не гонялась; идёт в `system.log`, не `messages.log` (`OPEN_QUESTIONS.md:2551`) |
| 13 | β `hikvision_letter_robot` на симе | `multiprocess_prototype/recipes/hikvision_letter_robot.yaml:119,125,61,64`; сим-вариант `letter_robot_sim.yaml:77–78` | нужен override (камера реальная, серийник `DA1689923`, робот `192.168.1.7:502`); fake-режима в рецепте нет |

Прочее, что опись нашла сверх ядра (кратко; полный список — в сообщении агента, не повторяется здесь): R4-пункты К (`OPEN_QUESTIONS.md:2601` — серво по умолчанию, `P_ZONE_MAX`, досягаемость 544 мм без валидатора, `cam0.yaml` отсутствует, readiness камеры); шум центроида > 0,5 px не измерен (`alpha-rerun.md:57`); причина потери «М» не установлена (`STATUS.md:53`); допуск угла ±15° временный (`logic.py:226`); смысл поля `servo` в park не разобран (`STATUS.md:54`); лента после `system_shutdown` (`STATUS.md:56`); задание от линии без ручной команды (`T5.6_stand.md:7`); C-103 (вопрос владельцу), C-105 (`gui terminated` 5 из 5, полоса Ф); Modbus 5021 напрямую не читали (`pult_recheck-run-gate.md:36`).

## 2. Факты для аудита провода

**a) Кодирование** (✔ лид): `Services/robot_comm/core/client_v2.py:1184` `_geom_words`: `n = round_half_away(value × WIRE_SCALE)`, `WIRE_SCALE = 10` (`protocol_v2.py:409`), диапазон `W_MIN..W_MAX = −32767..32767` (`:410–411`). Квант: **1 слово = 0,1 мм и 0,1°**, ошибка округления ≤ 0,05. На провод слово идёт как `& 0xFFFF` (отрицательное = 65536 + n; пример α: 64436 → −110,0 мм).
`cvt_job` (`client_v2.py:881–902`): `[ecap & 0xFFFF, ecap >> 16, pick_x, pick_y, pick_z, flags, place_x, place_y, place_z, place_rz]` — `CMD_ARGC = 10`.
Угол: `place_rz` на проводе = `P_PICK_RZ + доворот` (`Services/device_hub/drivers/robot_driver_v2/jobs.py:147–148` ✔ лид); S1 α проверяет `P_PICK_RZ.raw == −1000` (−100,0°).
**Знак `rz` (исправление описи, ✔ лид):** строка диска `layout` печатает **сырой угол сети** (`plugin.py:274` `_log_disk`), а `r` в строке взятия — уже **доворот** `wrap180(angle_zero − sign·угол_сети)` (`Plugins/processing/word_layout/geometry.py:102`, `assembler.py:116`; поле `job["angle_deg"]` названо вводяще). Формула α `wrap180(0 − angle)` (`logic.py:526`) верна. Цепочка до слова: `pose["place_rz_deg"]` → `data["place_rz"]` (`robot_io/plugin.py:188`) → `P_PICK_RZ + turn` (`jobs.py:66`) → `_geom_words`. Живой пример: «М» 281,5° → `r 78,5` → `ARGS[9] 65321` (`alpha-rerun.md:37`). Первая версия этой описи («r = +angle_deg, знак не прослежен») была ошибкой чтения.

**b) Журнал обмена:** `Services/device_hub/drivers/exchange_log.py` (`ExchangeLog:205`, `get:235`, `set:255`); запись `{seq,t,side,text,tag,n,ms}` (`:19`); файл `devices/robot_exchange.log`; строка `#<seq> [in|out] W* CMD_ARGS[i] = n` (форма — `docs/reports/2026-10-19_T5.6_stand.md:14`, разбор — `logic.py:166`).
Эталон декодирования (T5.6, M1): `CMD_ARGS[0..3] = 18178, 1, 3000, 64536` → ecap 83714, x 300,0, y −100,0 (сходится с заданием `x_mm:300, y_mm:−100`); ответ `RES_SEQ = 33258, RES_STATUS = 1`.

**c) Журнал диска `word_layout`:** `plugin.py:274–276` `_log_disk`; взятие — `plugin.py:250–256`: `ячейка N: взять(px,py) → положить x… y… z… r…° [k/n]`; пропуски — `:204, :220, :222, :296, :308, :330, :338–340`. **Причин пропуска в коде 7 форм, а не 6** (README `word_layout:131–155`: пять пропусков + «ниже порога» + «нет предсказания») — промпт говорит «6 причин».

**d) Литералы α** (`logic.py`): `_CELL_Y` шаг 110 мм от −440 до 440 (`:214`); `_CELL_A7 = {0: 61136, 1: 62236, 2: 63336, 3: 64436, 4: 0, 5: 1100, 6: 2200, 7: 3300, 8: 4400}` (`:215`); `_PLACE_X = 320,0`, `_PLACE_Z = −132,0` (`:222–223`); `_FIXED_ARGS = {4: 64216, 5: 3, 6: 3200, 8: 64216}` (`:230`); окна съёма `_PICK_X = (454,9; 461,5)`, `_PICK_Y = (−344,0; −342,0)`, `_A2 = (4549, 4615)`, `_A3 = (62096, 62116)` (`:224–232`); `_R_TOL = 15,0` (`:226`). Комментарий у `_A3` («−3400 + 65536») с окном не сходится — на расчёт не влияет.
Случаи (`logic.py:257–304`): **B** ПЕРЕМИРИЕ — 12 дисков, 9 ячеек, регистры `jobs_emitted 9`; **D** МИР — 5 дисков, 3 задания, `jobs_emitted 12`; **C** ПЕРЕМИРИЕ — 4 диска Е, 3 задания, `slots_filled 3`, `jobs_emitted 15`.

## 3. Не найдено / ненадёжно

- Расчёта `pixel_to_robot` → ячейка → `rz` в скрипте α **нет**; «независимый расчёт» аудита придётся брать из журнала `layout` (значения с одним знаком после запятой) — пиксельные входы в журнале не видны (проверить в задаче 3, пишет ли `pixel_to_robot` вход в лог).
- Опись не читала `core/camera.py:111` (поведение β без SDK) и не грепала R4-пункты К; считать словами `OPEN_QUESTIONS.md`.
- Противоречия источников: сверка сидов 1–3 (`1.2.result.md:16` «не проверено» против `alpha-rerun.md:141` «пересчёт совпал»); место строки C-104 (`messages.log` в карточке `plans/queue/defects.md:381` против `system.log`).
- Раздела «Не сделано» в `pult_recheck-run-gate.md` нет; взят «Открыто / ненадёжно» (`:30–37`).
- Стенд не запускался, тесты не гонялись.
