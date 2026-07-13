---
name: live-harness-tests
description: Правила live-тестов на BackendHarness — свой уникальный порт и разворачивание envelope ответа driver'а
metadata:
  type: feedback
---

Live-тесты (`harness_smoke`) на реальном бэкенде — две неочевидные ловушки, стоившие времени в Ф2.1.

**1. Свой уникальный порт ≥8770, НЕ общий `headless_backend`.**
- **Why:** общая session-фикстура `headless_backend` (backend_ctl/tests/conftest.py) сидит на порту 8765. Если рядом живёт другой бэкенд/остаток на 8765, driver молча цепляется к ЧУЖОМУ коду — тесты зелёные/красные по чужому бэкенду, health/новые команды «не видны». Симптом: `Captured stdout setup` пуст (свежий бут не печатал баннер), ответы без новых полей. Это проявление [[project-concurrent-backends-trap]].
- **How to apply:** для теста нового backend-поведения заводи СВОЮ `@pytest.fixture(scope="module")` с `BackendHarness(with_base=True, port=<уникальный ≥8770>)`. Debug-скриптом подтверждай фичу на своём порту прежде, чем винить код.

**2. Ответ команды ДОЧЕРНЕГО процесса приходит полным router-envelope.**
- **Why:** `driver.request()` делает `response.get("result", response)` — один уровень. Ответ команды дочернего процесса (напр. `preprocessor`) приходит как `{type:response, success:True, result:{...handler-return...}}` — верхний `success` есть, но нужные поля (`health`, `errors`, `sub_id`) лежат ВНУТРИ `result`. Существующие driver-тесты проходят случайно, читая верхнеуровневый `success`. Чтение `res.get("health")` вернёт None.
- **How to apply:** в live-тестах разворачивай: `inner = res["result"] if isinstance(res.get("result"), dict) else res`, читай поля из `inner`. См. helper `_result()` в `backend_ctl/tests/test_health_live.py`.

**3. Триггер отказа без железа.** Для acceptance «ошибка видна через driver» используй диагностическую команду `health.report` (BuiltinCommands) — детерминированный впрыск health-события, не дожидаясь реального отказа камеры. Снапшот — `health.status`.
