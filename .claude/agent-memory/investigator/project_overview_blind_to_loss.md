---
name: overview-blind-to-loss
description: РЕШЕНО 2026-08-23 (Task Т.2) — system_overview теперь несёт queue_data_loss/control_plane_loss в anomalies; запись оставлена как история болезни
metadata:
  type: project
---

**СТАТУС 2026-08-28: ЗАКРЫТО.** Исходная находка (2026-07-23) верна была для того момента:
`system_overview` строил anomalies только из `middleware_dropped`/`errors`, не читая
`queue_never_drop_loss_total`/`queue_system_evict_blocked`/`queue_data_evicted`.

Задача Т.2 плана `observation-port` (2026-08-23, `backend_ctl/STATUS.md` раздел «Task Т.2») это
закрыла: `overview.py` теперь различает `queue_data_loss` (вытеснение data-очереди получателя,
ожидаемое) и `control_plane_loss` (сорванная гарантия never-drop, строже) — два новых kind в
anomalies, не пересекаются с `router_dropped`/`router_errors`. Стражи: `test_overview_loss_counters.py`
(7, независимый тестер до реализации) + `test_t2_author_hazards.py` (7, автор). Полный
`backend_ctl/tests` на момент закрытия: 618→624 passed / 0 failed (регрессий нет).

**Why:** оставлено как памятка о классе дефекта («health зелёный при тяжёлой потере») — тот же
класс мог повториться в другом readback. Проверено чтением `README.md` (строка про Т.2 в описании
`system_overview`) и `STATUS.md` на HEAD `d37735c6` (2026-08-28) — не по памяти, а по свежему коду.

**How to apply:** не считать этот класс дефекта живым в backend_ctl без повторной проверки кода на
дату расследования. Если снова находишь «anomalies не видят X» — проверь СНАЧАЛА, не закрыто ли уже
похожей задачей (git log backend_ctl/overview.py).
