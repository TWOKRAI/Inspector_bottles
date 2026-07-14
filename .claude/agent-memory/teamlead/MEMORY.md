# Memory Index

- [seqlock contention semantics](project_seqlock_contention_semantics.md) — seqlock голодает при read≈write (всё дропает, но torn=0); тесты доставки в режиме read<<write, heavy-contention asserts только torn==0
- [commit trailers single-line](feedback_commit_trailers_single_line.md) — Why/Layer/... каждый на ОДНОЙ строке, иначе hook отвергает как «missing trailers»
- [switch live survivor](project_switch_live_survivor.md) — live-тест выжившего после topology.apply: брать protected `devices`, НЕ camera_0 (FullReplacePlanner + strip_gui)
- [hardware recipes no headless boot](project_hardware_recipes_no_headless_boot.md) — phone_sketch/hikvision не бутятся headless (блок на железе); валидируй через assemble + механизм на region_pipeline
- [cross-module move + шим = runtime cycle](project_crossmodule_move_shim_cycle.md) — перенос schema-модуля с back-compat шимом ловит circular import через eager package __init__ re-export; убрать re-export
- [новый framework-модуль: регистрация в 3 местах](project_new_framework_module_registration.md) — validate.py MODULES + scripts/sync/_adr_layers.py + python -m scripts.sync, иначе validate падает на ADR-дрифте
- [sentrux free-tier: только 3 правила](feedback_sentrux_freetier_3rule_limit.md) — check_rules pass не значит проверен твой boundary; критичный инвариант дублируй grep-тестом; relative-импорты обходят boundary (используй для self)
- [topology event-ordering: edit vs activate](project_topology_event_ordering.md) — все правки → TopologyReplaced; активация доп. RecipeActivated ПОСЛЕ (надёжный дискриминатор); load-from-file идёт мимо store
- [chain_module overhead-профиль](project_chain_module_overhead_profile.md) — ChainRunnable.execute ~2µs/батч фикс; >45% на пустых плагинах, <1.3% на реальной CV-работе; синтетический микробенч = ложный blocker, мерить на реалистичной работе звена
- [RS-7 workers семантика](project_rs7_workers_semantics.md) — recipe `workers`=tuple[WorkerSpec] (процессные треды), НЕ chain-pool; ортогонально C6e; проброс требует адаптера+ассемблера, отдельная задача, не встраивать наугад
- [swap stdlib-примитива: гарантии](feedback_swap_stdlib_primitive_guarantees.md) — заменяя ThreadPoolExecutor/пул/очередь своим, перечисли «бесплатные» гарантии (cancel/BaseException/изоляция/after-close) и покрой тестами ДО ревью; один редизайн вместо заплаток
