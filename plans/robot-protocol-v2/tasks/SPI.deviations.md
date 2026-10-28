# SPI хаба — отступления от брифа (`SPI.md`)

Фиксируются после реализации; полное обоснование — ADR-DH-012 (`Services/device_hub/docs/adr/ADR-DH-012.md`).

- **D4, строгий `command_table`.** Бриф: одноимённые `OpSpec` из двух источников должны быть равны по полям. Сделано
  строже: слияние строки возможно, только если у источников совпали `kind`, `route` и `key_from`, иначе `ValueError`
  (SPI.b/c1).
- **Допустимый вид — фабрика (SPI.c1b).** `VALID_KINDS` больше не источник истины: вид допустим, если для него
  зарегистрирована фабрика драйвера (`DeviceManager._check_kind`).
- **C-47 `executors` из топологии (SPI.d0).** Бриф считал ключ рабочим; `ProcessConfig` чертежа его отбрасывал. Добавлено
  поле и проброс в `as_generic_config` (framework, `process_manager_module/topology/blueprint.py`).
- **Литералы рисования по коду (SPI.c2b).** Описания `draw_square`, `draw_set_pen`, `draw_set_overlap` в А3 брали
  старые докстринги плагина; заменены по `robot_driver.py:765-804` (решение лида), `SPI.acceptance.md` и слепой тест
  обновлены этими тремя строками.
- **`driver_options` вместо `client_factory` в менеджере (SPI.f2).** SPI.seams.md предлагал фабрику клиента у драйвера
  v2; для тестов с драйвером от менеджера добавлены универсальные опции драйверов вида (`driver_options` /
  `set_driver_options`). Ограничение: опции на весь `kind`, v1 получит `client_factory` и упадёт `TypeError`.
- **`args_schema` по коду драйверов.** `?` у ключей ставился по коду (`jog`: `dx?`, `dy?`; `set_servo`: `on?`), а не по
  тексту описания.
