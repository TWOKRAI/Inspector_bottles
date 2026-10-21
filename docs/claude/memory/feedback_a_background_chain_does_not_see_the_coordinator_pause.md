---
name: feedback_a_background_chain_does_not_see_the_coordinator_pause
description: "Фоновая цепочка агента (background chain, nohup script) не видит паузу координатора (coordinator pause): шаг читает machine.lock сам; classify до окна — по machine_gate_timed.txt"
mechanism: [test-infra, process]
metadata:
  type: feedback
---

**Ловушка.** Пауза координатора доходит до агента сообщением, а сообщение доходит только на
следующем шаге инструмента. Developer T5.3f f2 запустил `chain.sh` (`nohup`, перенос модуля →
коммит → два набора → следующий модуль). Цепочка — один долгий вызов: пауза пришла в 20:55,
а в 21:08 цепочка стартовала ещё один прогон `Services/device_hub/tests`; стенд полосы Ф ждал,
пока лид не убил `chain.sh`/`vgo.sh`/`both.sh` по PID (21:11). Замер: 2026-10-20, сессия
inspector-bottles-09.

Вторая ловушка того же дня: `machine_gate.sh classify` показал `medium pytest_module_dir` для
`Services/device_hub/tests`, а путь стоит в `scripts/machine_gate_timed.txt` — gate отказал
(exit 75) без окна, f1 ждал окна.

**Как применять.**
- В бриф developer/tester на общей машине: «никаких фоновых цепочек; один прогон на шаг; перед
  каждым прогоном читать `machine.lock` — нет своего `window:` или в нём «ПАУЗА» → стоять».
- Перед запросом окна сверять путь с `scripts/machine_gate_timed.txt`, не только с `classify`.
- Ожидатель «pytest 0» — фоновый `until`-цикл по `Get-CimInstance` с фильтром `pytest`.
