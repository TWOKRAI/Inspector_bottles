# R2-S1d: слепая приёмка до реализации (tester, 2026-11-27)

**Статус:** DONE_WITH_CONCERNS. Дерево `r2-stopgate-tester`, detached `9c0c32f28`. Не коммитил.
**Источник:** `plans/robot-protocol-v2/tasks/R2-S1d.md` («Приёмка», «Дизайн») и
`docs/reviews/2026-11-27_task-R2-S1a-cto.md`.
**Файл тестов:** `Services/device_hub/tests/test_r2s1d_stop_gate_acceptance.py` (43 теста).

## Прогон

Импорт из этого дерева (напечатан один раз пробой):
`Services from D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.claude\worktrees\r2-stopgate-tester\Services\__init__.py`

Команда (класс `light`, из корня дерева):

```
PYTHONPATH="$(cygpath -w "$PWD")" PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 bash <main>/scripts/machine_gate.sh light \
  inspector-bottles-5d <main>/.venv/Scripts/python.exe -m pytest \
  Services/device_hub/tests/test_r2s1d_stop_gate_acceptance.py -q --tb=short -p no:cacheprovider
```

Итог до реализации: `27 failed, 16 passed, 1 warning in 97.63s`. `ruff check` и `ruff format --check` чистые.
Набор красных в двух прогонах подряд совпал (во втором меньше на один случай, который я убрал из файла).

Полные выводы (scratchpad сессии, каталог
`C:\Users\INNOTECH\AppData\Local\Temp\claude\65f734dde6ea3dc7\96295c47-68c9-45a7-997e-358c9fc73c33\scratchpad`):
`r2s1d_red_run3.log` (итоговый файл), `r2s1d_gate_bypass.log`, `r2s1d_injection.log`.

## Стенд

Настоящий `DeviceHubPlugin` (`configure`, `start`), настоящий `WorkerManager` (supervisor и тик идут своими потоками),
команды берутся по таблице `plugin.commands`. Робот: ядро sim v2 (A6: v1) за `LoopbackServer` на `127.0.0.1`.
Один дублёр: получатель публикаций вместо `state_proxy`. A7 идёт на стенде драйвера из R2-S1a.

«Робот встал» проверяется так: кадр `STOP_REQ`, `TLM_STOP_ACK` равен значению этого кадра, остановка не позже 1 с,
сторож sim не сработал, путь не дошёл до цели.

## Таблица приёмки (сейчас, без реализации)

| Id | Тесты (случаев) | Сейчас | Причина |
|----|-----------------|--------|---------|
| A1 | `test_a1_stop_after_failed_repeat_connect_is_written_and_robot_stops` (2) | красные | затвор: «Устройство 'rv2' не подключено» |
| A2а | `test_a2a_stop_before_successful_reconnect_is_written_and_robot_stops` (4) | красные | затвор, кадров STOP `[]` |
| A2б | `test_a2b_one_press_on_unnoticed_drop_is_ok_with_one_stop_frame` (4) | красные | ответ-ошибка WinError 10053 (FIN) / 10054 (RST) |
| A3 | `test_a3_stop_after_deliberate_disconnect_is_refused_without_frames_or_new_tcp` (2) | зелёные | отказывает затвор |
| A4 | `test_a4_never_confirmed_firmware_gets_no_stop` (4), `test_a4_wrong_firmware_after_confirmed_one_gets_no_stop` (2) | зелёные | отказывает затвор |
| A5 | `test_a5_dead_link_stop_is_error_in_time_and_stays_unconfirmed` (4) | красные | `tick_noticed`: текст «не подтверждён» опубликован 0 раз; `untouched`: в ответе нет `error` |
| A5 | `test_a5_each_press_on_dead_link_publishes_unconfirmed_once` (1) | красный | опубликовано 0 раз |
| A5 | `test_a5_guard_timed_out_stop_write_is_not_written_again` (1) | зелёный | повтора сейчас нет (сторож) |
| A5 | `test_a5_measure_second_device_command_delay` (1) | зелёный | измерение, не приёмка |
| A6 | `test_a6_v1_abort_without_link_is_refused_with_zero_writes` (2) | зелёные | отказывает затвор |
| A7 | `test_a7_tick_first_stop_during_job_is_on_the_wire` (4) | красные | кадров STOP `[]`; порядок навязан (`waits == [True]`) |
| A8 | `test_a8_motion_command_when_not_ready_is_refused_with_zero_frames` (2) | зелёные | затвор для этих команд остаётся |
| A9 | `test_a9_stop_between_transport_close_and_open_is_written` (2) | красные | затвор; окно навязано (сокет закрыт, не открыт) |
| A10 | `test_a10_stop_during_repeat_probe_is_on_the_wire` (2), `test_a10_stop_after_probe_failed_on_io_is_on_the_wire` (2) | красные | затвор, кадров STOP `[]` |
| A11 | `test_a11_repeat_disconnect_after_failed_jog_stop_says_nothing_again` (2) | красные | второе отключение объявляет ещё раз (2 вместо 1) |
| Дизайн 3, 8 | `test_refusal_without_driver_has_message_and_error_and_neutral_text` (2) | зелёные | отказывает затвор |

Бриф допускал, что A11 частично зелёный. Здесь оба случая красные.

## Почему зелёные не пустые

Проверил черновыми подменами в процессе (файлы только в scratchpad, дерево не тронуто).

1. Снят ТОЛЬКО затвор менеджера для `stop` и `abort` (выборка 18 случаев): `16 failed, 2 passed`.
   - A3 красный: ответ `{'message': 'Клиент не подключён'}` без `error`.
   - A4 красный: ответ без `error`.
   - A6 красный: вместо «Устройство 'rv1' не подключено» приходит текст исключения.
   - «Драйвер не создан» красный: «журнала нет: драйвер не создан», без `error`.
   - A2а остаётся красным: «Транспорт робота не подключён». Одного затвора мало.
   - A1 становится зелёным целиком. Это значит, что проверки после первого `assert` (кадр `[2]`, эхо, остановка)
     исполняются и проходят на настоящем sim.
2. Вторая запись стопа после любой ошибки: сторож A5 краснеет, кадры `[6, 6, 10, 10]`.
3. `servo` и `jog_step` пущены мимо затвора: оба случая A8 красные («нет связи с роботом»).

Замер сейчас: при таймауте записи STOP команда идёт 2,016 с, кадры `[6, 6]` (повтор pymodbus тем же значением).
Задержка второго устройства сейчас 0,000 с, потому что СТОП по мёртвому сокету падает мгновенно. Число для отчёта
надо снять заново после реализации: оно печатается строкой `MEASURE:` (`pytest ... -rP`).

## Допущения о спецификации

1. `robot_abort` посылается с `mode: 2` (HARD). GUI шлёт `mode` 1..3. Без `mode` это SOFT, а SOFT посреди хода sim
   откладывает до цели.
2. «`STOP_REQ` на проводе» проверяется строже: уровни ровно `[2]`, один кадр на нажатие.
3. Ответ `ok` требуется в A1, A2б и A9. Для A9 это из дизайна п.3 (запись прошла, эхо не прочиталось: `ok`).
   В A2а и A10 ответ не проверяется, только провод и робот.
4. «Любой отказ несёт `message` и `error`» применён и к v1 (A6), а не только к v2.
5. «Опубликован один раз на нажатие»: счёт точного литерала в `devices.state.<id>.last_error`.
6. «Следующая неудачная попытка connect» в A5: команда `device_connect`.
7. A4 «0 кадров»: ноль ЗАПИСЕЙ. Чтения переподключения тиком идут своим чередом.
8. A8 «0 кадров»: ноль записей в регистры команд, буфер программы и аренду jog. Пульс не считается.
9. A11: на втором отключении также нет кадра STOP и нового TCP. Это из правила cto, не из строки A11.

## What I interpreted rather than followed

- A7 идёт не через команды хаба: речь о `disconnect` и `request_stop`, а не о `robot_stop`. Взял `_v2()` и
  `_force_order` из тестов R2-S1a и зову методы драйвера.
- A1: взял вариант `on_connect.servo: false` и занятый робот, без вброшенного сбоя.
- «Тик включён»: в A2б, A5 (`untouched`, «раз на нажатие», сторож) и A11 `poll_interval_s = 30`. Тик идёт, но после
  первого такта обменов не делает. Иначе нельзя гарантировать «после обрыва обменов не было».
- «Связь вернулась» в A2а и A8: сервер принимает новые соединения, а первая проба переподключения получает
  ответ-исключение. Дальше идёт порог 2 с.
- Задержка второго устройства: два метода команд плагина подряд в одном потоке. Настоящего роутера команд нет.
- Драйвер читается через приватный `plugin._manager.get_driver` (`is_connected`, `stop_unconfirmed`, `transport`).
- Тест лежит в `Services/`, а импортирует из `Plugins/` (так требуют FILES и «команды как из приложения»).
  `sentrux check` я не запускал.
- Тест «драйвер не создан» взят из дизайна п.3 и п.8, в списке A1..A11 его нет.

## What I left open / unreliable

- Строки после первого красного `assert` в A2а, A2б, A5, A9, A10, A11 ещё не исполнялись ни разу. Там возможна
  ошибка теста, которая проявится только после реализации. Сквозь затвор проверен только путь A1.
- «Ноль записей» в A3 и A4 не видел красным: под подменой затвора они падают раньше, на ключе `error`.
- Время файла: 97,6 с до реализации. После реализации тесты пойдут дальше и дольше. Оценка около 2 минут, не измерено.
- Пороги `< 0,5 с` (A2б) и `< 3 с` (A5) зависят от нагрузки машины (во время работы могло быть открыто тяжёлое окно).
- A5 `tick_noticed` ждёт, пока первая попытка тика кончится, и жмёт в порог 2 с. Нажатие ВО ВРЕМЯ идущего connect
  тика (замок устройства занят до таймаута) не проверено. В таком чередовании команда может выйти за 3 с.
- Барьеры A9 и A10 подменяют `ModbusDevice.connect` и `read_registers`. Если реализация уведёт открытие или пробу в
  другие методы, тест упадёт на предпосылке (не позеленеет молча).
- A9 покрывает только окно в `connect`. Путь `_link_lost` держит только A7.
- Коды 10053 и 10054 относятся к Windows. Настоящий робот и сторонние ОС не проверены.

memory hits: `search.py robot stop gate tick heartbeat sim` ->
`docs/claude/memory/feedback_snapshot_of_a_sim_record_races_its_ticker.md` (прочитано только описание).
