---
name: project_phase_g_final_review
description: "Директива владельца: финальное Fable-ревью ВСЕЙ фазы G — честная балльная оценка before/after, сравнение с коммерч. best practices, архитектура/модульность/эффективность/безопасность/стиль"
metadata:
  node_type: memory
  type: project
  originSessionId: 2bbae9f7-11c0-4154-8369-2fd9c8dfa9bb
---

Владелец (2026-07-14): перед merge всей фазы G — **обновить qex** (reindex), затем дать
Fable **честную оценку**. Требования к ревью:

**Что сравнить:**
- **before/after ВСЕЙ фазы G** (не отдельной задачи): состояние до старта фазы ↔ после. Референс
  «до» = SHA начала фазы + все флаги дефолт-off (тракт G бит-в-бит откатывается флагами).
- с **лучшими подходами из чужих коммерческих проектов** (индустриальные паттерны SHM/IPC/
  zero-copy/владение слотами — iceoryx2/DDS loan-publish, seqlock, claim-check и т.п.).

**Оси оценки (все):** архитектура · паттерны программирования и практики (что улучшили) ·
**модульность** · **эффективность** · **безопасность** · **общий стиль** · **согласованность с
остальными модулями**.

**Формат:** честно (что правильно / что неправильно), **с советами**, желательно **в баллах**
(балльная оценка по осям). Не маркетинг — вердикт по факту (для перф — по замеру G.7, не по вере).

**Порядок:** доделать код фазы (G.H ✅, G.9 ✅, G.8) → qex-reindex → 8-угловое (риск-задачи) →
**этот Fable-ревью на всю фазу** → G.7 flip/soak/приёмка → merge.

## Итог ревью + ремедиация (2026-07-14→15)

Ревью проведено (4 Sonnet-финдера + Fable-свод): **before 4.8 → after 7.4/10**. Оси:
архитектура 7.5 · паттерны 9 · модульность 7 · эффективность 7 (перф pending-G.7) ·
**безопасность 6.5** · стиль 8 · согласованность 9. Низкая безопасность — единственная
причина: модель **single-writer была ЗАЯВЛЕНА, но не ЗАКРЕПЛЕНА кодом**.

Владелец: «исправить без костылей, как полагается» → выбрал **Option 1 (single-writer
enforced, lock-free)**. Ремедиация сделана и закоммичена (`b3576c12`), 4696 passed, 0 регрессий:
- LoanLedger: acquire резервирует слот (WRITING) + single-writer thread-guard; commit
  публикует; `abort` (loan без publish → free); state-машина free→writing→ready→free.
- Настоящий DI (injectable `pool=`/`reader=` в middleware); read_frame под lock; тихие
  except→`close_errors`; collect_scheduled проведён в heartbeat (HIGH gc-trap закрыт);
  worker.drain `removed`=факт. ADR-SRM-013 амендмент.

**Директива на ФИНАЛЬНОЕ Fable-ревью (владелец 2026-07-15):** искать КЛАСС «стале-ссылки»
— переименованные/несуществующие символы, мёртвые импорты, сломанный сбор тестов, дрейф
«переименовали, вызовы не обновили». Готовые улики: 7 collection-errors + 8 `base_manager`
isinstance-падений (предсуществующие, `ProcessManagerCore`→`ProcessManagerProcess`).
Нейминг: владелец предпочитает `ProcessManagerCore` — отдельный рефактор, не в скоупе фазы G.

**Порядок (владелец склоняется):** G.7 flip/soak (числа FPS/p99) → финальное Fable-ревью
(с числами + hunt стале-ссылок) → merge.

## ФИНАЛЬНОЕ Fable-ревью ПРОВЕДЕНО (2026-07-15, ветка feat/mem-module-consolidation)

**Вердикт: APPROVE — merge в main.** Гейт: 4690 passed / 2 pre-existing Windows-fail
(эталон) / 6 skipped; точечные G-тесты 208+82; sentrux 7100 (старт фазы 7088), циклов 0,
rules 9/9. Баллы фазы: **before 4.8 → after 8.0/10** (арх 8.5 · паттерны 9 · модульность 8 ·
эффективность 7.5 (числа — G.7 soak) · безопасность 8 · наблюдаемость 9 · стиль 8.5).

**4 находки закрыты фиксом `0a7f16a6`:** (1) LoanLedger «писатель навсегда» ломал G.8
drain→replace воркера — теперь «один писатель в каждый момент» (мёртвый → перепривязка);
(2) хардкод `{"gui"}` в `_COPY_OUT_TARGETS` → перекрытие `copy_out_targets` из конфига
процесса + дедуп целей; (3) FW_GC_SCHEDULED без FW_GC_FREEZE был тихим no-op → громкий
warning; (4) стале-докстринг find_free_index + чекбокс G.9.

**Hunt стале-ссылок:** 7 collection-errors = ВСЕ `ProcessManagerCore→ProcessManagerProcess`
в `multiprocess_framework/tests/` (каталог ВНЕ testpaths CI — мёртвая зона; чинить вместе с
рефактором нейминга, вне фазы G). ruff F821/F401 по фазе G чист.

**Новые находки:**
- ✅ ЗАКРЫТО вторым фиксом ревью: `frame_ring_depth`/`copy_out_targets` из рецепта НЕ
  долетали (ProcessConfig extra=ignore молча дропал) → проведены extras→GenericProcessConfig
  (typed)→proc_dict.config; по запросу владельца маркер copy-out — через КОНФИГ (рецепт:
  `extras.copy_out_targets`), не через регистры (роль структурная, live-write рассинхронизировал
  бы refcount). Golden-снапшоты перегенерированы осознанно.
- ✅ ЗАКРЫТО тем же фиксом: характеризация «двух живых рецептов» была RED на main с merge
  G.3/G.4 (backend/tests вне framework-раннера — тихо сгнила): env-зависимые разделители
  log-путей (INSPECTOR_LOG_DIR setdefault + порядок тестов) + невнесённый `use_kind_channels`.
  `_normalize_paths` теперь канонизирует разделители rooted-путей. СОВЕТ: включить
  backend/tests в регулярный гейт (validate.py/CI).
- `wire.configure`-тракт создаёт middleware БЕЗ num_consumers (дефолт 1) — несогласован
  с recipe-трактом G.7-фикса.
- POSIX без FW_SHM_OWNER_INCARNATION: `cleanup_stale_shm` молча unlink'ает ЖИВОЙ сегмент
  тёзки → мультикамера на Linux/macOS требует инкарнацию (Windows маскирует PID-суффиксом).
- Join 2 камер в 1 процесс: JoinInspectorManager ключуется (seq_id, data_type) БЕЗ
  camera_id, `_FRAME_ID_MODULO=121` → коллизии; рабочий паттерн — batch/fanin плагин с
  корреляцией по camera_id (multi_camera.yaml) либо разные data_type.
Прежние резидуалы G.7 остаются: E2E release живым транспортом, incarnation-guard,
реальный kill-9, длинный soak обоих рецептов. Teardown `ValueError: I/O operation on
closed file` — известный graceful-stop долг, отдельной задачей.

Связано: [[project_memory_module_consolidation]] (директивы память-один-модуль на G.5),
[[project_feature_flags_registry]], [[feedback_formal_review_before_merge]].
