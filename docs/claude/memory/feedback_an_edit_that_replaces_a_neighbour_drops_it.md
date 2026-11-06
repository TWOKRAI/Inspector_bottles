---
name: an-edit-that-replaces-a-neighbour-drops-it
description: "Вставка нового метода в базовый класс через Edit, где old_string захватил соседний метод, а new_string его не повторил, молча удаляет соседа (C-60: пропал штатный ProcessModulePlugin.shutdown) — тесты автора и ревью зелёные, красным стал только полный suite / an Edit that inserts a method by replacing its neighbour silently deletes the neighbour; check the diff for removed lines"
module: [process_module]
mechanism: [guards, test-assertions]
role: teamlead
metadata:
  type: feedback
  last-verified: 2026-11-01
---

При добавлении хука `request_stop` в `ProcessModulePlugin` исполнитель заменил блок `def shutdown(...)` новым методом вместо вставки рядом: штатный `shutdown` (default no-op) исчез. Плагин без своего `shutdown` падал в `_do_shutdown` с `AttributeError`. Не заметили: тесты автора (R1–R5, H1–H8), приёмка слепого тестера, два раунда ревью, матрица инъекций I1–I11 — у всех тестовых плагинов `shutdown` свой. Поймал полный framework suite: 5 красных в `test_f2_acceptance_writer_retraction.py` + вложенный `test_declarations_leak_order_independence`.

**Why:** радиус «свои тесты + соседние файлы» не содержит плагина на одних умолчаниях базы; ревьюер читает дифф с плюсами и не видит единственную минус-строку (2026-11-01, C-60).
**How to apply:** после правки базового класса — `git diff <база> -- <файл> | grep '^-[^-]'`: любая непреднамеренно удалённая строка есть дефект; в задачу — сторож «плагин на одних умолчаниях базы закрывается чисто» (C-60: H9) и инъекция «удалить умолчание»; радиус правки базового класса — весь каталог модуля, а до merge — framework suite.

Related: [[feedback_do_shutdown_on_unbooted_plugin_is_a_silent_noop]], [[feedback_injection_zero_may_mean_the_guards_were_not_collected]]
