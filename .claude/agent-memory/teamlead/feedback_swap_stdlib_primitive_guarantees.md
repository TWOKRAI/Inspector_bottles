---
name: swap-stdlib-primitive-guarantees
description: Замена stdlib-примитива своим — перечисли и покрой тестами «бесплатные» гарантии оригинала, иначе тихая деградация
metadata:
  type: feedback
---

При замене stdlib-примитива на самодельный (C6e: `ThreadPoolExecutor` →
`WorkerPoolExecutor` поверх worker_module) — ПЕРЕЧИСЛИ гарантии, которые оригинал
давал бесплатно, и покрой КАЖДУЮ регресс-тестом ДО ревью. Иначе они молча теряются.

**Why:** Fable-ревью C6e вернул CHANGES REQUESTED — концепция (обёртка, контракт-тест,
grep=0) была верна, но наивный пул потерял то, что `ThreadPoolExecutor` давал даром:
- `future.cancel()` — не начатая задача НЕ исполнялась; у меня истёкшие по timeout
  задачи оставались в очереди и исполнялись позже → кросс-кадровая контаминация
  side-state (`last_detections` на shared-объекте) + backlog + RSS;
- `_WorkItem.run` ловит `BaseException` — у меня `except Exception` пропускал
  BaseException → LOOP-воркер умирал навсегда, `result()` возвращал None как «успех»;
- изоляция экземпляров — глобальные имена `chain_pool_i` в общем реестре → два пула
  сносили воркеров друг друга; `create_worker`=False игнорировался (тихий пустой пул);
- `submit` после shutdown → RuntimeError (у меня молча терялась задача);
- маскировка: `except TimeoutError` перехватывал бизнес-TimeoutError шага.

**How to apply:** для любого swap низкоуровневого примитива (пул/очередь/локов/сокета)
выпиши контракт-инварианты оригинала (cancel, exception-capture широта, изоляция,
after-close поведение, точность ошибок) — это acceptance, не «потом». Многие находки
лечатся ОДНИМ связным редизайном (у меня — сентинелы вместо poll закрыли 4 сразу),
не точечными заплатками. См. [[test-params-hide-defect-window]] (прод-значения в тестах),
[[rs7-workers-semantics]] (C6e-контекст).
