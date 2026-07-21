---
name: project_backend_ctl_socket_bypasses_mw
description: Команды через сокет backend_ctl не проходят receive-мидлварь роутера (ни fence, ни контракты) — драйвером нельзя проверять фильтры приёма
metadata:
  type: project
---

`RouterManager.receive()` опрашивает каналы через `_poll_all_channels(input_channels_only=True)`, а тот пропускает только каналы с префиксом `<process_name>_` (`ProcessManager_system`, `_data`, `_local`). Канал `backend_ctl` (type=socket) под префикс не подходит и в опрос не попадает — значит команды драйвера **не проходят** `_recv_mw`: ни fence-фильтр (ADR-PMM-014), ни contract-check их не видят.

**Why:** попытка 2026-07-21 сделать fencing-тест детерминированным провалилась именно из-за этого — билет со специально устаревшим `_fence`, отправленный через `drv.request()`, дошёл до обработчика и получил ответ ОДИНАКОВО при `FW_FENCE` вкл и выкл. Признак того, что фильтр его не судил вовсе, а не того, что фильтр сломан.

**How to apply:** нельзя проверять receive-мидлварь (fence, контракты) инъекцией через backend_ctl — только через настоящий peer-канал процесса. Обратная сторона: команды драйвера намеренно вне этих проверок (операторский инструмент); если понадобится их гейтить — это отдельное решение, не «оно и так работает». См. [[project_backend_ctl_signal_integrity]], [[project_fencing_test_race]].
