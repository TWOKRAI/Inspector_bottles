---
name: feedback_recipe_knob_must_be_named_in_from_recipe
description: Ключ рецепта доезжает до процесса только если назван в ProcessConfig._from_recipe и лежит в extras; metadata читается лишь ради легаси-коллектора
metadata:
  type: feedback
---

Новая ручка процесса, положенная в рецепт под `metadata:`, **не доезжает до процесса вовсе**.
`ProcessConfig._from_recipe` собирает `base_kwargs` поимённо через `_pick(key, default)`, а тот
смотрит в typed-поле ИЛИ в `extras`. `metadata` читается только ради легаси-ключа коллектора.
Незнакомый ключ Pydantic отбрасывает молча (`extra=ignore`) — «заявлено, но не проведено».

**Why:** 2026-08-12 ручка `chain_max_lag_items` была положена в `metadata:` и выглядела рабочей —
тесты зелёные, рецепт читаемый. Живой прогон показал, что старое поведение осталось на месте
(прежнее сообщение о перегрузке никуда не делось). Чтение диффа этого не даёт: дифф выглядит
правильным. Тот же класс уже ловили на `frame_ring_depth`/`copy_out_targets` (Ф7 G.7).

**How to apply:** новая ручка процесса = три места: поле в `GenericProcessConfig`, строка в
`_from_recipe` (`_pick` + `base_kwargs[...]`), ключ в рецепте под `extras:`. Доказывать
**сборкой**, а не верой: `SystemBuilder.from_manifest(app, recipe).build()` → напечатать
`proc["config"][ключ]` у целевых процессов и убедиться, что значение **отличается от дефолта**
(совпавшее с дефолтом число ничего не доказывает — см. [[feedback_coinciding_constants_hide_opposite_implementations]]).
Новое поле схемы материализуется во ВСЕХ proc_dict — снимки сборки придётся перегенерировать
(`UPDATE_BUILD_SNAPSHOTS=1`), и дельта обязана быть ровно этим ключом с нейтральным значением
(см. [[feedback_no_regression_proved_by_identical_build]]).

Связано: [[feedback_facade_is_a_whitelist_not_a_passthrough]], [[feedback_port_wire_is_not_a_process_route]],
[[feedback_materialized_default_hides_absence]].
