# T2.3a — RED acceptance tests for SC_RUN (sim v2 scenario execution)

Parsed: MODE=red (implied — no explicit `MODE:` header, but brief is RED-shaped:
worktree at pre-implementation commit, forbidden paths named, RED acceptance
required), INTERFACE=none (no `interface.py`; contract = protocol-spec.md §7 +
§8.6-8.7 + params.md, per DESIGN), MODULE_CONTRACT=n/a, TASK=T2.3a,
PLAN=plans/robot-protocol-v2/tasks.md.

## Файл

`Services/robot_comm/tests/test_sim_v2_scenario.py` — новый, единственный файл в FILES.

## Тесты (8 функций, 12 test id — 2 параметризованы по 3 случая)

1. `test_scenario_moves_with_do_delay_speed` — DO_ON выставляет бит DO_MASK,
   DELAY_MS не даёт завершиться на тике прихода, после выхода из сценария
   скорость возвращается к `P_SPD_DEFAULT` (§7.2 п.5), DONE_SEQ/SC_INDEX/
   SC_TOTAL/SC_DONE_N.
2. `test_progress_only_on_exact_points` — `TLM_SC_INDEX` и mailbox (PING,
   `busy: allow`) не обновляются на LINE_PASS-точке, обновляются на следующей
   EXACT-точке (§7.2 п.4).
3. `test_bad_record_nak_index_reason_no_motion` [×3: bad kind / bad action /
   bad aparam] — весь срез валидируется ДО движения; первая плохая запись →
   NAK `E_SC_RECORD`, rval0=индекс, rval1=причина; поза не изменилась даже
   при валидной первой записи (§7.2 п.1-2).
4. `test_sc_count_zero_over_capacity_offset_overflow` [×3: count=0 /
   count>SC_CAP / offset+count>SC_CAP] → NAK `E_SC_COUNT`.
5. `test_ping_pong_two_offsets` — два `SC_RUN` с разными `offset` читают СВОИ
   записи буфера (offset=0 и offset=30), не повторяют первую (§7.4).
6. `test_stop_mid_scenario_aborted_do_untouched` — HARD посреди сценария →
   `E_ABORTED`, никогда `DONE_SEQ`; отложенное DO_OFF не исполнилось, DO_MASK
   не тронут (§7.2 п.6, §8 п.6).
7. `test_done_seq_and_sc_done_n_after_last_record` — DONE_SEQ/SC_DONE_N после
   последней записи + порядок И5 (DONE_SEQ пишется после блока события,
   `RecordingRegs`-харнесс, паттерн T2.2).
8. `test_scenario_on_battle_defaults` — e2e на дефолтных параметрах, 4 записи
   (LINE×3 + JOINT-возврат домой), DO_ON, DELAY_MS, реалистичные дистанции
   120/80/60мм.

## Запуск и RED-причина

```
PYTHONPATH=$PWD .venv/bin/python -m pytest -q --tb=line Services/robot_comm/tests/test_sim_v2_scenario.py
```

12 failed. **Все** падают на первой же проверке `res["status"] == ACK` с
`{'status': 2 (NAK), 'errno': 14 (E_INTERNAL), 'rvalc': 0, ...}` —
подтверждённая причина: `SC_RUN` в `_UNIMPLEMENTED_OPS` (`sim_core_v2.py`).
Ни одного `ImportError`/`AttributeError`/`TypeError` — падений от багов
хелперов нет.

Дополнительно (вне 8 тестов, самопроверка): все точки и XY-сегменты сценариев
прогнаны через `geometry.check_point`/`check_segment` (уже принятый оракул
T2.2) напрямую — все OK, зона/мёртвая зона посчитаны верно.

## ASSUMPTIONS (полный текст — в docstring файла)

- A1: `TLM_SC_DONE_N` = `count` при полном успехе (спека даёт только «итог
  исполнения», без формулы).
- A2: `rval0` у `E_SC_RECORD` — индекс внутри среза (0-based от offset); все
  тесты с этой ошибкой используют `offset=0`, где обе трактовки совпадают —
  неоднозначность не эксплуатируется.
- A3: DELAY_MS — буквально миллисекунды (спека это говорит явно); НЕ пином
  точное число тиков задержки, только «не завершается на тике прихода».
- A4: mailbox/`TLM_SC_INDEX` гейтятся до EXACT-точек; тест устойчив к обеим
  гранулярностям прочтения (см. docstring).
- A5: промежуточные точки сценария (включая LINE_PASS) проходятся ТОЧНО
  (поза на каком-то тике совпадает с raw-координатами записи) — по аналогии
  с уже принятым клампингом последнего шага PTP (T2.2).

## Что интерпретировал, а не следовал буквально

- Скоуп чтения `sim_core_v2.py` превышен относительно «конструктор, tick,
  regs, write»: `sed`/`grep` также показали модульный docstring (список
  реализованного текстом, без алгоритмов) и имена констант активности
  (IDLE/PTP/JOG/FAULT — SCENARIO/CVT там нет, не реализованы). По `SC_RUN`
  в файле нет ничего, кроме NAK-заглушки — контаминации по предмету теста не
  было, но раскрываю превышение честно, как того требует правило проекта.
- `TICK_INTERVAL_S`/`MAX_STEP_MM`-формула тайминга (T2.2, уже GREEN) взята
  как оракул для проверки восстановления `P_SPD_DEFAULT` после сценария —
  не переизобретена, скопирована 1:1 из `test_sim_v2_motion.py`.

## Что оставлено открытым / ненадёжно

- Только ПЕРВАЯ строка каждого теста (`assert res["status"] == ACK`) реально
  исполнилась против SUT — весь код после неё (арифметика DO-маски, тайминг
  DELAY, порядок И5, offset-адресация) НЕ прогнан против настоящей логики,
  только против самого себя и (для координат/сегментов) против `geometry`
  оракула отдельным скриптом. Первый реальный прогон этих assert'ов будет
  уже на GREEN — там могут вскрыться баги теста, не только реализации.
- A5 (точное прохождение LINE_PASS-точки) — самое рискованное допущение: если
  реализация сглаживает переход непрерывно и никогда не касается координат
  LINE_PASS-записи точно, `test_progress_only_on_exact_points` придётся
  переписать без привязки к «поза==raw координаты p2».
- Не проверял, требует ли `E_SC_COUNT` пустых `rvals` (rvalc=0) — сознательно
  не пиновал, спека не даёт этого явно (по аналогии с уже принятым в T2.2
  паттерном «не пинить неясные rvals»).
- `argc` для SC_RUN — не тестировал `E_BAD_ARGC` отдельно (не в REDS, не в
  скоупе T2.3a по брифу).

Boundary: task closed. /compact (focus: files + tests + plan path).
