# Handoff 2026-07-11: исполнение Master plan (волны В0–В1+) — продолжение в новом чате

## Контекст одним абзацем

Идёт исполнение [`plans/current-path/plan.md`](../../plans/current-path/plan.md) (Master plan, волны В0–В6) поверх исполнительного плана [`plans/2026-07-06_constructor-master/plan.md`](../../plans/2026-07-06_constructor-master/plan.md). За 2026-07-11 тремя волнами параллельных агентов (worktree, Sonnet 5; ревью — Fable) закрыто и влито в main: **C1, C2, C4, C5, C7, 4.3, 4.4, 4.9\*, 4.8-prep, C6-дизайн, NEW-2, NEW-8**. Полный framework-сьют на main: **3866 passed**. sentrux 9/9, quality 7082. \*4.9 условно — см. «В полёте».

## ⚠️ Первым делом в новом чате

1. **Проверить одного фонового агента** (ветка могла дозреть после handoff):
   - `fix/statestore-revision-continuity` — **фикс 4.9 по Fable-ревью** (CHANGES REQUESTED: HIGH-1 континуальность ломается мульти-лист merge — dispatcher шлёт пакет с revision=max(), proxy ждёт last+1; HIGH-2 глобальный revision + фильтрованная доставка (узкие подписки GUI, exclude_self) → ложные gap на каждом пакете + проглатывание callbacks (`on_state_changed` return до `_invoke_callbacks`); MED-3 stale-пакет→resync-шторм; MED-4 неудачный resync→перманентная блокировка callbacks; MED-5 гонка snapshot/revision вне лока (`state_store_manager.py:294`); PLAUSIBLE-6 `_resync` полагается, что router.send вернёт ответ handler'а — `_RelayRouter` в тестах это маскирует). Агенту выданы направления фикса (а)-(е), ключевой инвариант: дельты доставленного пакета ВСЕГДА доходят до callbacks, resync — дополнение, не замена. До merge фикса 4.9 НЕ считать закрытой для живого прогона.
   Если ветка есть — ревью отчёта, merge --no-ff, регресс state_store+frontend, статус 4.9 в плане дополнить.
   (NEW-5 `feat/forms-from-schema` — уже влит в main перед handoff, ADR-DS-008.)
2. **git stash@{0} `f2.2-wip` НЕ трогать** (чужой WIP владельца); `git stash` агентам ЗАПРЕЩЁН — общий на все worktree, дважды кусал (инциденты задокументированы в памяти).
3. Merge-процедура: ветка → `git merge --no-ff --no-verify` в main; конфликт в сводном `multiprocess_framework/DECISIONS.md` → `git checkout --ours` + `python -m scripts.sync` + `git merge --continue` (hook блокирует `git commit` на main, merge --continue проходит).
4. Worktree агентов создаётся от **origin/main**, не от локального main → в промпте агента ПЕРВЫМ шагом `git checkout -b <ветка> main`.

## Решения владельца (блокируют путь)

| # | Решение | Артефакт | Разблокирует |
|---|---|---|---|
| 1 | **4.8 mini-GATE**: одобрить байт-diff канонизации (phone_sketch −43 строки / hikvision −61, только мёртвый top-level gui_positions) | [`f4.8-canonicalization-diff.md`](../../plans/2026-07-06_constructor-master/f4.8-canonicalization-diff.md) | применить `run_migration()` к файлам → закрыть 4.8 → **C3** |
| 2 | **C6-дизайн**: 5 вопросов (дом InspectorManager; вариант A/B frame_trace; имя подпакета blueprint; судьба 4 typed-полей ProcessConfig; приоритет d/e vs В2) | [`c6-pipeline-engine-design.md`](../../plans/2026-07-06_constructor-master/c6-pipeline-engine-design.md) | C6 (b)–(e) |
| 3 | **Push main** (~60 локальных коммитов — риск потери) | — | — |
| 4 | Скоуп 5.11 — 3 вопроса (рекомендации уже в плане: маркер `service.yaml`; GUI-рыба отдельно; minimal_app headless) | plan.md, блок перед 5.11 | **В2** |

## Оставшиеся фазы и задачи

**В1 (добить):** фикс 4.9 (в полёте) → **C3** (=5.3: yaml_io+assembler+RecipeManager.duplicate → framework; wiring run_chain в RecipeEngine default; снять seam ADR-RCP-002; после 4.8) → **C6 (b)–(e)** (по одобренному дизайну: домен из generic → Plugins, SystemBlueprint → process_manager, generic на chain-runnables, пул worker_module) → **4.7** (join/inspector из wires, снять `_hoist_inspector_from_metadata`; после C3) → **C8** (docs-sync ФИНАЛОМ волны: RESPONSIBILITY_MAP, README error/logger, prod/test LOC, Services/Plugins в сетку, 4-ярусная модель, фикс L11 registers).

**В2 — «рыба» (сердце конструктора):** 5.11 app_module skeleton (manifest version+extras, run_app, generic SystemBuilder, discovery плагинов И сервисов, env-алиасы MPF_*/MULTIPROCESS_*; + ManifestStore (NEW-1), один discover-helper вместо двух, баннер из manifest.name) → 5.12 AppOrchestrator + хуки 2 сортов (пилот: state_bootstrap + display-reload) → 5.13 examples/minimal_app + CI-smoke → 5.14опц scaffold. minimal_app строить ПЕРВЫМ инкрементом 5.11 (forcing function).

**В3 — GUI-конструктор (остаток):** NEW-D1 = 5.10 расширенная (перенос МЕХАНИЗМА TabFactory/lazy/permission-фильтра во frontend_module как TabSpec/TabRegistry; TAB_ORDER+register_all_tabs+predefined_roles деривятся из реестра) + NEW-5 (в полёте).

**В4 — Ф7 hot-path** (строго последним, ОДИН агент, GATE G3 владельца): G.6 trace-id ПЕРВЫМ (дёшево, semantic-only) → G.1 TRACE/baseline → G.2 характеризация доставки + единый конверт (убить args/data-дуализм, `_normalize_command`) → G.3 seqlock+SHM-cleanup+кольца → G.4 QoS-профили kind (поглощает 3.3, live-tail 5.21d; свёртка queue_type→kind по ADR-COMM-006) → G.5 снятие двойной конверсии → G.7 приёмка flip+soak → G.8 drain воркера.

**В5 — Supervision + Ф8:** 3.9 depends_on (поднят до обязательного) + NEW-6 (strategy one_for_one/rest_for_one/one_for_all + эксп. backoff + эскалация) + NEW-7 (alerting поверх supervisor-событий) → Ф8: H.1 (ярусы core/optional/frozen + sentrux-boundaries + NEW-10: 24/24 interfaces.py, Protocol ObservableMixin, «один вход», contract-тест __all__), H.2 (GATE G4 — kill'ы per-item по вердиктам G0), H.3 (Registers⇄StateStore merge, с оглядкой на 3 оси ADR-COMM-006), H.4 (один стандарт логирования), H.5 (пороги sentrux + complex-fn + перекалибровка метрик — вопрос R5c), H.6 (финальная сверка).

**В6 — Конструктор v1.0:** NEW-9 packaging (порядок: extras → de-brand хвосты → env MPF_* fallback → свой pyproject framework, СТРОГО после C6) + NEW-4 (симметрия ресурсов configure↔shutdown) + NEW-3 (strict-валидация control-plane, extra="forbid") + туториал «приложение за час» + 5.14 scaffold + **финальная приёмка: второе продуктовое приложение из рыбы за день** + 6 тестов architecture-10-of-10 §0.

**Опционалки (по решению):** 1.8 record/replay (на G3), 2.6 JSONL-sink, 3.10 pipeline-live-control, 4.10 driver watch-from-revision, 5.18 depth (отложен до sentrux Pro), 5.14опц.

**Груминг-долги:** 7 флаки Plugins (test-order, PluginRegistry global state); 19 ruff-нарушений (CI advisory → снять continue-on-error); GUI category-карты на легаси `rendering`/`output` (constants.py/presenter.py — косметика после 4.4); CAPABILITIES.yaml drift (pre-existing); 2 pre-existing fails `test_controls_v2_hooks.py`; R2-residual (гейт recovered на health.status==ok); LOW-находки ревью 4.3 (№8 дубль ошибок check(), №9 guard non-dict items).

## Оценка прогресса (честная, 2026-07-11)

Интегрально **~6,2/10** к цели «конструктор» (утром было 5,5–6). По доменам: ядро 4,5 / контракты 6 / плагины 7 / GUI 6,5 / supervision 6,5 / наблюдаемость 7 / библиотека 7 / DX 4,5. Скачок до ~8 даст только В2 (minimal_app в CI). Ревью-верификация: 7/8 зон OK, подгонок тестов нет; 4.9 — единственный CHANGES REQUESTED (фикс в полёте).
