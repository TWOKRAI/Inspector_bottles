---
name: overview-blind-to-loss
description: system_overview аномалии не читают never_drop_loss_total/evict_blocked/data_evicted — health зелёный при тяжелейшей потере
metadata:
  type: project
---

`backend_ctl/overview.py` `system_overview` (первая команда сессии, «вся картина») строит anomalies ТОЛЬКО из `middleware_dropped` и `errors` (строки 216-221). Новые поля `RouterStats` — `queue_never_drop_loss_total` (безвозвратная never-drop потеря, e038a747), `queue_system_evict_blocked` (тот самый шторм, что душил GUI — [[project_gui_system_queue_storm]]), `queue_data_evicted` — в аномалиях НЕ участвуют (подтверждено grep: единственные потребители — probes/ и protocol.py).

**Why:** e038a747 вынес never_drop_loss_total в интроспекцию с формулировкой «самая тяжёлая потеря системы доступна интроспекции» — но потребитель здоровья её не читает. Счётчик реально инкрементируется (manager.py:431), сигнал настоящий; дыра — в агрегации.

**How to apply:** если правят truthfulness backend_ctl — добавить kind'ы `never_drop_loss`/`evict_blocked`/`data_evicted` в overview.py по образцу `router_dropped`. Пока не добавлено — не полагаться на «anomaly_count=0» как на «потерь нет».
