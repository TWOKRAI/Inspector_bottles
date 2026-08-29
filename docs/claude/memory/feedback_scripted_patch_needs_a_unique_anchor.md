---
name: feedback-scripted-patch-needs-a-unique-anchor
description: "Скриптовая замена по якорю обязана падать при count != 1 — неуникальный якорь режет соседнюю функцию молча, и ближайший гейт этого не видит"
metadata:
  node_type: memory
  type: feedback
  originSessionId: e319bad7-fb0b-405c-a740-60766c4d8516
  modified: 2026-08-29T14:38:27.975Z
---

`s.replace(anchor, ...)` в заплатке/инъекции обязан стоять после `assert s.count(anchor) == 1`.
`>= 1` — не проверка: замена уйдёт в ПЕРВОЕ вхождение и разрежет то, что вокруг второго.

Замер 2026-08-29 (Ф0.1 `observability-closure`): вставлял фикстуру в `test_plugin_manifest.py`
по якорю `PluginRegistry.clear()`. Якорь встречается в соседней фикстуре `_clean_registry`
дважды — до и после `yield`. Вставка разрезала её: хвост (`yield` + второй `clear()`) прилип к
новой фикстуре, pytest отказал «fixture function has more than one yield», 32 ошибки teardown.

**Ловил только ОДИН гейт из трёх.** Корневой (7232 passed) и `modules/tests` (93 passed) прошли
зелёными: `process_module/plugins/tests` не входит ни в тот, ни в другой. Увидел только
`scripts/run_framework_tests.py`. То есть «зелёный ближайшего прогона» после скриптовой правки
не значит ничего — см. [[project_root_gate_misses_framework_modules]].

**Why:** порча синтаксически валидна, поэтому ни ruff, ни импорт её не заметят; она проявляется
только на сборе тестов в том дереве, куда попала.

**How to apply:** в любом скрипте, который правит чужой файл текстом, — `assert count == 1` перед
каждой заменой; после правки гонять ТОТ гейт, в чей периметр попадает файл, а не ближайший.
Связано: [[feedback_inject_only_after_the_work_is_committed]].
