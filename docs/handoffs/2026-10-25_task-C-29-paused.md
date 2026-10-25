# Передача: полоса Р2, C-29 на паузе (2026-10-25)

Сессия-автор: inspector-bottles-d0. Координатор — имя в строке `coordinator:` файла
`D:\PROJECT_INNOTECH\Inspector_vision\machine.lock` (на момент передачи inspector-bottles-bc). Первое сообщение ему —
своё имя сессии. Пауза — по слову владельца (через координатора).

## Где стоим

- Ветка `fix/robot-v2-c29`, worktree `.claude/worktrees/robot-v2-c29`, от main `fcc1033b9`. Код продукта не менялся.
- Готово (в этом коммите WIP):
  - `plans/robot-protocol-v2/tasks/C-29.md` — бриф, редакция 2 (Senior+): DESIGN / FILES / REDS / REPORT, ACCEPTANCE,
    решения владельца В1–В4 ПРИНЯТО;
  - `C-29.injections.md` — контракт R1–R9, 19 инъекций с красными наборами;
  - `C-29.probe.md` — проба барьером: р.1 17 failed / 8 passed (по прогнозу), р.2 22 failed / 10 passed (по прогнозу);
  - `C-29.stage0.md` — стадия 0 Opus р.1: CHANGES REQUESTED, 10 находок (записал лид);
  - `Services/device_hub/tests/test_c29_probe.py` — проба; тесты C11–C13 (итерация 3) **НЕ ПРОГНАНЫ**, прогноз:
    файл целиком 26 failed / 13 passed.
- Дизайн (коротко): `request_disconnect()` только у робота v2, зовётся через getattr из `cmd_device_disconnect` под
  `_workers_lock` до очереди; переход `disconnect_request(link_up)` — точка линеаризации, монотонный снимок
  `_stop_linked`, `_stopping`; счётчик `_disconnect_requests` (В1) — `connect_begin` → `"cancelled"`; супервизор
  пропускает connect при `is False` и не ставит desired True; `manager.connect` при отмене публикует `disconnecting`,
  не `error` (В3); jog/задание в окне — отказ `TEXT_DISCONNECTING` (В4); `_await_tlm` прерывается.

## Ответы владельца (реестр main `ce328c827`)

- В1 да; В2 — не в C-29, заведён C-31 (очередь на устройство), дизайн C-29 не опирается на общую очередь;
  В3 — исправить: connecting → disconnecting → disconnected, без error, с парной проверкой достижимости;
  В4 — запрещать jog и задание в окне, команда до робота не уходит.

## Следующие шаги

1. Прогнать итерацию 3 пробы (C11–C13), прогноз — в `C-29.probe.md`; только файлом, гейт `light`.
2. Новый вопрос владельцу **В5** (через координатора): программа (`admit_launch`), `return_job`, возвраты,
   `servo`/`do_set` в окне «Отключить» — В4 их не называет. Рекомендация teamlead: программу и `return_job` запрещать,
   `servo`/`do_set` — нет. До ответа DESIGN их не трогает (остаток О9).
3. Стадия 0 р.2 — тот же reviewer Opus через SendMessage (agentId ниже), по изменённым пунктам + В3/В4. Это итерация
   2 из 2; на 3-й — ESCALATION -> cto.
4. Затем: `C-29.blind-tester.md` (пишет лид), слепой tester Sonnet в worktree на `fcc1033b9`, developer Sonnet,
   инъекции, ревью задачи Sonnet, ревью ветки Opus, стенд (живая связь, симулятор v2 300 мс, порог 5,0 с).
5. Сторож `test_no_private_driver_state.py`: литерал числа файлов 44 → 45 (проба), со слепым тестером → 46.

## Находки координатора по плану 1.0 (взять при следующем касании планов, не срочно)

1. word-layout P3 / ORDER #10: посылка «angle_deg не доходит до robot_io» неверна — угол идёт как `place_rz_deg` →
   `place_rz` (word_layout/plugin.py:187-195, robot_io/plugin.py:178-182, jobs.py:70-77,146-149). Сузить P3.
2. T5.5 (plan.md:302): robot_io → CVT_JOB уже в коде с T3.7 (jobs.py:139-162); остаток — приёмка от линии и robot_draw.
3. Шапки T5.3f/T5.3h (plan.md:298,300) устарели: `60b99f210` и `6652ef88a` в main.
4. `docs/reports/2026-10-19_T5.6_stand.md:7` — jobs=0 от линии не разобран; гипотеза: пустой target_word в
   letter_robot_sim.yaml:311 (word_layout/plugin.py:138-140), не проверено.
5. Сим: 9 ячеек при first_y −200 вне P_WS_R_MAX 600 мм (delta_v2.yaml:638) — решение word-layout на умолчание рецепта.
6. Дефект C-32 (main `624e18aa8`): второй одинаковый диск подряд теряется (дедуп по букве), 1.0 · P0, word-layout P3.

## Открыто / ненадёжно

- DESIGN и R1–R9 — разбор чтением; гонки окна (б) без детерминированного теста (инъекция 19 — только чтение).
- Сторож `test_no_private_driver_state.py` красный по числу (45 ≠ 44) — проверка запрещённых полей пробой не выполнена.
- Не проверено, выходит ли поток поводка jog в C11–C13 до закрытия области теста.
- Порог стенда 5,0 с — расчёт, не замер.

## agentId (в новой сессии не возобновляются)

| роль | модель | agentId | токены |
|---|---|---|---|
| teamlead (проба + бриф р.1, р.2) | Opus | aa949182d1e782dbf | ~481k (205k + 276k) |
| reviewer, стадия 0 р.1 | Opus | ab23ad50b655074e6 | 213k |
