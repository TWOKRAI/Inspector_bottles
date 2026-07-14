---
name: seqlock-contention-semantics
description: Seqlock reader голодает при read_time ≈ write_period (всё дропает); тесты доставки нужны в режиме read<<write, а не пат-контеншн
metadata:
  type: project
---

Seqlock (Ф7 G.3b, `shared_resources_module/memory/format/buffer.py`): reader сверяет
generation до/после копии, при расхождении — drop. Корректность (torn=0) держится ВСЕГДА,
но **liveness зависит от соотношения read_time и write_period**.

**Не-очевидное:** под пат-контеншеном (writer без пауз, кадр ~3МБ, reader копирует столько же)
reader почти НИКОГДА не попадает в чистое окно → valid≈0, всё дропается. Это КОРРЕКТНО
(seqlock превращает гонку в drop, не в порчу), но ломает наивный тест `assert valid>0`.

**Why:** окно чтения reader'а (gen_before → копия → gen_after) почти всегда перекрывает
запись, если writer пишет непрерывно с периодом ≈ времени копии. В проде writer = камера
(~33мс период при 30fps) >> копия (~1-2мс) → чистых окон полно, доставка ок (smoke:
162/161 кадров при флагах on).

**How to apply:** тесты seqlock разделять на ДВА:
- heavy-contention (writer без пауз, большой кадр) → assert ТОЛЬКО `torn==0` (безопасность);
  valid тут законно ~0.
- light-contention (малый кадр + writer_gap ≥ несколько мс, read<<write) → assert `valid>0`
  (доставка не чёрная дыра). Плюс детерминированные roundtrip-тесты без гонки.
Устойчивое отставание consumer'а (read стабильно ≥ write) лечит НЕ seqlock, а frame-pool
G.4 (владение + drop-на-источнике). Связано: [[frame-pool-owns-liveness]].
