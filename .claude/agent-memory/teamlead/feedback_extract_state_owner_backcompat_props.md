---
name: extract-state-owner-backcompat-props
description: Вынос state-owner класса (watch.py/RegisterOps) — тесты дёргают приватные поля фасада, нужны property-делегаты, не только method-делегаты
metadata:
  type: feedback
---

Вынося аппарат-владелец состояния из фасада в отдельный класс (паттерн `backend_ctl/watch.py` WatchController, `registers.py` RegisterOps — композиция `self._x = X(self)` + back-ref `self._drv`), метод-делегатов НЕ достаточно: тесты и интроспекция читают ПРИВАТНЫЕ поля фасада напрямую (`drv._pending_commits`, `drv._rollback_journal`). После переноса состояния в новый класс эти атрибуты исчезают → `AttributeError`. Лечится back-compat `@property` на фасаде, возвращающим поле нового владельца (мутирующий доступ типа `.append()`/`== {}` работает — property отдаёт тот же объект).

**Why:** заход Task 2.1 (вынос regs) прошёл 511/514, 3 упали именно на `drv._pending_commits`. Method-делегаты (публичный API register_*) я сделал сразу, а приватные атрибуты-читатели проглядел.

**How to apply:** ПЕРЕД выносом — `grep -rnE "_поле1|_поле2" tests/` по КАЖДОМУ переносимому приватному полю. Грабля: `grep ... | grep -v "driver.py"` отфильтровывает и `tests/test_driver.py` (подстрока!) — читателей не видно. Фильтруй по точному пути (`grep -v "/driver.py:"`) или проверяй без фильтра. Инвариант приёмки «тесты зелёные с правкой ТОЛЬКО импортов» = сигнал, что приватные читатели должны остаться доступны на фасаде без правки тестов.

Смежное: аннотация back-compat property (`-> "deque[...]"`) под `from __future__ import annotations` всё равно ловится ruff F821, если тип больше нигде не импортируется — держи импорт (он реально «используется» аннотацией) с `# noqa: F401`. См. [[swap_stdlib_primitive_guarantees]].
