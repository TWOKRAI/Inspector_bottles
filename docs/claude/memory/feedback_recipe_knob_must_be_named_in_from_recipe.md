---
name: feedback_recipe_knob_must_be_named_in_from_recipe
description: "Ключ рецепта доезжает до процесса только если назван в ProcessConfig._from_recipe и лежит в extras; metadata читается лишь ради легаси-коллектора; также: Новый ключ конфига читать из секции, которая УЖЕ едет к процессу, а не заводить свой — иначе его надо класть в каждой дороге сборки"
merged_from: [feedback_read_the_key_from_the_section_already_travelling]
module: "recipe, process_module"
mechanism: "config-delivery"
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

## Слито из feedback_read_the_key_from_the_section_already_travelling (_archive/feedback_read_the_key_from_the_section_already_travelling.md)

Ф8.5 (2026-08-09). Спека предлагала завести плоский ключ `observability_documents` в
`proc_dict["config"]` и честно предупреждала о ловушке: конструкторов `BlueprintAssembler`
**два** — boot (`launch.py`) и switch (`orchestrator_hooks.py`). Забудешь второй — плоскость
исчезает после горячей смены рецепта, молча.

Решение оказалось дешевле спеки: ключ положен ВНУТРЬ секции `observability`
(`ObservabilityConfig.documents`) и читается из разрешённых слоёв
(`process_observability_layers(svc).resolve()["documents"]`). Секция уже едет к каждому
процессу обеими дорогами (`observability_app` = L1, `observability_override` = L2) —
поэтому **ассемблеры не правились вовсе**, и ловушка исчезла вместе с правкой.

**Why:** каждая новая точка раскладки конфига — это ещё одно место, которое можно забыть,
и забывается оно на редкой дороге (switch, hot-swap), где дефект не воспроизводится
тестами сборки. Ключ, приехавший внутри уже существующей секции, наследует все её дороги
даром. Побочная выгода: он автоматически становится настраиваемым рецептом (L2) и
командой (L3), и попадает в provenance.

**How to apply:** прежде чем заводить новый ключ `proc_dict`, спросить — есть ли секция,
которая УЖЕ доезжает туда, куда нужно, и чей смысл ключ разделяет. Если да, класть внутрь
неё и добавлять поле в её Pydantic-схему (без поля `model_dump(exclude_unset=True)`
**молча выбросит** ключ — extra-ключи схема принимает, но не хранит). Смежное:
[[feedback-defect-fixed-on-one-path-only]], [[feedback_fakes_feed_config_flat_so_key_address_defects_are_invisible]],
[[feedback-model-copy-does-not-validate]].
