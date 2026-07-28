---
name: feedback-config-delivery-shape-differs
description: Оркестратор получает конфиг плоским, ребёнок — весь proc_dict; одно и то же get_config работает у одного и молчит у другого
metadata:
  type: feedback
---

`svc.get_config("ключ")` работает на ProcessManager и **молча возвращает None**
на дочернем процессе. Причина: `spawner` мержит `orchestrator_config` в корень
конфига оркестратора (плоско), а `process_runner` отдаёт ребёнку
`custom["process_config"]` — ВЕСЬ `proc_dict`, где прикладные ключи лежат под
`config.`. Читать надо `read_process_config(svc, key)`
(`process_module/configs/observability_layers.py`): плоский ключ → затем
`config.<ключ>`.

**Why:** отказ бесшумный и выглядит как «фича не настроена». Так уже умерла
починка находки C задачи 2.2: `telemetry_override` читался плоско и на детях
не срабатывал никогда — при 26 зелёных тестах, потому что фейковый `svc`
в тестах был плоским словарём.

**How to apply:** любой новый per-process ключ в `proc_dict["config"]` читать
через `read_process_config`, а в тесте подавать ОБЕ формы доставки. Фейк
`get_config` обязан иметь сигнатуру `(key, default=None)` — однопараметрический
роняет вызывающих `TypeError` вместо того, чтобы их проверять. См.
[[feedback-plausible-is-not-verified]], [[feedback-default-path-must-match-publisher]].
