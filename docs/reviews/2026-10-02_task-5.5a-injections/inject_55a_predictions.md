# 5.5A — предсказания до прогона (лид)
База (HEAD c8a1853f4, 4 файла тестов): 1 failed (test_second_sender_..., часть B), остальные зелёные. collected — число.
I1 убрать `if client in self._dead: break` → +2 красных: test_slow_reader_does_not_stall, test_session_closed_after_handler_on_write_failure.
I2 as_posix() → str(value) → +1: test_path_default_goes_as_str.
I3 field_meta: вернуть logging.getLogger на уровне модуля → +1: test_no_bare_stdlib_logger_outside_whitelist.
I4 sdk_reader: вернуть logging.getLogger → +1: тот же тест.

## Итог прогона (лид, HEAD c8a1853f4 ветки fix/t55-green-main)
- BASE: `1 failed, 84 passed, 2 skipped` — красный test_second_sender_to_stuck_socket_does_not_wait_again (часть B), как предсказано.
- I1: 3 failed — + test_slow_reader_does_not_stall_other_clients, test_session_closed_after_handler_on_write_failure_path. **Совпало.**
- I2: 2 failed — + test_fieldinfo_path_default_goes_as_str. **Совпало.**
- I3: **пустая** — вывода нет: заплата (строки перед модулем) сломала сбор тестов. Свойство «field_meta без голого логгера» инъекцией НЕ доказано. Переделать: заплату ставить после импортов модуля.
- I4: 2 failed — + test_no_bare_stdlib_logger_outside_whitelist. **Совпало.**
- I3 v2 (заплата после `from __future__ import annotations`): `2 failed, 83 passed, 2 skipped` — + test_no_bare_stdlib_logger_outside_whitelist. **Совпало.** Свойство «field_meta без голого логгера» доказано. Урок v1: строки до `from __future__` ломают модуль целиком — сбор пуст, а не «тест зелёный».
