# Re-scan находок аудита — актуализация на 2026-06-18

> **Зачем.** Аудит [`2026-06-13_prototype-services-plugins-audit.md`](2026-06-13_prototype-services-plugins-audit.md) написан 5 дней назад (ветка `feat/camera-robot-calibration`); его `file:line` дрейфнули, часть находок уже починена. Это **W0-артефакт** мастер-роадмапа ([`../../plans/master-rework-roadmap.md`](../../plans/master-rework-roadmap.md)): волны чистки W1+ берут координаты ОТСЮДА, не из аудита (риск R3 — re-fix по устаревшим координатам).
>
> **Метод.** 3 read-only investigator-агента по зонам, верификация против ЖИВОГО кода (qex/serena/grep/read), ветка `feat/draw-mode-rework`. Принцип: код = истина.
>
> **Статусы:** STILL-PRESENT / MOVED / ALREADY-FIXED / REFUTED / PARTIAL.

## Сводка изменений с 2026-06-13

- **Закрыто/улучшено:** M-err-6 (улучшен, но битый YAML всё ещё падает → PARTIAL), M-ml-1 (resize_policy в ModelSpec, дефолт letterbox → PARTIAL), M-dom-1 (DisconnectWire теперь удаляет ВСЕ совпадения — частичное улучшение; ConnectWire всё ещё без dup-check), M-dead-5 (Operation_crop 858→519 LOC, но всё ещё сирота).
- **Опровергнуто:** `registers/manager.py build_rm_from_topology` — НЕ test-only, используется в проде (`adapters/stores/registers_backend.py:77`).
- **Уточнено (важно для волн):** M-dead-1 ActionBus имеет **2 живых prod-потребителя** (FormContext forms-binding + `roles_panel.py:204` V2ActionBuilder) — удаление НЕ одностороннее (→ K1 owner-decides подтверждён). M-lay-1 — **2 места** (~443 и ~795), не одно; `ProcessCard` уже даёт публичные `indicator`/`metric_label()`. M-dead-2 — мёртвы `hot_add_process`/`connect_wire`/`apply_topology_diff`, а `hot_remove_process`(:405)+`disconnect_wire`(:475) ЖИВЫ.
- **H1/H2 — закрытие держится** (verified).

---

## Зона A — Frontend

| ID | Ориг. | Текущий file:line | Статус | Прим. |
|----|-------|-------------------|--------|-------|
| M-leak-1 | auth_facade.py:75 / permission_gate.py:80 | `auth_facade.py:75` + `permission_gate.py:80,257` | STILL-PRESENT | `on_access_changed` connect(lambda) без disconnect; 2 точки вызова |
| M-leak-2 | app.py:262 | `frontend/app.py:269` | MOVED / PARTIAL | вызывается ОДИН раз на старте, накопления нет; нет `remove_state_listener` в framework |
| M-leak-3 | presenter.py:167-177 | `pipeline/presenter.py:167,177` | STILL-PRESENT | ровно **2** подписки (`_topology_sub`,`_recipe_activated_sub`), handle есть, unsubscribe нет |
| M-leak-4 | processes/tab.py:113 | `tab.py:113` | STILL-PRESENT | `_topology_sub` без teardown при destroy |
| M-leak-6 | preview_window.py:249 | `preview_window.py:249` | STILL-PRESENT | unsubscribe перезаписывает broadcast пустым списком (мульти-окно гасит соседей) |
| M-perf-3 | factory.py:880 | `forms/factory.py:880` | STILL-PRESENT | `textChanged`→write на каждый символ (через ActionBus/FormContext) |
| M-lay-1 | _panels.py:443 | `_panels.py:443-448` **+ :795-814** | STILL-PRESENT | **2 места** читают приватные `_indicator`/`_metric_labels`; есть публичные `indicator`/`metric_label()` |
| M-god-1 | presenter.py:86 | `pipeline/presenter.py:86` | STILL-PRESENT | **1827 LOC** (+9), 56 методов |
| M-god-3 | factory.py:229 | `forms/factory.py:229` | STILL-PRESENT | 9 binding-builders (229/278/330/382/444/624/767/845/924), 1190 LOC |
| M-dead-1 | app.py:463 + actions/ | `app.py:458-476` + `frontend/actions/` (20 файлов) | STILL-PRESENT | runtime-dead для undo, НО **2 живых prod-потребителя**: forms FormContext + `roles_panel.py:204`. Удаление не одностороннее → **K1 owner-decides** |
| M-dead-2 | topology_bridge.py:381 | hot_add `:381`, connect_wire `:432`, apply_topology_diff `:503` = DEAD; **hot_remove `:405` + disconnect_wire `:475` ЖИВЫ** | PARTIAL | мёртвые зовутся только из self-calls+тестов; `hot_remove_process` ← `processes/presenter.py:392` |
| M-dead-3 | command_panel.py:42 | `controls/command_panel.py:11` + `process_status.py:8` | STILL-PRESENT | 0 prod-импортов, только `tests/test_bridge.py` |
| M-dead-4 | topology/editor.py:26 | `editor.py:26` DEAD; **`topology/presenter.py:19` ЖИВ** | STILL-PRESENT | editor-виджет мёртв (re-export+тест); `TopologyPresenter` ← `pipeline/presenter.py:160-162` |

---

## Зона B — Plugins + Services + robot

| ID | Ориг. | Текущий file:line | Статус | Прим. |
|----|-------|-------------------|--------|-------|
| M-leak-5 | robot/controller.py:114 | `robot/calibration/controller.py:112,158` + `robot/controller.py:135` | STILL-PRESENT / PARTIAL | calib: `unbind()`(142) чистит только метаданные; robot: `bind_fanout` без сохранения handle → `_unbind_state` пуст |
| M-race-1 | device_hub/plugin.py:202,428-435 | `plugin.py:210,223,275,287,335,446,451,452,900,903` | STILL-PRESENT | **10 мест** читают приватные `_manager._entries/_drivers` мимо `_registry_lock`; итерация на supervisor-тике → RuntimeError |
| M-race-2 | worker_pool/plugin.py:120 | `plugin.py:122-123` | STILL-PRESENT | при items>pool_size один экземпляр sub-plugin в N потоках |
| M-race-3 | database/plugin.py:127 | `plugin.py:127-133` + `_do_flush:154-185` | STILL-PRESENT | `_do_flush` мутирует `_total_*` без `_buffer_lock`; per-row SQLite |
| M-race-4 | modbus/core/device.py:92-111 | `device.py:92-111` | STILL-PRESENT | RLock держится на блокирующем connect/disconnect IO |
| M-perf-1 | robot_control/plugin.py:138 | `plugin.py:138` | STILL-PRESENT | `time.sleep(reject_delay_ms)` в `process()` |
| M-perf-2 | blob_detector/plugin.py:106 | `plugin.py:106` | STILL-PRESENT | `mask`+`contours` (ndarray) в item на каждый кадр |
| M-perf-4 | sql/action_log/log_writer.py:135-159 | `log_writer.py:135-159` | STILL-PRESENT | DB-запись под `_lock` (задокументировано «для простоты») |
| M-err-1 | camera_service/plugin.py:152-155 | `plugin.py:152-155` | STILL-PRESENT | `produce()` `except Exception: return []` молча → чёрный экран. **Hot-path, W2** |
| M-err-2 | capture/plugin.py:122 | `capture/plugin.py:150-153` | MOVED | голый except в `produce()` без лога. **Hot-path, W2** |
| M-err-3 | device_hub/drivers/robot_driver.py(+vfd+generic) | robot `:181-183,196,336,532`; vfd `:173-174`; generic_modbus `:66,78,109` | PARTIAL | IO-ошибки → только `_record_err()` (счётчик), без `log_*` |
| M-err-4 | hikvision/parameters.py:74 | `parameters.py:74-77` + `discovery.py:155-173` | STILL-PRESENT | SDK-ошибки set/get проглатываются без лога |
| M-err-6 | calibration/store.py:110 | `store.py:110-119` | PARTIAL | пустой/нет файла → None (ок), но битый YAML (`yaml.YAMLError`) всё ещё падает |
| M-err-7 | auth/audit_writer.py:72,144-154 | `audit_writer.py:72-73,144-154` | PARTIAL | очередь без `maxsize` (рост памяти); fallback-ветка в `log()` мёртвая (put_nowait на unbounded не бросит Full) |
| M-arch-1 | vfd_comm/client.py:97-118 | `client.py:42-52` (конструктор, `register_map=BRIDGE_MAP`) | STILL-PRESENT | дефолт-coupling на BRIDGE_MAP |
| M-arch-2 | modbus/device.py:176-193 | `device.py:153-193` | STILL-PRESENT (задокументирован) | fail-fast на 1-й ошибке помечен намеренным; маркер последней операцией |
| M-arch-3 | color_mask/plugin.py:38-40,98-99 | `plugin.py:38-40,99` | STILL-PRESENT | порт `mask`, но пишет в `frame` (расхождение с hsv_mask) |
| M-ml-1 | ml_inference/preprocess.py:40 | `preprocess.py:63-91` + `model_spec.py:46` | PARTIAL | `resize_policy` в ModelSpec (дефолт letterbox); остаток — legacy ONNX без поля в sidecar |
| M-dead-5 | Operation_crop/preobrazovanie.py | тот же путь, **519 LOC** (было 858) | STILL-PRESENT (уменьшен) | сирота, 0 prod-импортов |
| M-sec-1 | auth/manager.py:303-323 | `manager.py:302-323` | STILL-PRESENT | пропуск bcrypt для несуществующего юзера → timing-oracle |

---

## Зона C — Domain + Recipes + Backend + Config + comm + HIGH-закрытия

| ID | Ориг. | Текущий file:line | Статус | Прим. |
|----|-------|-------------------|--------|-------|
| H1 | project.py:453-508 | `project.py:471-537` (`_rename_refs:492-500`) | ALREADY-FIXED | rename обновляет `target_process`/`chain_targets` — держится |
| H2 | converter.py:97 | `converter.py:77-125` | ALREADY-FIXED | `resize(mode="letterbox")` дефолт — держится |
| M-dom-1 | project.py:754-787 | `_apply_connect_wire:783`, `_apply_disconnect_wire:818-842` | STILL-PRESENT (улучш.) | ConnectWire без dup-check; DisconnectWire теперь удаляет ВСЕ совпадения |
| M-dom-2 | project.py:941-954 | `_apply_replace_topology:970-983` | STILL-PRESENT | stale `active_recipe` после replace |
| M-dom-3 | recipe.py:82-85 | `recipe.py:82-85` + `_coerce_devices:151-162` | PARTIAL | `dict(d)` поверхностная копия (вложенный `transport` не deep); нет round-trip теста |
| M-cfg-1 | .../generic/blueprint.py:343 | `process_module/generic/blueprint.py:343` | PARTIAL | runtime `_extract_plugin_config` (plugin_orchestrator.py:86-106) разворачивает; blueprint-путь для SHM-размера — нет |
| M-cfg-2 | dataset_circle_capture.yaml + camera_robot_calibration.yaml | оба v3; read-norm: `pipeline/presenter.py:1225,1652` + `recipes/presenter.py:394` | PARTIAL | форматы файлов выровнены (v3), но 3 READ-сайта с legacy-fallback остаются |
| M-be-1 | orchestrator.py:185-198 | `orchestrator.py:180-198` | STILL-PRESENT | DisplayRegistry reload до `super().apply_topology()` → окно рассинхрона |
| M-err-5 | topology/editor.py:151 | `editor.py:154` | STILL-PRESENT | `except: pass` (виджет мёртв, см. M-dead-4) |
| M-lay-2 | auth/tests/test_role_update_handler.py:14 | `:14` | STILL-PRESENT | обратный импорт Services→prototype в тесте |
| L-dead frame_router_setup | backend/routing/frame_router_setup.py | тот же | STILL-PRESENT | 0 prod-импортов |
| L-dead blueprint_binding | backend/displays/blueprint_binding.py | тот же | STILL-PRESENT | только re-export+тест |
| L-dead registers/manager | build_rm_from_topology/_RawRegisterData | `registers/manager.py` | **REFUTED** | `build_rm_from_topology` ← `adapters/stores/registers_backend.py:77` (ПРОД) |
| L-dead webcam_camera | Services/webcam_camera/ | только `__pycache__`, 0 `.py` | STILL-PRESENT | фактически пустой |
| L-dead Region_processors | Services/Region_processors/ | 3 `.py`, 0 импортов | STILL-PRESENT | не используется |
| comm FrameShm TRACE | — | `frame_shm_middleware.py:345,357,370,375,387,395,400` | STILL-PRESENT | 7 `[TRACE]`-логов в hot-path `on_receive` (K10) |
| comm release_process_memory | — | `manager.py:375` + `process_manager_process.py:624` | STILL-PRESENT (закрыто) | метод есть и вызывается — канон-gap M2 ЗАКРЫТ (SC-4) |

---

## Что это меняет в волнах

- **W1 (утечки):** M-leak-3 (2 подписки, тривиально) → M-leak-1/4/5/6; M-leak-5 учесть ОБА контроллера (`robot` + `calibration`); M-lay-1 — **2 места**, использовать публичные `indicator`/`metric_label()`.
- **W2 (hot-path ошибки):** M-err-1 `camera_service:152-155`, M-err-2 `capture:150-153` (координата обновлена) — contain→report→degrade.
- **W3 (гонки + carve):** M-race-1 — публичный snapshot мимо приватных `_entries` (10 мест).
- **W4 (kill-list, owner-decides):** M-dead-1 — **НЕ удалять весь пакет** (2 prod-потребителя); M-dead-2 — только мёртвые методы, беречь `hot_remove_process`/`disconnect_wire`; M-dead-3/4 (editor беречь `TopologyPresenter`); M-dead-5 (519 LOC); webcam_camera/Region_processors; K10 TRACE (hot-path — qt-smoke+FPS). **registers/manager НЕ кандидат (REFUTED).**
- **W2/W6:** M-arch-2 уже задокументирован как намеренный — снять из «багов», оставить как есть.
