# SPI хаба — стадия 0 р.1: хвостовой раздел (перенесён дословно из `SPI.stage0.md`, размер файла > 32 КБ)

## Что оставил открытым / ненадёжным
1. Тесты не гонялись: ни REDS, ни «зелёные до и после» не воспроизведены. Вердикт по чтению; строки по `9b6645546`.
2. «`update_handler_metadata` заменяет словарь» подтверждено чтением (`exact_match.py:89`, README и ADR command_module), не прогоном. «Роутер без `metadata.executor` не передаёт `reply`» — по `router_manager.py:1359-1371`; живой путь IPC не проверялся.
3. Влияние ключа `args` на рантайм-свод `CAPABILITIES`: `_command_dump` (`backend_ctl/dump_capabilities.py:47-60`) читает `name / description / tags / params_schema`, `args` — нет; но карточку строит `builtin_commands.py:873`. Надо прогнать дамп.
4. Список «не в очередь» (п.6) — мои 11 имён по смыслу, не по анализу кода: `stop, abort, jog, jog_hold, jog_release, jog_step, jog_abort, draw_abort, program_abort, servo, set_servo`; `do_set`, `clear_queue`, `toolchange` — решение лида.
5. Потокобезопасность `_safe_call` (`self._reg.commands_ok += 1`) при вызове с потоков исполнителя не проверена (у `RobotDataStore` замки по ключам, `store.py:202`, — только объявление).
6. Загрузка `executors: {device_io: {max_workers, max_pending}}` без `kind` / `serial` не проверена (`ExecutorManager._create`); 4 / 64 ничем не измерены.
7. Шов конструктора (п.9) не примерен к 34 чтениям после `connect` (клиент создаёт драйвер, `driver.py:338-339`); возможен `client_factory`. Объём SPI.f — оценка.
8. C-45: границы `base.py:1700-1727` — со слов лида (в моём дереве `cmd_set_config` на :1695-1720). «generic_modbus на bridge невозможен» — чтением `generic_modbus_driver.py:63`, без прогона.
