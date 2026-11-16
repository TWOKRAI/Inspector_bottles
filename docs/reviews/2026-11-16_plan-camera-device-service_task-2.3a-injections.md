# 2.3a — прогнозы break-injection лида (записаны ДО прогона)

Тесты: `test_plugin_base.py` (слепой tester, 23 прогона), `test_plugin_base_hazards.py` (автор, 10), `test_slice_plugin.py` (1.8, 6). Мутации — в `Services/camera_device/plugin_base.py` / `session.py`, откат `cp`. Прогноз = минимальное множество красных; всё остальное должно остаться зелёным.

| # | Мутация | Прогноз |
|---|---|---|
| I1 | `_plan`: `build_plan(type(reg), rest_values, rest_bindings)` -> `…, bindings)` (формула N2) | красные: `test_план_run_и_rest_из_register`, `test_план_строится_при_каждом_старте`; `take_device` в `test_slice_plugin.py` отвечает error |
| I2 | убрать строку `"trigger_period_ms": reg.trigger_period_ms,` из `rest_values` | ВЫЖИВАЕТ (все зелёные): отклонение developer'а (1) тестами не покрыто — находка; ловится только `rest_trigger_source="SelfTrigger"` |
| I3 | `session.set_cycle(ident, run, rest)` в `cmd_take_device` -> `pass` | красные: `test_план_run_и_rest_из_register`, `test_план_строится_при_каждом_старте` |
| I4 | в `produce()` перенести три строки `self._frames += 1`/`self._reg.frames = …`/`publish_metric` ПЕРЕД `try` | красный: `test_форма_кадра_по_pixel_format_битый_кадр_отбрасывается` (случаи с `produced=False`: счётчик вырос) |
| I5 | `_frame_array`: убрать проверку `len(raw.data) != expected` вместе с `raise` | ВЫЖИВАЕТ (эквивалентная мутация: `reshape` сам бросает `ValueError`, он ловится в `produce`); красный только если тест сверяет текст причины |
| I6 | `configure`: убрать проверку `watchdog_s <= timeout_ms/1000` | красные: две ветки `test_watchdog_…` (недопустимые значения), допустимая — зелёная |
| I7 | `bindings()` -> `return {}` | красные: `test_план_run_и_рест…`, `test_план_строится_при_каждом_старте` (журнал без `set_param`); `test_хуки_базы_…` зелёный (подкласс переопределяет `bindings`) |
| I8 | `session.set_cycle`: удалить `self._ident = ident` | ВЫЖИВАЕТ: правка `device_serial` между циклами (Р12, вердикт cto MED) тестами не покрыта — нужен тест |

Выжившие мутации (I2, I5, I8) — находки: I2 и I8 требуют тестов (I8 — обязательно), I5 — эквивалент.

## Наблюдено (Haiku, коммит 7d16bb64e; базовая линия 39 passed) — сравнение лида

| # | Факт | Прогноз совпал? |
|---|---|---|
| I1 | 18 failed (планы, идентичность, хуки, срез 1.8, хазарды) | да, факт шире прогноза |
| I2 | 0 failed | да (выжила; закрыта тестом `test_rest_selftrigger_пишет_период_run`, красный при откате) |
| I3 | 7 failed (планы, хуки, 2 хазарда) | да |
| I4 | 2 failed (`rgb8_короткий_буфер`, `неизвестный_формат`) | да |
| I5 | 0 failed | да (эквивалентная мутация: `reshape` сам бросает `ValueError`) |
| I6 | 2 failed (`меньше_таймаута`, `равен_таймауту`) | да, ровно |
| I7 | 6 failed; `test_хуки_базы…` зелёный | да |
| I8 | 1 failed (`test_set_cycle_при_device_held…`) | НЕТ: прогноз «выживает» неверен — мутацию убивает хазард уровня сеанса; сквозной тест Р12 (`test_правка_device_serial_между_циклами…`) добавлен по ревью и тоже красный при откате |
