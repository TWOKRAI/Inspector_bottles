---
name: feedback-facade-is-a-whitelist-not-a-passthrough
description: "Поле в схеме менеджера не делает ручку управляемой — конфиг идёт через фасад-белый-список, и чужой ключ он отбрасывает молча"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 37ab2dae-58c0-4b18-8edf-ace7ecc6a1f2
  modified: 2026-08-11T12:34:54.658Z
---

Задача 3.4 (2026-08-11). Ручка `log_line_max_bytes` объявлена в `StatsManagerConfig`,
тест «менеджер читает конфиг» зелёный — а из конфига приложения ручка не управлялась
вовсе. Дорога к плоскости идёт через **фасад** `ObservabilityStatsConfig`
(`process_module/configs/observability_config.py`), который транслирует ТОЛЬКО
перечисленные поля: `expand_observability` собирает `stats = {...}` руками, и ключа,
которого там нет, для менеджера не существует.

Нашёл это **живой прогон**, не тесты: `config_reload_verified` вернул `failed` на всех
восьми процессах («ключ не выжил round-trip»), тогда как юнит дёргал `StatsManager`
напрямую, минуя дорогу. Закрывается тремя точками сразу: поле в фасаде, прокид в
`expand_observability`, ключ в `observability_readback` — иначе применение нечем
подтвердить, и `verified` останется `unverifiable`.

**Why:** тест на своём уровне ничего не знает о дороге. Зелёный юнит + мёртвая ручка —
это хуже отсутствия ручки: конфиг её принимает, никто не жалуется, эффекта нет.

**How to apply:** добавляя ручку менеджеру наблюдаемости, проверь ТРИ точки, а не одну:
схема менеджера → фасад `Observability*Config` + `expand_observability` → readback. Тест
проводки писать на `expand_observability`, а не на менеджере. Сверять живым
`config_reload_verified`: `failed` тут означает «ключ отброшен», а не «значение не то».
Родня — [[feedback-read-the-key-from-the-section-already-travelling]],
[[feedback-config-delivery-shape-differs]], [[feedback-port-wire-is-not-a-process-route]].
