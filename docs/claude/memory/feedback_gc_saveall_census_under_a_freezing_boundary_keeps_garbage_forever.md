---
name: gc-saveall-census-under-a-freezing-boundary-keeps-garbage-forever
description: "Перепись Qt-мусора колбэком gc.callbacks с DEBUG_SAVEALL под политикой T1 делает циклы бессмертными: граница теста T1 = collect + gc.freeze, очистка gc.garbage внутри сборки, затем freeze уводит объекты в постоянное поколение; refreeze=False не лечит (следующая сборка снова кладёт те же объекты в gc.garbage); G5 вынесен из 0.5 / a SAVEALL garbage census under a freezing gc boundary keeps garbage immortal"
module: [process_module]
mechanism: [concurrency, probes]
role: reviewer
metadata:
  type: feedback
---

Задумка G5 (DESIGN §3): `gc.callbacks`, фаза `start` — `set_debug(DEBUG_SAVEALL)`, фаза `stop` — посчитать `gc.garbage`, очистить. Ревью спека р.1: на чистом `gc` сборка без freeze освобождает циклы следующей сборкой. Ревью р.2 (отозвал своё «сверено»): под T1 граница теста — `collect_now(refreeze=True)` (`gc_discipline.py:309-310`), сразу `gc.freeze()` → очищенные циклы переносятся в постоянное поколение: `collect()` после freeze освободил 0, после `gc.unfreeze()` — 6. С `refreeze=False` каждая следующая сборка снова кладёт те же 3 объекта в `gc.garbage` (на трёх границах одни и те же объекты, `__del__` один раз). Остаётся ещё путь заморозки по сроку (`_freeze_due()`; 29 мест `rearm/suspend/unfreeze` в тестах).

**Why:** SAVEALL не разрывает циклы (`tp_clear` не зовётся): объекты живут, пока их держит `gc.garbage`; сборка же с включённым флагом кладёт их обратно.

**How to apply:**
- Счётчик Qt-мусора на тест (храповик) строить на счётчиках T1 (`foreign_collections`, `collected_objects`) и режиме `census` пробы, не на `SAVEALL`-колбэке внутри сборки владельца.
- Если перепись всё же нужна: SAVEALL на одну сборку из двух (посчитать, очистить, следующую пропустить), учёт по `id()`, и политика без freeze на время переписи — вместе с владельцем T1, не в стороннем плагине.
- Проверять не только «следующая сборка освобождает», но и «сборка владельца с freeze освобождает».

Related: [[feedback-tests-of-process-global-state-run-in-own-process]]
