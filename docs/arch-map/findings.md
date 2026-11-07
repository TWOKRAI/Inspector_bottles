# Находки правил

Сгенерировано `scripts/arch_map/build.py` (commit `1dc6c71b7`). Не править руками. Всего: 849.

| правило | error | warn | info | всего |
|---|---:|---:|---:|---:|
| layer-reverse | 0 | 0 | 0 | 0 |
| unit-cycle | 0 | 2 | 0 | 2 |
| deep-import | 0 | 638 | 0 | 638 |
| private-import | 0 | 26 | 0 | 26 |
| unit-hygiene | 0 | 0 | 67 | 67 |
| unit-undeclared | 0 | 0 | 111 | 111 |
| registry-drift | 0 | 1 | 0 | 1 |
| unresolved-relative | 0 | 0 | 1 | 1 |
| parse-error | 0 | 0 | 0 | 0 |
| unresolved-absolute | 0 | 0 | 1 | 1 |
| recipe-unknown-plugin | 0 | 2 | 0 | 2 |

## unit-cycle — 2

сильно связная компонента из 2+ юнитов; error, если внутри есть цикл по hard-рёбрам, иначе warn

- [warn] цикл из 6 вершин: multiprocess_framework.modules._fallback, multiprocess_framework.modules.base_manager, multiprocess_framework.modules.channel_routing_module, multiprocess_framework.modules.data_schema_module, multiprocess_framework.modules.error_module, multiprocess_framework.modules.logger_module; только с lazy-рёбрами
- [warn] цикл из 3 вершин: multiprocess_framework.modules.process_manager_module, multiprocess_framework.modules.process_module, multiprocess_framework.modules.statistics_module; только с lazy-рёбрами

## deep-import — 638

импорт из другого юнита мимо его витрины: цель — не `__init__` юнита, не его `interfaces` и не `__init__` пакета с литеральным `__all__`, в котором есть все импортируемые имена


### `Plugins._shared.fanin` -> `multiprocess_framework.modules.process_module` — 1 (warn 1)
- `Plugins/_shared/fanin/factory.py:19`

### `Plugins._shared.fanin` -> `multiprocess_framework.modules.router_module` — 1 (warn 1)
- `Plugins/_shared/fanin/join_inspector_manager.py:29`

### `Plugins.calibration.camera_robot` -> `Plugins.hub.device_hub` — 1 (warn 1)
- `Plugins/calibration/camera_robot/plugin.py:39`

### `Plugins.control.robot_control` -> `multiprocess_framework.modules.router_module` — 1 (warn 1)
- `Plugins/control/robot_control/plugin.py:53`

### `Plugins.hub.device_hub` -> `Services.device_hub` — 4 (warn 4)
- `Plugins/hub/device_hub/plugin.py:40`
- `Plugins/hub/device_hub/plugin.py:41`
- `Plugins/hub/device_hub/plugin.py:42`
- `Plugins/hub/device_hub/plugin.py:43`

### `Plugins.hub.device_hub` -> `Services.hikvision_camera` — 1 (warn 1)
- `Plugins/hub/device_hub/plugin.py:926`

### `Plugins.hub.device_hub` -> `Services.robot_comm` — 1 (warn 1)
- `Plugins/hub/device_hub/plugin.py:44`

### `Plugins.hub.device_hub` -> `multiprocess_framework.modules.message_module` — 2 (warn 2)
- `Plugins/hub/device_hub/client.py:114`
- `Plugins/hub/device_hub/client.py:161`

### `Plugins.io.otel_export` -> `Services.otel_export` — 5 (warn 5)
- `Plugins/io/otel_export/plugin.py:102`
- `Plugins/io/otel_export/plugin.py:103`
- `Plugins/io/otel_export/plugin.py:105`
- `Plugins/io/otel_export/plugin.py:106`
- `Plugins/io/otel_export/registers.py:41`

### `Plugins.io.otel_export` -> `multiprocess_framework.modules.channel_routing_module` — 2 (warn 2)
- `Plugins/io/otel_export/plugin.py:86`
- `Plugins/io/otel_export/plugin.py:89`

### `Plugins.io.otel_export` -> `multiprocess_framework.modules.logger_module` — 1 (warn 1)
- `Plugins/io/otel_export/plugin.py:92`

### `Plugins.io.otel_export` -> `multiprocess_framework.modules.message_module` — 1 (warn 1)
- `Plugins/io/otel_export/plugin.py:93`

### `Plugins.io.robot_draw` -> `Plugins.hub.device_hub` — 1 (warn 1)
- `Plugins/io/robot_draw/plugin.py:32`

### `Plugins.io.robot_draw` -> `Services.robot_comm` — 3 (warn 3)
- `Plugins/io/robot_draw/plugin.py:199`
- `Plugins/io/robot_draw/plugin.py:205`
- `Plugins/io/robot_draw/plugin.py:215`

### `Plugins.io.robot_io` -> `Plugins.hub.device_hub` — 1 (warn 1)
- `Plugins/io/robot_io/plugin.py:31`

### `Plugins.io.telemetry_sink` -> `multiprocess_framework.modules.state_store_module` — 1 (warn 1)
- `Plugins/io/telemetry_sink/plugin.py:49`

### `Plugins.processing.center_crop` -> `Services.layer_render` — 1 (warn 1)
- `Plugins/processing/center_crop/plugin.py:28`

### `Plugins.processing.pixel_to_robot` -> `Plugins.calibration.camera_robot` — 2 (warn 2)
- `Plugins/processing/pixel_to_robot/plugin.py:100`
- `Plugins/processing/pixel_to_robot/plugin.py:153`

### `Plugins.processing.region_split` -> `multiprocess_framework.modules.process_module` — 1 (warn 1)
- `Plugins/processing/region_split/plugin.py:12`

### `Plugins.processing.stitcher` -> `multiprocess_framework.modules.process_module` — 1 (warn 1)
- `Plugins/processing/stitcher/plugin.py:16`

### `Plugins.runtime.chain_executor` -> `multiprocess_framework.modules.process_module` — 1 (warn 1)
- `Plugins/runtime/chain_executor/plugin.py:30`

### `Plugins.runtime.worker_pool` -> `multiprocess_framework.modules.process_module` — 1 (warn 1)
- `Plugins/runtime/worker_pool/plugin.py:27`

### `Plugins.sim.layer_preview` -> `Services.line_sim` — 2 (warn 2)
- `Plugins/sim/layer_preview/plugin.py:83`
- `Plugins/sim/layer_preview/plugin.py:84`

### `Plugins.sim.layer_preview` -> `multiprocess_framework.modules.recipe` — 1 (warn 1)
- `Plugins/sim/layer_preview/plugin.py:70`

### `Plugins.sim.pult_web` -> `Plugins.hub.device_hub` — 1 (warn 1)
- `Plugins/sim/pult_web/plugin.py:71`

### `Plugins.sim.robot_host` -> `Plugins.hub.device_hub` — 1 (warn 1)
- `Plugins/sim/robot_host/plugin.py:69`

### `Plugins.sim.robot_host` -> `Services.modbus` — 1 (warn 1)
- `Plugins/sim/robot_host/plugin.py:377`

### `Plugins.sim.robot_host` -> `Services.robot_comm` — 5 (warn 5)
- `Plugins/sim/robot_host/plugin.py:378`
- `Plugins/sim/robot_host/plugin.py:384`
- `Plugins/sim/robot_host/plugin.py:70`
- `Plugins/sim/robot_host/plugin.py:71`
- `Plugins/sim/robot_host/plugin.py:72`

### `Plugins.sim.scene_source` -> `Services.dataset_gen` — 1 (warn 1)
- `Plugins/sim/scene_source/plugin.py:75`

### `Plugins.sim.scene_source` -> `Services.line_sim` — 1 (warn 1)
- `Plugins/sim/scene_source/plugin.py:89`

### `Plugins.sim.scene_source` -> `multiprocess_framework.modules.recipe` — 2 (warn 2)
- `Plugins/sim/scene_source/plugin.py:66`
- `Plugins/sim/scene_source/plugin.py:67`

### `Plugins.sim.scene_source` -> `multiprocess_framework.modules.state_store_module` — 2 (warn 2)
- `Plugins/sim/scene_source/plugin.py:74`
- `Plugins/sim/scene_source/plugin.py:92`

### `Plugins.sinks.modbus_sink` -> `Services.modbus` — 1 (warn 1)
- `Plugins/sinks/modbus_sink/plugin.py:30`

### `Plugins.sources.camera_service` -> `Plugins.hub.device_hub` — 1 (warn 1)
- `Plugins/sources/camera_service/plugin.py:250`

### `Plugins.sources.camera_service` -> `Services.hikvision_camera` — 4 (warn 4)
- `Plugins/sources/camera_service/backends/hikvision.py:17`
- `Plugins/sources/camera_service/backends/hikvision.py:18`
- `Plugins/sources/camera_service/backends/hikvision.py:19`
- `Plugins/sources/camera_service/backends/hikvision.py:20`

### `Services.auth` -> `Services.sql` — 2 (warn 2)
- `Services/auth/storage/audit_storage.py:35`
- `Services/auth/storage/audit_storage.py:36`

### `Services.code_reader` -> `Services.hikvision_camera` — 3 (warn 3)
- `Services/code_reader/tools/id3000_discover.py:45`
- `Services/code_reader/tools/id3000_discover.py:46`
- `Services/code_reader/tools/id3000_discover.py:47`

### `Services.dataset_gen` -> `Services.layer_render` — 13 (warn 13)
- `Services/dataset_gen/core/augment.py:28`
- `Services/dataset_gen/core/backgrounds.py:9`
- `Services/dataset_gen/core/catalog.py:10`
- `Services/dataset_gen/core/catalog.py:9`
- `Services/dataset_gen/core/compose.py:10`
- … и ещё 8

### `Services.device_hub` -> `Services.robot_comm` — 36 (warn 36)
- `Services/device_hub/drivers/exchange_log.py:45`
- `Services/device_hub/drivers/robot_driver.py:117`
- `Services/device_hub/drivers/robot_driver.py:457`
- `Services/device_hub/drivers/robot_driver.py:762`
- `Services/device_hub/drivers/robot_driver.py:960`
- … и ещё 31

### `Services.documents` -> `Services.sql` — 4 (warn 4)
- `Services/documents/store.py:16`
- `Services/documents/store.py:17`
- `Services/documents/store.py:77`
- `Services/documents/wiring.py:24`

### `Services.hikvision_camera` -> `multiprocess_framework.modules.process_module` — 4 (warn 4)
- `Services/hikvision_camera/plugin/config.py:9`
- `Services/hikvision_camera/plugin/plugin.py:22`
- `Services/hikvision_camera/plugin/plugin.py:26`
- `Services/hikvision_camera/plugin/plugin.py:27`

### `Services.line_sim` -> `Services.dataset_gen` — 5 (warn 5)
- `Services/line_sim/tools/build_stand_assets.py:40`
- `Services/line_sim/tools/make_demo_catalog.py:26`
- `Services/line_sim/tools/make_font_letters.py:80`
- `Services/line_sim/tools/make_letter_catalog.py:31`
- `Services/line_sim/tools/make_seamless_texture.py:44`

### `Services.line_sim` -> `Services.layer_render` — 12 (warn 12)
- `Services/line_sim/core/catalog_bridge.py:10`
- `Services/line_sim/core/catalog_bridge.py:9`
- `Services/line_sim/core/factory.py:15`
- `Services/line_sim/core/factory.py:16`
- `Services/line_sim/core/factory.py:17`
- … и ещё 7

### `Services.line_sim` -> `Services.robot_comm` — 1 (warn 1)
- `Services/line_sim/core/belt.py:10`

### `Services.ml_train` -> `Services.dataset_gen` — 2 (warn 2)
- `Services/ml_train/holdout_eval.py:34`
- `Services/ml_train/holdout_eval.py:35`

### `Services.ml_train` -> `Services.ml_inference` — 1 (warn 1)
- `Services/ml_train/holdout_eval.py:37`

### `Services.modbus` -> `multiprocess_framework.modules.router_module` — 1 (warn 1)
- `Services/modbus/channels/modbus_channel.py:21`

### `Services.otel_export` -> `multiprocess_framework.modules.channel_routing_module` — 3 (warn 3)
- `Services/otel_export/config.py:24`
- `Services/otel_export/mapping.py:52`
- `Services/otel_export/mapping.py:56`

### `Services.otel_export` -> `multiprocess_framework.modules.logger_module` — 1 (warn 1)
- `Services/otel_export/mapping.py:60`

### `Services.robot_comm` -> `Services.modbus` — 4 (warn 4)
- `Services/robot_comm/server/sim_core.py:27`
- `Services/robot_comm/server/sim_journal.py:73`
- `Services/robot_comm/server/sim_robot.py:30`
- `Services/robot_comm/testing/fake_transport.py:16`

### `Services.robot_comm` -> `Services.vfd_comm` — 10 (warn 10)
- `Services/robot_comm/server/sim_core_v2.py:247`
- `Services/robot_comm/server/sim_core_v2.py:248`
- `Services/robot_comm/server/sim_core_v2.py:249`
- `Services/robot_comm/server/sim_core_v2.py:250`
- `Services/robot_comm/server/sim_core_v2.py:251`
- … и ещё 5

### `Services.robot_comm` -> `multiprocess_framework.modules.frontend_module` — 1 (warn 1)
- `Services/robot_comm/gui/line_source.py:34`

### `Services.robot_comm` -> `multiprocess_framework.modules.router_module` — 1 (warn 1)
- `Services/robot_comm/gui/line_source.py:36`

### `Services.sql` -> `multiprocess_framework.modules.actions_module` — 4 (warn 4)
- `Services/sql/action_log/log_writer.py:22`
- `Services/sql/action_log/recovery.py:17`
- `Services/sql/action_log/repository.py:16`
- `Services/sql/action_log/schema_ext.py:18`

### `Services.vfd_comm` -> `Services.modbus` — 1 (warn 1)
- `Services/vfd_comm/core/client.py:21`

### `multiprocess_framework.__root__` -> `multiprocess_framework.modules.logger_module` — 1 (warn 1)
- `multiprocess_framework/modules/_fallback.py:91`

### `multiprocess_framework.modules.app_module` -> `multiprocess_framework.modules.config_module` — 1 (warn 1)
- `multiprocess_framework/modules/app_module/orchestrator.py:429`

### `multiprocess_framework.modules.app_module` -> `multiprocess_framework.modules.data_schema_module` — 1 (warn 1)
- `multiprocess_framework/modules/app_module/builder.py:228`

### `multiprocess_framework.modules.app_module` -> `multiprocess_framework.modules.process_manager_module` — 6 (warn 6)
- `multiprocess_framework/modules/app_module/builder.py:229`
- `multiprocess_framework/modules/app_module/builder.py:232`
- `multiprocess_framework/modules/app_module/builder.py:38`
- `multiprocess_framework/modules/app_module/entry.py:20`
- `multiprocess_framework/modules/app_module/interfaces.py:26`
- … и ещё 1

### `multiprocess_framework.modules.app_module` -> `multiprocess_framework.modules.process_module` — 11 (warn 11)
- `multiprocess_framework/modules/app_module/builder.py:235`
- `multiprocess_framework/modules/app_module/builder.py:376`
- `multiprocess_framework/modules/app_module/builder.py:461`
- `multiprocess_framework/modules/app_module/discovery.py:129`
- `multiprocess_framework/modules/app_module/orchestrator.py:151`
- … и ещё 6

### `multiprocess_framework.modules.app_module` -> `multiprocess_framework.modules.state_store_module` — 3 (warn 3)
- `multiprocess_framework/modules/app_module/orchestrator.py:395`
- `multiprocess_framework/modules/app_module/orchestrator.py:419`
- `multiprocess_framework/modules/app_module/orchestrator.py:432`

### `multiprocess_framework.modules.base_manager` -> `multiprocess_framework.modules.channel_routing_module` — 1 (warn 1)
- `multiprocess_framework/modules/base_manager/mixins/observable_mixin.py:414`

### `multiprocess_framework.modules.base_manager` -> `multiprocess_framework.modules.error_module` — 1 (warn 1)
- `multiprocess_framework/modules/base_manager/mixins/observable_mixin.py:593`

### `multiprocess_framework.modules.base_manager` -> `multiprocess_framework.modules.logger_module` — 3 (warn 3)
- `multiprocess_framework/modules/base_manager/mixins/observable_mixin.py:301`
- `multiprocess_framework/modules/base_manager/mixins/observable_mixin.py:415`
- `multiprocess_framework/modules/base_manager/mixins/observable_mixin.py:416`

### `multiprocess_framework.modules.channel_routing_module` -> `multiprocess_framework.modules.logger_module` — 3 (warn 3)
- `multiprocess_framework/modules/channel_routing_module/observability/batch_drain.py:514`
- `multiprocess_framework/modules/channel_routing_module/observability/observability_store.py:657`
- `multiprocess_framework/modules/channel_routing_module/observability/store_tap.py:281`

### `multiprocess_framework.modules.command_module` -> `multiprocess_framework.modules.base_manager` — 1 (warn 1)
- `multiprocess_framework/modules/command_module/adapters/command_adapter.py:9`

### `multiprocess_framework.modules.config_module` -> `multiprocess_framework.modules.data_schema_module` — 3 (warn 3)
- `multiprocess_framework/modules/config_module/core/config.py:18`
- `multiprocess_framework/modules/config_module/tools/loader.py:77`
- `multiprocess_framework/modules/config_module/tools/watcher.py:168`

### `multiprocess_framework.modules.config_module` -> `multiprocess_framework.modules.shared_resources_module` — 1 (warn 1)
- `multiprocess_framework/modules/config_module/core/config_manager.py:24`

### `multiprocess_framework.modules.console_module` -> `multiprocess_framework.modules.base_manager` — 1 (warn 1)
- `multiprocess_framework/modules/console_module/adapters/console_adapter.py:12`

### `multiprocess_framework.modules.data_schema_module` -> `multiprocess_framework.modules.process_module` — 1 (warn 1)
- `multiprocess_framework/modules/data_schema_module/storage/storage_manager.py:14`

### `multiprocess_framework.modules.data_schema_module` -> `multiprocess_framework.modules.shared_resources_module` — 1 (warn 1)
- `multiprocess_framework/modules/data_schema_module/storage/storage_manager.py:22`

### `multiprocess_framework.modules.error_module` -> `multiprocess_framework.modules.channel_routing_module` — 2 (warn 2)
- `multiprocess_framework/modules/error_module/core/error_manager.py:31`
- `multiprocess_framework/modules/error_module/core/error_manager.py:32`

### `multiprocess_framework.modules.error_module` -> `multiprocess_framework.modules.logger_module` — 4 (warn 4)
- `multiprocess_framework/modules/error_module/core/error_manager.py:33`
- `multiprocess_framework/modules/error_module/core/error_manager.py:34`
- `multiprocess_framework/modules/error_module/core/error_manager.py:35`
- `multiprocess_framework/modules/error_module/interfaces.py:30`

### `multiprocess_framework.modules.frontend_module` -> `multiprocess_framework.modules.actions_module` — 1 (warn 1)
- `multiprocess_framework/modules/frontend_module/forms/form_context.py:17`

### `multiprocess_framework.modules.frontend_module` -> `multiprocess_framework.modules.logger_module` — 3 (warn 3)
- `multiprocess_framework/modules/frontend_module/managers/theme_manager.py:24`
- `multiprocess_framework/modules/frontend_module/managers/theme_presets_manager.py:22`
- `multiprocess_framework/modules/frontend_module/managers/yaml_persistence_store.py:11`

### `multiprocess_framework.modules.frontend_module` -> `multiprocess_framework.modules.message_module` — 1 (warn 1)
- `multiprocess_framework/modules/frontend_module/bridge/remote_command_sender.py:54`

### `multiprocess_framework.modules.frontend_module` -> `multiprocess_framework.modules.process_module` — 1 (warn 1)
- `multiprocess_framework/modules/frontend_module/core/qt_gc_policy.py:47`

### `multiprocess_framework.modules.frontend_module` -> `multiprocess_framework.modules.router_module` — 3 (warn 3)
- `multiprocess_framework/modules/frontend_module/bridge/remote_command_sender.py:58`
- `multiprocess_framework/modules/frontend_module/bridge/remote_frame_source.py:50`
- `multiprocess_framework/modules/frontend_module/bridge/remote_state_proxy.py:36`

### `multiprocess_framework.modules.frontend_module` -> `multiprocess_framework.modules.shared_resources_module` — 1 (warn 1)
- `multiprocess_framework/modules/frontend_module/bridge/wire_protocol.py:17`

### `multiprocess_framework.modules.logger_module` -> `multiprocess_framework.modules.channel_routing_module` — 4 (warn 4)
- `multiprocess_framework/modules/logger_module/__init__.py:37`
- `multiprocess_framework/modules/logger_module/configs/logger_manager_config.py:15`
- `multiprocess_framework/modules/logger_module/core/logger_core.py:41`
- `multiprocess_framework/modules/logger_module/core/sampling.py:88`

### `multiprocess_framework.modules.process_manager_module` -> `multiprocess_framework.modules.config_module` — 4 (warn 4)
- `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:454`
- `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:17`
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:21`
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:266`

### `multiprocess_framework.modules.process_manager_module` -> `multiprocess_framework.modules.logger_module` — 7 (warn 7)
- `multiprocess_framework/modules/process_manager_module/launcher/spawner.py:11`
- `multiprocess_framework/modules/process_manager_module/launcher/spawner.py:12`
- `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:15`
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:24`
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:4430`
- … и ещё 2

### `multiprocess_framework.modules.process_manager_module` -> `multiprocess_framework.modules.message_module` — 2 (warn 2)
- `multiprocess_framework/modules/process_manager_module/topology/blueprint.py:1256`
- `multiprocess_framework/modules/process_manager_module/topology/blueprint.py:730`

### `multiprocess_framework.modules.process_manager_module` -> `multiprocess_framework.modules.process_module` — 21 (warn 21)
- `multiprocess_framework/modules/process_manager_module/launcher/spawner.py:15`
- `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:215`
- `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:216`
- `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:18`
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1015`
- … и ещё 16

### `multiprocess_framework.modules.process_manager_module` -> `multiprocess_framework.modules.shared_resources_module` — 4 (warn 4)
- `multiprocess_framework/modules/process_manager_module/core/process_registry.py:26`
- `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:68`
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:31`
- `multiprocess_framework/modules/process_manager_module/topology/blueprint.py:669`

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.base_manager` — 2 (warn 2)
- `multiprocess_framework/modules/process_module/adapters/process_adapter.py:17`
- `multiprocess_framework/modules/process_module/types/types.py:14`

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.channel_routing_module` — 6 (warn 6)
- `multiprocess_framework/modules/process_module/commands/builtin_commands.py:17`
- `multiprocess_framework/modules/process_module/commands/builtin_commands.py:3358`
- `multiprocess_framework/modules/process_module/configs/observability_config.py:38`
- `multiprocess_framework/modules/process_module/core/process_module.py:18`
- `multiprocess_framework/modules/process_module/health/state.py:37`
- … и ещё 1

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.command_module` — 1 (warn 1)
- `multiprocess_framework/modules/process_module/configs/managers_config.py:18`

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.config_module` — 9 (warn 9)
- `multiprocess_framework/modules/process_module/commands/builtin_commands.py:4166`
- `multiprocess_framework/modules/process_module/generic/data_receiver.py:82`
- `multiprocess_framework/modules/process_module/generic/perf_probes.py:25`
- `multiprocess_framework/modules/process_module/generic/plugin_runner.py:42`
- `multiprocess_framework/modules/process_module/lifecycle/gc_discipline.py:60`
- … и ещё 4

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.console_module` — 4 (warn 4)
- `multiprocess_framework/modules/process_module/configs/console_process_config.py:12`
- `multiprocess_framework/modules/process_module/configs/managers_config.py:19`
- `multiprocess_framework/modules/process_module/managers/process_managers.py:214`
- `multiprocess_framework/modules/process_module/managers/process_managers.py:495`

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.data_schema_module` — 4 (warn 4)
- `multiprocess_framework/modules/process_module/commands/builtin_commands.py:1942`
- `multiprocess_framework/modules/process_module/configs/observability_companion.py:65`
- `multiprocess_framework/modules/process_module/managers/observability_reload.py:2294`
- `multiprocess_framework/modules/process_module/managers/telemetry_reload.py:703`

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.error_module` — 1 (warn 1)
- `multiprocess_framework/modules/process_module/configs/managers_config.py:21`

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.logger_module` — 21 (warn 21)
- `multiprocess_framework/modules/process_module/commands/builtin_commands.py:3618`
- `multiprocess_framework/modules/process_module/commands/builtin_commands.py:3669`
- `multiprocess_framework/modules/process_module/communication/process_communication.py:14`
- `multiprocess_framework/modules/process_module/configs/managers_config.py:22`
- `multiprocess_framework/modules/process_module/configs/managers_config.py:23`
- … и ещё 16

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.process_manager_module` — 3 (warn 3)
- `multiprocess_framework/modules/process_module/__init__.py:119`
- `multiprocess_framework/modules/process_module/__init__.py:123`
- `multiprocess_framework/modules/process_module/__init__.py:127`

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.registers_module` — 1 (warn 1)
- `multiprocess_framework/modules/process_module/commands/builtin_commands.py:996`

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.router_module` — 11 (warn 11)
- `multiprocess_framework/modules/process_module/commands/builtin_commands.py:3778`
- `multiprocess_framework/modules/process_module/configs/managers_config.py:24`
- `multiprocess_framework/modules/process_module/generic/__init__.py:19`
- `multiprocess_framework/modules/process_module/generic/data_receiver.py:20`
- `multiprocess_framework/modules/process_module/generic/data_receiver.py:21`
- … и ещё 6

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.shared_resources_module` — 1 (warn 1)
- `multiprocess_framework/modules/process_module/state/process_data.py:10`

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.state_store_module` — 1 (warn 1)
- `multiprocess_framework/modules/process_module/generic/generic_process.py:82`

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.statistics_module` — 9 (warn 9)
- `multiprocess_framework/modules/process_module/configs/managers_config.py:25`
- `multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py:1216`
- `multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py:63`
- `multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py:701`
- `multiprocess_framework/modules/process_module/heartbeat/telemetry.py:29`
- … и ещё 4

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.modules.worker_module` — 3 (warn 3)
- `multiprocess_framework/modules/process_module/commands/builtin_commands.py:463`
- `multiprocess_framework/modules/process_module/managers/process_managers.py:217`
- `multiprocess_framework/modules/process_module/managers/process_managers.py:271`

### `multiprocess_framework.modules.router_module` -> `multiprocess_framework.modules.base_manager` — 1 (warn 1)
- `multiprocess_framework/modules/router_module/adapters/router_adapter.py:20`

### `multiprocess_framework.modules.router_module` -> `multiprocess_framework.modules.config_module` — 2 (warn 2)
- `multiprocess_framework/modules/router_module/core/router_manager.py:17`
- `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:679`

### `multiprocess_framework.modules.router_module` -> `multiprocess_framework.modules.shared_resources_module` — 1 (warn 1)
- `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:694`

### `multiprocess_framework.modules.shared_resources_module` -> `multiprocess_framework.modules.base_manager` — 1 (warn 1)
- `multiprocess_framework/modules/shared_resources_module/types/types.py:18`

### `multiprocess_framework.modules.shared_resources_module` -> `multiprocess_framework.modules.config_module` — 1 (warn 1)
- `multiprocess_framework/modules/shared_resources_module/queues/core/manager.py:163`

### `multiprocess_framework.modules.shared_resources_module` -> `multiprocess_framework.modules.data_schema_module` — 1 (warn 1)
- `multiprocess_framework/modules/shared_resources_module/adapters/data_schema_adapter.py:29`

### `multiprocess_framework.modules.shared_resources_module` -> `multiprocess_framework.modules.logger_module` — 2 (warn 2)
- `multiprocess_framework/modules/shared_resources_module/memory/platform/shm.py:20`
- `multiprocess_framework/modules/shared_resources_module/queues/core/manager.py:16`

### `multiprocess_framework.modules.state_store_module` -> `multiprocess_framework.modules.recipe` — 1 (warn 1)
- `multiprocess_framework/modules/state_store_module/recipes/recipe_engine.py:17`

### `multiprocess_framework.modules.state_store_module` -> `multiprocess_framework.modules.router_module` — 1 (warn 1)
- `multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:28`

### `multiprocess_framework.modules.statistics_module` -> `multiprocess_framework.modules.base_manager` — 1 (warn 1)
- `multiprocess_framework/modules/statistics_module/adapters/stats_adapter.py:11`

### `multiprocess_framework.modules.statistics_module` -> `multiprocess_framework.modules.channel_routing_module` — 2 (warn 2)
- `multiprocess_framework/modules/statistics_module/channels/log_stats_channel.py:11`
- `multiprocess_framework/modules/statistics_module/core/stats_manager.py:25`

### `multiprocess_framework.modules.statistics_module` -> `multiprocess_framework.modules.logger_module` — 2 (warn 2)
- `multiprocess_framework/modules/statistics_module/channels/log_stats_channel.py:156`
- `multiprocess_framework/modules/statistics_module/core/stats_manager.py:31`

### `multiprocess_framework.modules.statistics_module` -> `multiprocess_framework.modules.process_module` — 2 (warn 2)
- `multiprocess_framework/modules/statistics_module/observation/observation_manager.py:135`
- `multiprocess_framework/modules/statistics_module/observation/observation_manager.py:253`

### `multiprocess_framework.modules.worker_module` -> `multiprocess_framework.modules.base_manager` — 1 (warn 1)
- `multiprocess_framework/modules/worker_module/adapters/worker_adapter.py:20`

### `multiprocess_prototype.__root__` -> `multiprocess_framework.modules.app_module` — 1 (warn 1)
- `multiprocess_prototype/orchestrator.py:26`

### `multiprocess_prototype.__root__` -> `multiprocess_framework.modules.process_manager_module` — 1 (warn 1)
- `multiprocess_prototype/main.py:21`

### `multiprocess_prototype.__root__` -> `multiprocess_framework.modules.process_module` — 1 (warn 1)
- `multiprocess_prototype/generic_process_app.py:9`

### `multiprocess_prototype.__root__` -> `multiprocess_framework.modules.recipe` — 1 (warn 1)
- `multiprocess_prototype/orchestrator.py:141`

### `multiprocess_prototype.__root__` -> `multiprocess_prototype.backend` — 8 (warn 8)
- `multiprocess_prototype/main.py:107`
- `multiprocess_prototype/main.py:154`
- `multiprocess_prototype/main.py:25`
- `multiprocess_prototype/main.py:76`
- `multiprocess_prototype/main.py:86`
- … и ещё 3

### `multiprocess_prototype.adapters` -> `multiprocess_framework.modules.display_module` — 1 (warn 1)
- `multiprocess_prototype/adapters/catalogs/display_catalog.py:26`

### `multiprocess_prototype.adapters` -> `multiprocess_framework.modules.process_module` — 1 (warn 1)
- `multiprocess_prototype/adapters/catalogs/plugin_catalog.py:22`

### `multiprocess_prototype.adapters` -> `multiprocess_framework.modules.recipe` — 2 (warn 2)
- `multiprocess_prototype/adapters/recipe_canonical.py:36`
- `multiprocess_prototype/adapters/stores/recipe_store.py:31`

### `multiprocess_prototype.adapters` -> `multiprocess_framework.modules.service_module` — 2 (warn 2)
- `multiprocess_prototype/adapters/catalogs/service_catalog.py:33`
- `multiprocess_prototype/adapters/catalogs/service_catalog.py:35`

### `multiprocess_prototype.adapters` -> `multiprocess_prototype.domain` — 32 (warn 32)
- `multiprocess_prototype/adapters/catalogs/display_catalog.py:27`
- `multiprocess_prototype/adapters/catalogs/display_catalog_recipe.py:32`
- `multiprocess_prototype/adapters/catalogs/display_catalog_recipe.py:33`
- `multiprocess_prototype/adapters/catalogs/display_catalog_recipe.py:42`
- `multiprocess_prototype/adapters/catalogs/plugin_catalog.py:26`
- … и ещё 27

### `multiprocess_prototype.adapters` -> `multiprocess_prototype.recipes` — 1 (warn 1)
- `multiprocess_prototype/adapters/stores/recipe_store.py:35`

### `multiprocess_prototype.backend` -> `multiprocess_framework.modules.app_module` — 2 (warn 2)
- `multiprocess_prototype/backend/config/manifest.py:132`
- `multiprocess_prototype/backend/orchestrator_hooks.py:24`

### `multiprocess_prototype.backend` -> `multiprocess_framework.modules.data_schema_module` — 1 (warn 1)
- `multiprocess_prototype/backend/assembly/assembler.py:22`

### `multiprocess_prototype.backend` -> `multiprocess_framework.modules.process_manager_module` — 3 (warn 3)
- `multiprocess_prototype/backend/assembly/assembler.py:25`
- `multiprocess_prototype/backend/assembly/assembler.py:36`
- `multiprocess_prototype/backend/launch.py:28`

### `multiprocess_prototype.backend` -> `multiprocess_framework.modules.process_module` — 4 (warn 4)
- `multiprocess_prototype/backend/assembly/assembler.py:28`
- `multiprocess_prototype/backend/assembly/planner.py:110`
- `multiprocess_prototype/backend/launch.py:22`
- `multiprocess_prototype/backend/launch.py:720`

### `multiprocess_prototype.backend` -> `multiprocess_framework.modules.recipe` — 4 (warn 4)
- `multiprocess_prototype/backend/launch.py:25`
- `multiprocess_prototype/backend/recipe_format_hook.py:24`
- `multiprocess_prototype/backend/state/recipes/migrations/v1_to_v2.py:25`
- `multiprocess_prototype/backend/state/recipes/recipe_engine.py:22`

### `multiprocess_prototype.backend` -> `multiprocess_prototype.recipes` — 5 (warn 5)
- `multiprocess_prototype/backend/launch.py:575`
- `multiprocess_prototype/backend/orchestrator_hooks.py:58`
- `multiprocess_prototype/backend/recipe_format_hook.py:26`
- `multiprocess_prototype/backend/recipe_format_hook.py:27`
- `multiprocess_prototype/backend/recipe_format_hook.py:28`

### `multiprocess_prototype.frontend` -> `Plugins.sources.camera_service` — 2 (warn 2)
- `multiprocess_prototype/frontend/widgets/tabs/plugins/sandbox.py:524`
- `multiprocess_prototype/frontend/widgets/tabs/services/camera/widget.py:27`

### `multiprocess_prototype.frontend` -> `Services.auth` — 4 (warn 4)
- `multiprocess_prototype/frontend/actions/middleware/audit_middleware.py:28`
- `multiprocess_prototype/frontend/auth_context.py:29`
- `multiprocess_prototype/frontend/widgets/dialogs/login_dialog.py:26`
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/users_panel.py:24`

### `multiprocess_prototype.frontend` -> `Services.control_panel` — 1 (warn 1)
- `multiprocess_prototype/frontend/widgets/tabs/services/control_panel/presenter.py:86`

### `multiprocess_prototype.frontend` -> `Services.dataset_gen` — 2 (warn 2)
- `multiprocess_prototype/frontend/widgets/tabs/services/neural/disk_cutter_section.py:167`
- `multiprocess_prototype/frontend/widgets/tabs/services/neural/disk_cutter_section.py:66`

### `multiprocess_prototype.frontend` -> `Services.ml_inference` — 2 (warn 2)
- `multiprocess_prototype/frontend/forms/model_picker.py:20`
- `multiprocess_prototype/frontend/widgets/tabs/services/neural/ml_inference_section.py:75`

### `multiprocess_prototype.frontend` -> `Services.phone_gateway` — 2 (warn 2)
- `multiprocess_prototype/frontend/widgets/tabs/services/phone/section.py:20`
- `multiprocess_prototype/frontend/widgets/tabs/services/phone/section.py:21`

### `multiprocess_prototype.frontend` -> `multiprocess_framework.modules.actions_module` — 13 (warn 13)
- `multiprocess_prototype/frontend/actions/__init__.py:7`
- `multiprocess_prototype/frontend/actions/__init__.py:8`
- `multiprocess_prototype/frontend/actions/__init__.py:9`
- `multiprocess_prototype/frontend/actions/builder.py:8`
- `multiprocess_prototype/frontend/actions/builder.py:9`
- … и ещё 8

### `multiprocess_prototype.frontend` -> `multiprocess_framework.modules.channel_routing_module` — 1 (warn 1)
- `multiprocess_prototype/frontend/process.py:15`

### `multiprocess_prototype.frontend` -> `multiprocess_framework.modules.config_module` — 2 (warn 2)
- `multiprocess_prototype/frontend/app_services_factory.py:176`
- `multiprocess_prototype/frontend/bridge_process.py:211`

### `multiprocess_prototype.frontend` -> `multiprocess_framework.modules.frontend_module` — 59 (warn 59)
- `multiprocess_prototype/frontend/app.py:14`
- `multiprocess_prototype/frontend/app.py:206`
- `multiprocess_prototype/frontend/app.py:742`
- `multiprocess_prototype/frontend/bridge/command_sender.py:3`
- `multiprocess_prototype/frontend/bridge/command_sender.py:4`
- … и ещё 54

### `multiprocess_prototype.frontend` -> `multiprocess_framework.modules.logger_module` — 1 (warn 1)
- `multiprocess_prototype/frontend/styles/style_manifest.py:17`

### `multiprocess_prototype.frontend` -> `multiprocess_framework.modules.process_manager_module` — 1 (warn 1)
- `multiprocess_prototype/frontend/widgets/topology/presenter.py:12`

### `multiprocess_prototype.frontend` -> `multiprocess_framework.modules.process_module` — 9 (warn 9)
- `multiprocess_prototype/frontend/app.py:18`
- `multiprocess_prototype/frontend/app.py:307`
- `multiprocess_prototype/frontend/app.py:323`
- `multiprocess_prototype/frontend/headless_process.py:42`
- `multiprocess_prototype/frontend/process.py:18`
- … и ещё 4

### `multiprocess_prototype.frontend` -> `multiprocess_framework.modules.recipe` — 3 (warn 3)
- `multiprocess_prototype/frontend/app.py:47`
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/recipe_io.py:25`
- `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:24`

### `multiprocess_prototype.frontend` -> `multiprocess_framework.modules.registers_module` — 14 (warn 14)
- `multiprocess_prototype/frontend/forms/factory/__init__.py:23`
- `multiprocess_prototype/frontend/forms/factory/_common.py:12`
- `multiprocess_prototype/frontend/forms/factory/builders_binding.py:22`
- `multiprocess_prototype/frontend/forms/factory/builders_legacy.py:28`
- `multiprocess_prototype/frontend/forms/factory/json_editor.py:16`
- … и ещё 9

### `multiprocess_prototype.frontend` -> `multiprocess_framework.modules.service_module` — 1 (warn 1)
- `multiprocess_prototype/frontend/widgets/tabs/services/presenter.py:156`

### `multiprocess_prototype.frontend` -> `multiprocess_framework.modules.state_store_module` — 3 (warn 3)
- `multiprocess_prototype/frontend/app.py:622`
- `multiprocess_prototype/frontend/process.py:67`
- `multiprocess_prototype/frontend/state/delta_message.py:29`

### `multiprocess_prototype.frontend` -> `multiprocess_prototype.backend` — 12 (warn 12)
- `multiprocess_prototype/frontend/app.py:292`
- `multiprocess_prototype/frontend/app.py:309`
- `multiprocess_prototype/frontend/app.py:48`
- `multiprocess_prototype/frontend/app.py:592`
- `multiprocess_prototype/frontend/app.py:628`
- … и ещё 7

### `multiprocess_prototype.frontend` -> `multiprocess_prototype.domain` — 56 (warn 56)
- `multiprocess_prototype/frontend/app.py:1133`
- `multiprocess_prototype/frontend/app.py:816`
- `multiprocess_prototype/frontend/app.py:832`
- `multiprocess_prototype/frontend/app.py:864`
- `multiprocess_prototype/frontend/app_services_factory.py:39`
- … и ещё 51

### `multiprocess_prototype.frontend` -> `multiprocess_prototype.recipes` — 7 (warn 7)
- `multiprocess_prototype/frontend/app.py:138`
- `multiprocess_prototype/frontend/app.py:630`
- `multiprocess_prototype/frontend/app.py:631`
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/layout_controller.py:452`
- `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:417`
- … и ещё 2

### `multiprocess_prototype.frontend` -> `multiprocess_prototype.registers` — 6 (warn 6)
- `multiprocess_prototype/frontend/app.py:530`
- `multiprocess_prototype/frontend/bridge/command_catalog.py:224`
- `multiprocess_prototype/frontend/managers/theme_presets_manager.py:33`
- `multiprocess_prototype/frontend/styles/theme_loader.py:37`
- `multiprocess_prototype/frontend/widgets/tabs/settings/appearance/presenter.py:21`
- … и ещё 1

### `multiprocess_prototype.recipes` -> `multiprocess_framework.modules.process_manager_module` — 1 (warn 1)
- `multiprocess_prototype/recipes/save.py:173`

### `multiprocess_prototype.recipes` -> `multiprocess_framework.modules.recipe` — 6 (warn 6)
- `multiprocess_prototype/recipes/format.py:11`
- `multiprocess_prototype/recipes/manager.py:15`
- `multiprocess_prototype/recipes/migrations/canonicalize_gui_positions.py:79`
- `multiprocess_prototype/recipes/migrations/format_v1_to_v2.py:43`
- `multiprocess_prototype/recipes/save.py:47`
- … и ещё 1

### `multiprocess_prototype.recipes` -> `multiprocess_prototype.adapters` — 1 (warn 1)
- `multiprocess_prototype/recipes/save.py:344`

## private-import — 26

из другого юнита импортируется имя или модуль с `_` в начале


### `Plugins.__root__` -> `Plugins._shared.__root__` — 1 (warn 1)
- `Plugins/__init__.py:17`

### `Services.dataset_gen` -> `Services.layer_render` — 1 (warn 1)
- `Services/dataset_gen/core/backgrounds.py:9`

### `Services.documents` -> `multiprocess_framework.__root__` — 1 (warn 1)
- `Services/documents/wiring.py:23`

### `Services.line_sim` -> `Services.layer_render` — 1 (warn 1)
- `Services/line_sim/core/factory.py:16`

### `multiprocess_framework.modules.base_manager` -> `multiprocess_framework.__root__` — 2 (warn 2)
- `multiprocess_framework/modules/base_manager/adapters/base_adapter.py:10`
- `multiprocess_framework/modules/base_manager/core/base_manager.py:9`

### `multiprocess_framework.modules.channel_routing_module` -> `multiprocess_framework.__root__` — 3 (warn 3)
- `multiprocess_framework/modules/channel_routing_module/core/channel_registry.py:22`
- `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py:27`
- `multiprocess_framework/modules/channel_routing_module/observability/observability_store.py:42`

### `multiprocess_framework.modules.logger_module` -> `multiprocess_framework.__root__` — 4 (warn 4)
- `multiprocess_framework/modules/logger_module/channels/log_channel.py:26`
- `multiprocess_framework/modules/logger_module/core/process_hooks.py:69`
- `multiprocess_framework/modules/logger_module/core/windowed_voice.py:135`
- `multiprocess_framework/modules/logger_module/utils.py:5`

### `multiprocess_framework.modules.process_manager_module` -> `multiprocess_framework.__root__` — 5 (warn 5)
- `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:237`
- `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:265`
- `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:285`
- `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:317`
- `multiprocess_framework/modules/process_manager_module/runner/process_runner.py:18`

### `multiprocess_framework.modules.process_manager_module` -> `multiprocess_framework.modules.shared_resources_module` — 1 (warn 1)
- `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:68`

### `multiprocess_framework.modules.process_module` -> `multiprocess_framework.__root__` — 4 (warn 4)
- `multiprocess_framework/modules/process_module/configs/observability_config.py:33`
- `multiprocess_framework/modules/process_module/core/process_module.py:16`
- `multiprocess_framework/modules/process_module/lifecycle/process_lifecycle.py:13`
- `multiprocess_framework/modules/process_module/managers/observability_reload.py:249`

### `multiprocess_framework.modules.router_module` -> `multiprocess_framework.__root__` — 1 (warn 1)
- `multiprocess_framework/modules/router_module/adapters/socket_bridge_adapter.py:25`

### `multiprocess_prototype.adapters` -> `multiprocess_framework.modules.process_module` — 1 (warn 1)
- `multiprocess_prototype/adapters/catalogs/plugin_catalog.py:22`

### `multiprocess_prototype.frontend` -> `multiprocess_prototype.domain` — 1 (warn 1)
- `multiprocess_prototype/frontend/widgets/tabs/displays/presenter.py:28`

## unit-hygiene — 67

у юнита нет interfaces.py, README.md, STATUS.md или тестов

- [info] `Plugins._shared.fanin` — нет: interfaces.py, STATUS.md
- [info] `Plugins.calibration.camera_robot` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.control.robot_control` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.filter.line_filter` — нет: interfaces.py
- [info] `Plugins.hub.device_hub` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.io.database` — нет: interfaces.py
- [info] `Plugins.io.drawing_io` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.io.frame_saver` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.io.otel_export` — нет: interfaces.py
- [info] `Plugins.io.robot_draw` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.io.robot_io` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.io.telemetry_sink` — нет: interfaces.py
- [info] `Plugins.processing.blob_detector` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.blob_filter` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.blur` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.center_crop` — нет: interfaces.py
- [info] `Plugins.processing.circle_detector` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.color_convert` — нет: interfaces.py, README.md, STATUS.md, тесты
- [info] `Plugins.processing.color_mask` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.contour_draw` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.contour_finder` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.crop` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.edge_detection` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.flip` — нет: interfaces.py, README.md, STATUS.md, тесты
- [info] `Plugins.processing.grayscale` — нет: interfaces.py, README.md, STATUS.md, тесты
- [info] `Plugins.processing.hsv_mask` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.image_adjust` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.mask_to_frame` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.morphology` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.negative` — нет: interfaces.py, README.md, STATUS.md, тесты
- [info] `Plugins.processing.pixel_to_robot` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.points_render` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.region_split` — нет: interfaces.py, README.md, STATUS.md, тесты
- [info] `Plugins.processing.resize` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.robot_scale` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.roi_crop` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.segmentation` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.stitcher` — нет: interfaces.py, README.md, STATUS.md, тесты
- [info] `Plugins.processing.strokes_to_points` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.text_vector` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.processing.word_layout` — нет: interfaces.py
- [info] `Plugins.render.circle_draw` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.render.overlay_draw` — нет: interfaces.py
- [info] `Plugins.render.render_overlay` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.render.renderer_compositor` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.runtime.chain_executor` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.runtime.worker_pool` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.sim.layer_preview` — нет: interfaces.py
- [info] `Plugins.sim.mjpeg_sink` — нет: interfaces.py
- [info] `Plugins.sim.pult_web` — нет: interfaces.py
- [info] `Plugins.sim.robot_host` — нет: interfaces.py
- [info] `Plugins.sim.scene_source` — нет: interfaces.py
- [info] `Plugins.sinks.modbus_sink` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.sources.camera_service` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.sources.capture` — нет: interfaces.py, README.md, STATUS.md
- [info] `Plugins.sources.frame_counter` — нет: interfaces.py, README.md, STATUS.md, тесты
- [info] `Plugins.sources.heartbeat` — нет: interfaces.py, README.md, STATUS.md, тесты
- [info] `Plugins.sources.synthetic_frame_source` — нет: interfaces.py, README.md, STATUS.md, тесты
- [info] `Plugins.utility.pilot_widgets` — нет: interfaces.py, README.md, STATUS.md, тесты
- [info] `Services.camera_device` — нет: interfaces.py
- [info] `Services.device_hub` — нет: interfaces.py
- [info] `multiprocess_prototype.adapters` — нет: interfaces.py, STATUS.md
- [info] `multiprocess_prototype.backend` — нет: interfaces.py, README.md, STATUS.md
- [info] `multiprocess_prototype.domain` — нет: interfaces.py, STATUS.md
- [info] `multiprocess_prototype.frontend` — нет: interfaces.py, STATUS.md
- [info] `multiprocess_prototype.recipes` — нет: interfaces.py, README.md, STATUS.md
- [info] `multiprocess_prototype.registers` — нет: interfaces.py, README.md, STATUS.md

## unit-undeclared — 111

у юнита не объявлено поле карточки (purpose, tier, contour)

- [info] `Plugins._shared.fanin` — не объявлено: tier, contour
- [info] `Plugins.calibration.camera_robot` — не объявлено: tier, contour
- [info] `Plugins.control.robot_control` — не объявлено: tier, contour
- [info] `Plugins.filter.line_filter` — не объявлено: tier, contour
- [info] `Plugins.hub.device_hub` — не объявлено: tier, contour
- [info] `Plugins.io.database` — не объявлено: tier, contour
- [info] `Plugins.io.drawing_io` — не объявлено: tier, contour
- [info] `Plugins.io.frame_saver` — не объявлено: tier, contour
- [info] `Plugins.io.otel_export` — не объявлено: tier, contour
- [info] `Plugins.io.robot_draw` — не объявлено: tier, contour
- [info] `Plugins.io.robot_io` — не объявлено: tier, contour
- [info] `Plugins.io.telemetry_sink` — не объявлено: tier, contour
- [info] `Plugins.processing.blob_detector` — не объявлено: tier, contour
- [info] `Plugins.processing.blob_filter` — не объявлено: tier, contour
- [info] `Plugins.processing.blur` — не объявлено: tier, contour
- [info] `Plugins.processing.center_crop` — не объявлено: tier, contour
- [info] `Plugins.processing.circle_detector` — не объявлено: tier, contour
- [info] `Plugins.processing.color_convert` — не объявлено: tier, contour
- [info] `Plugins.processing.color_mask` — не объявлено: tier, contour
- [info] `Plugins.processing.contour_draw` — не объявлено: tier, contour
- [info] `Plugins.processing.contour_finder` — не объявлено: tier, contour
- [info] `Plugins.processing.crop` — не объявлено: tier, contour
- [info] `Plugins.processing.edge_detection` — не объявлено: tier, contour
- [info] `Plugins.processing.flip` — не объявлено: tier, contour
- [info] `Plugins.processing.grayscale` — не объявлено: tier, contour
- [info] `Plugins.processing.hsv_mask` — не объявлено: tier, contour
- [info] `Plugins.processing.image_adjust` — не объявлено: tier, contour
- [info] `Plugins.processing.mask_to_frame` — не объявлено: tier, contour
- [info] `Plugins.processing.morphology` — не объявлено: tier, contour
- [info] `Plugins.processing.negative` — не объявлено: tier, contour
- [info] `Plugins.processing.pixel_to_robot` — не объявлено: tier, contour
- [info] `Plugins.processing.points_render` — не объявлено: tier, contour
- [info] `Plugins.processing.region_split` — не объявлено: tier, contour
- [info] `Plugins.processing.resize` — не объявлено: tier, contour
- [info] `Plugins.processing.robot_scale` — не объявлено: tier, contour
- [info] `Plugins.processing.roi_crop` — не объявлено: tier, contour
- [info] `Plugins.processing.segmentation` — не объявлено: tier, contour
- [info] `Plugins.processing.stitcher` — не объявлено: tier, contour
- [info] `Plugins.processing.strokes_to_points` — не объявлено: tier, contour
- [info] `Plugins.processing.text_vector` — не объявлено: tier, contour
- [info] `Plugins.processing.word_layout` — не объявлено: tier, contour
- [info] `Plugins.render.circle_draw` — не объявлено: tier, contour
- [info] `Plugins.render.overlay_draw` — не объявлено: tier, contour
- [info] `Plugins.render.render_overlay` — не объявлено: tier, contour
- [info] `Plugins.render.renderer_compositor` — не объявлено: tier, contour
- [info] `Plugins.runtime.chain_executor` — не объявлено: tier, contour
- [info] `Plugins.runtime.worker_pool` — не объявлено: tier, contour
- [info] `Plugins.sim.layer_preview` — не объявлено: tier, contour
- [info] `Plugins.sim.mjpeg_sink` — не объявлено: tier, contour
- [info] `Plugins.sim.pult_web` — не объявлено: tier, contour
- [info] `Plugins.sim.robot_host` — не объявлено: tier, contour
- [info] `Plugins.sim.scene_source` — не объявлено: tier, contour
- [info] `Plugins.sinks.modbus_sink` — не объявлено: tier, contour
- [info] `Plugins.sources.camera_service` — не объявлено: tier, contour
- [info] `Plugins.sources.capture` — не объявлено: tier, contour
- [info] `Plugins.sources.frame_counter` — не объявлено: tier, contour
- [info] `Plugins.sources.heartbeat` — не объявлено: tier, contour
- [info] `Plugins.sources.synthetic_frame_source` — не объявлено: tier, contour
- [info] `Plugins.utility.pilot_widgets` — не объявлено: tier, contour
- [info] `Services.auth` — не объявлено: tier, contour
- [info] `Services.camera_device` — не объявлено: tier, contour
- [info] `Services.code_reader` — не объявлено: tier, contour
- [info] `Services.control_panel` — не объявлено: tier, contour
- [info] `Services.dataset_gen` — не объявлено: tier, contour
- [info] `Services.device_hub` — не объявлено: tier, contour
- [info] `Services.documents` — не объявлено: tier, contour
- [info] `Services.hikvision_camera` — не объявлено: tier, contour
- [info] `Services.layer_render` — не объявлено: tier, contour
- [info] `Services.line_sim` — не объявлено: tier, contour
- [info] `Services.ml_inference` — не объявлено: tier, contour
- [info] `Services.ml_train` — не объявлено: tier, contour
- [info] `Services.modbus` — не объявлено: tier, contour
- [info] `Services.otel_export` — не объявлено: tier, contour
- [info] `Services.phone_gateway` — не объявлено: tier, contour
- [info] `Services.robot_comm` — не объявлено: tier, contour
- [info] `Services.sql` — не объявлено: tier, contour
- [info] `Services.vfd_comm` — не объявлено: tier, contour
- [info] `backend_ctl.__root__` — не объявлено: tier, contour
- [info] `multiprocess_framework.modules.actions_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.app_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.base_manager` — не объявлено: contour
- [info] `multiprocess_framework.modules.chain_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.channel_routing_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.command_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.config_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.console_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.data_schema_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.dispatch_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.display_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.error_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.event_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.frontend_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.logger_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.message_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.process_manager_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.process_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.recipe` — не объявлено: contour
- [info] `multiprocess_framework.modules.registers_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.router_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.service_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.shared_resources_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.state_store_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.statistics_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.telemetry_readmodel_module` — не объявлено: contour
- [info] `multiprocess_framework.modules.worker_module` — не объявлено: contour
- [info] `multiprocess_prototype.adapters` — не объявлено: tier, contour
- [info] `multiprocess_prototype.backend` — не объявлено: tier, contour
- [info] `multiprocess_prototype.domain` — не объявлено: tier, contour
- [info] `multiprocess_prototype.frontend` — не объявлено: tier, contour
- [info] `multiprocess_prototype.recipes` — не объявлено: tier, contour
- [info] `multiprocess_prototype.registers` — не объявлено: tier, contour

## registry-drift — 1

юнит графа не найден в modules.yaml либо путь из modules.yaml не существует на диске

- [warn] `Services.camera_device` — юнит не найден в modules.yaml (other)

## unresolved-relative — 1

относительный импорт не разрешается в файл графа (info внутри try/except ImportError)


### `multiprocess_framework.modules.data_schema_module` -> `—` — 1 (info 1)
- `multiprocess_framework/modules/data_schema_module/storage/storage_manager.py:17`

## unresolved-absolute — 1

абсолютный импорт внутри корней не разрешается в файл графа (info — цель тестовый файл)


### `Services.code_reader` -> `—` — 1 (info 1)
- `Services/code_reader/tools/thread_split_probe.py:410`

## recipe-unknown-plugin — 2

plugin_class в рецепте не соответствует ни одному юниту графа


### `—` -> `—` — 2 (warn 2)
- `examples/minimal_app/pipeline.yaml:25`
- `examples/minimal_app/pipeline.yaml:36`
