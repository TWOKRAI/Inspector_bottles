---
name: project_camera_settings_feature
description: Настройки камеры РЕАЛИЗОВАНЫ — унифицированный путь через плагин camera_service (live + actual + MJPG)
metadata:
  type: project
---

Фича настроек вебкамеры РЕАЛИЗОВАНА (5 фаз, ветка fix/recipe-v3-engine-decouple, uncommitted).
План: `~/.claude/plans/project-camera-settings-feature-purrfect-kettle.md`.

**Архитектура (решение владельца):** плагин `camera_service` — ЕДИНСТВЕННЫЙ владелец cv2 и
единый путь управления. Оба UI (Pipeline-инспектор + Services-фасад) шлют правки в ОДИН работающий
плагин через `TopologyBridge.on_action_command`/`on_field_set`. Второго cv2 в GUI нет (online-only;
preview = pipeline «камера→дисплей»). desired → рецепт (persist по «Сохранить»), actual → state store
(read-only). Настройки в рецепте (plugin_config), не отдельный каталог.

**Что сделано:**
- `Plugins/sources/camera_service/backends/webcam_controls.py` — каталог CAP_PROP + apply/read/set_mjpg;
  `apply_open_sequence` enforce MJPG→width/height (фикс ~15fps DirectShow).
- `plugin.py`: команды `set_param/set_config/set_mjpg/get_actual` + `_apply_field` reconciler + publish
  actual в `processes.{name}.state.cam.actual` (раз в 30 кадров). `registers.py` = tunable subset
  (fps/mjpg/exposure/gain/brightness/contrast) для инспектора; `config.py` += register_bindings + `params`.
  Дефолты register НЕ форсятся на камеру (только при правке/явно в рецепте).
- Pipeline-инспектор: subset-поля авто из register + блок «Камера (actual)» (привязка к state через bindings).
- Services «Камера» = подробный фасад (`frontend/widgets/tabs/services/camera/`): пресеты + полный каталог
  WEBCAM_PARAMS + MJPG + actual + «Сохранить в рецепт». IPC-only (без cv2).

**Решения/нюансы:**
- `Services/webcam_camera/` УДАЛЁН (по требованию владельца «одно лучшее»): единственный владелец cv2 —
  плагин. sandbox-снимок переведён на `webcam_controls.capture_single_frame` (разовый грабер, единый
  cv2-путь). Кнопка webcam в sandbox теперь всегда активна (fail-graceful если устройство занято).
- Почему нельзя было «поделиться» кодом: WebcamCameraService в слое Services, control-core в Plugins
  (Services НЕ импортирует Plugins по слоям) → дубль убран, а не вынесен. sandbox в prototype → Plugins (ок).
- Слои: control-core в Plugins; фасад в prototype (prototype→Plugins разрешено). Граница Services→prototype не нарушена.
- Тесты: 105 feature-specific passed (control-core, plugin live/actual, inspector, фасад). ruff чисто.
- qt-mcp probe-инспекция НЕ выполнена (probe не поднимается обычным run.py); реальная сборка проверена —
  app стартует, camera_0 грузится чисто. Полный визуальный smoke с камерой 0 — за владельцем.
- Преэкзистинг (НЕ моё): тесты `demo_webcam_split_merge` падают (рецепта нет в репо); `detector` set_config
  conflict (multi-plugin-in-process).

Связано: [[project_pipeline_live_control_stage2]], [[project_recipe_hotswap]], [[project_telemetry_self_publish]].
