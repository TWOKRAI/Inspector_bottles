# Инвентарь разъёмов GUI ↔ дерево процессов (gui-service, Task 1.1)

**Дата:** 2026-09-22. **SHA:** код снят на `597be9e8` (`main`; следующий коммит `8bc4b9c2` — только план).
**Исполнитель:** investigator (read-only). **Инструменты:** qex недоступен (Ollama лежит) — все числа из `rg`, команды приведены.
**Области:** `FE` = `multiprocess_prototype/frontend`, `FM` = `multiprocess_framework/modules/frontend_module`.
Сверка лидом: `command_sender.py:276`, `tab.py:198`, `app.py:846`, `driver.py:2198` — совпали с `sed -n`.

## 0. Сверка чисел плана

| Утверждение плана | Команда | Итог |
|---|---|---|
| `CommandSender` — 29 файлов в FE | `rg -l -e 'CommandSender' multiprocess_prototype/frontend \| wc -l` | **29, подтверждено** (18 не-тестовых, 11 тестовых) |
| `StateProxy/StateStore` — 20 в FE, 2 в FM | `rg -l -e 'StateProxy\|StateStore' <dir> \| wc -l` | FE **20** — подтверждено; FM **3** (1 `.py`, остальное `.md`) — дрейф |

## 1. Таблица разъёмов

Счёт: **файлы** — `rg -l --type py -e '<PAT>' <DIR> | grep -vc /tests/`; **вхождения** —
`rg -c --type py -e '<PAT>' <DIR> | grep -v /tests/ | awk -F: '{s+=$NF} END{print s}'`; **тесты** — `grep -c /tests/`.
Колонка «FE / FM» — «файлы (вхождения, тестовых файлов)».

| # | Разъём | Направление | Трафик | PAT | FE / FM | Аналог в `backend_ctl` |
|---|---|---|---|---|---|---|
| S1 | `CommandSender` (fire-and-forget, PM-relay, `request_*`) | GUI→дерево | команда | `CommandSender\|command_sender` | 30 (125, 24) / 8 (30, 1) | **частично**: `send_command` `driver.py:657`, `system_command` `driver.py:669`; публичен только `request` (`transport.py:144`), отправка без ожидания — приватный `_send_raw` (`:229`); PM-relay (`command_sender.py:110`) нет; `_fence` не штампуется (G1) |
| S2 | State: `GuiStateProxy` + `state.changed` + `ensure/release_subscription` | дерево→GUI | стейт | `GuiStateProxy\|GuiStateBindings\|_gui_state_proxy\|ensure_subscription\|release_subscription\|state\.changed\|state_delta` | 23 (112, 20) / 2 (12, 4) | **частично**: `state_subscribe` `driver.py:2521`, `watch_like_gui` `driver.py:2575` (паттерны `watch.py:40-45` = `process.py:131-148`); `state_unsubscribe` `driver.py:2547` правит только локальный реестр, хотя серверный `state.unsubscribe` по `sub_id` есть (`state_store_manager.py:628`) |
| S3 | Кадры: `FrameShmMiddleware` в `GuiProcess` + SHM | дерево→GUI | кадр | `FrameShmMiddleware\|shm_actual_name\|SharedMemory\|set_frame_callback\|frame_received\|display_frame\(` | 7 (15, 4) / 1 (3, 0) | **нет** (в `driver.py` только докстринги `:728`, `:730`, `:863-869`) |
| S4 | Data-канал: `receive(channel_types=["data"])` → `DataReceiverBridge.dispatch` | дерево→GUI | кадр + legacy `status/fps_update` | `DataReceiverBridge\|data_bridge\|_bridge\.(dispatch\|add_state_listener\|…)\|observability_received` | 9 (45, 8) / 0 | **нет** для data-плоскости |
| S5 | Хвост наблюдаемости: `observability.record` + `ObservabilityTailActivator` | дерево→GUI | лог/ошибки/статистика | `observability\.record\|observability_record\|ObservabilityTailActivator\|observability\.tail` | 6 (19, 5) / 0 | **да**: `observability_tail_all` `driver.py:2198` (та же `observability.tail.subscribe_all`, `tail_activator.py:35`); `log_tail` `:2094`, `observability_tail` `:2136` |
| S6 | Регистры: `register_update` + локальный `RegistersManager` | GUI→дерево | регистр | `register_update\|RegistersManager\|registers_manager` | 16 (101, 20) / 49 (216, 13) | **да** для записи: `set_register` `driver.py:1300`; локальная сборка (`app.py:186`) — см. S9 |
| S7 | Телеметрия: `TelemetryPoller` + `TelemetryViewModel` | дерево→GUI | телеметрия | `TelemetryPoller\|TelemetryViewModel\|introspect\.telemetry\|telemetry_view_model\|telemetry_poller` | 8 (49, 11) / 6 (34, 6) | **да**: `introspect_telemetry` `driver.py:709`, `telemetry_snapshot` `driver.py:1950` |
| S8 | `ui_tap` / `intent_taps` — GUI как **сервер** `ui.tap.*` | GUI→наблюдатель | debug-plane | `intent_tap\|UiEventTap\|register_ui_tap_commands\|ui\.tap\|_ui_command_sender\|_ui_event_tap` | 1 (10, 0) / 5 (32, 1) | **нет, направление обратное**: `ui_tap` `driver.py:2345` — потребитель; у Пульта вне дерева нет адресуемого `gui` с `CommandManager` (`app.py:112`) |
| S9 | Локальная ФС и конфиг: манифест, `recipes/`, `PluginRegistry.discover`, `DisplayRegistry.reload`, `users.yaml`, запись `app.yaml` | вне IPC | конфиг/рецепты | `load_manifest\|resolve_manifest_path\|PluginRegistry\.discover\|RecipeManager\(\|RecipeEngine\(\|_RECIPES_DIR\|recipes_dir\|ManifestStore\|DisplayRegistry\|YamlUserStorage\|INSPECTOR_AUTH_USERS_PATH` | 7 (34, 4) / 0 | **частично**: `capabilities` `driver.py:1261`, `config_reload` `driver.py:1373`; чтения рецепта и записи манифеста через сокет нет |
| S10 | Жизненный цикл: `system_stop_event`, `should_stop`, «закрыл окно — погасил систему» | оба | lifecycle | `system_stop_event\|should_stop\(\|_request_system_shutdown\|shared_resources\|_stop_requested\|_restart_ui` | 5 (24, 2) / 0 | **частично**: `system_command({"cmd":"system.shutdown"})` `driver.py:669`; смерть бэкенда — `connection_lost` `transport.py:309` |
| S11 | Корреляция request/response | оба | команда | см. S1 | см. S1 | **да**: `transport.request` `transport.py:144` |
| S12 | Превью дисплеев: `PreviewWindow` → `register_broadcast_route` | дерево→GUI | кадр | `register_broadcast_route\|router_manager` | 7 (53, 9) / 2 (9, 1) | **нет**; в проде путь мёртвый — `DisplaysTab.create` не передаёт `router_manager` (`tab.py:198`), `preview_window.py:199-204` — no-op |

Производные от S1 (`ProcessManagerProxy|process_manager_proxy|TopologyBridge|topology_bridge`) — FE 29 файлов (126 вхождений, 15 тестовых), FM 4; отдельным разъёмом не считаются.

## 2. Допущения «живу внутри `ProcessModule`» (`файл:строка`)

Проверено циклом `while IFS=: read f l; do sed -n "${l}p" "$f"; done` — `total=45 missing=0`.

**`multiprocess_prototype/frontend/process.py`:** `:27` `GuiProcess(ProcessModule)` · `:46` требует `router_manager`/`memory_manager` · `:54` `add_receive_middleware(FrameShm…)` · `:59` `register_frame_middleware` · `:82` `GuiStateProxy(router=self.router_manager)` · `:92`, `:97`, `:103` handlers `state.changed` / `observability.record` / `process.command.response` · `:131` подписки через in-tree router · `:158` `create_worker("data_receiver")` · `:267` `receive(channel_types=["data"])` · `:339` `self.shared_resources` · `:368` `send_message("ProcessManager", system.shutdown)`.

**`multiprocess_prototype/frontend/app.py`:** `:61` `run_gui(process: GuiProcess)` · `:110` `process._ui_event_tap` · `:112` `register_ui_tap_commands` · `:173` `PluginRegistry.discover` по локальным путям · `:191` `CommandSender(process)` · `:254` рецепт с локальной ФС · `:272` `DisplayRegistry.reload` · `:328` `_gui_state_proxy` · `:340` `process._bridge` · `:389` `exclude=(process.name,)` · `:493` локальный `recipes/` · `:563` локальный `users.yaml` · `:846` `ManifestStore(...).set_pipeline` — GUI пишет `app.yaml` бэкенда · `:859` `data_bridge=process._bridge` · `:903` `process._window` · `:1027` `time.time() - capture_ts` (wall-clock сравним только на одной машине — Ф2) · `:1042` `set_frame_callback` · `:1111` `should_stop()` · `:1125` `_stop_requested`.

**Прочие:** `app_services_factory.py:63` `_RECIPES_DIR` · `bridge_impl.py:84` кадр по `"frame" in msg_dict` (ожидает уже извлечённый `ndarray`) · `headless_process.py:98` `router_manager.receive` · `widgets/displays/preview_window.py:210` `register_broadcast_route` · `widgets/tabs/displays/tab.py:198` мёртвый путь S12.

**Фреймворк:** `frontend_module/bridge/command_sender.py:107-108` маршрутизация «свой / PM / relay» · `:220` `sender=self._process.name` · `:276` `router_manager` для request · `frontend_module/debug/tap_commands.py:130` · `frontend_module/debug/ui_event_tap.py:55` · `frontend_module/application/process_attached_frontend.py:56-57` `_queue_manager`, `_stop_event`.

Контракты для удалённой реализации в Task 1.2: `IProcess` и `IRequestingProcess` (`command_sender.py:35`, `:44`); `GuiStateProxy(process_name, router, delta_sink, server_target, logger)` (`gui_state_proxy.py:42`) — роутер-подобный объект должен уметь `request`, `send_message`, `register_message_handler`.

## 3. Baseline

**fps дисплея за 60 с — НЕ СНЯТ.** Стенд не поднимался: (1) синтетические рецепты `g1_perf_probe`, `dualcam_synth` не объявляют процесс `gui` (`grep -c gui` → 0 и 0), fps был бы 0 по построению; (2) рецепты с `gui` требуют камеру/телефон/Hikvision; (3) `frontend/run.py <recipe>` пишет выбор в отслеживаемый `app.yaml` (`main.py:137-141`). Edge case плана — baseline только по тестам.

| Набор | Команда | passed | skipped | failed |
|---|---|---|---|---|
| `frontend_module/tests` | `cd multiprocess_framework/modules && QT_QPA_PLATFORM=offscreen python -m pytest frontend_module/tests -q --tb=short -p no:cacheprovider` | **574** | 0 | **0** |
| `multiprocess_prototype/frontend` | `QT_QPA_PLATFORM=offscreen python -m pytest multiprocess_prototype/frontend -q --tb=short -p no:cacheprovider` (корень) | **2470** | 0 | **3** |

Три красных детерминированы (изолированно: `3 failed, 22 passed`):
- `widgets/tabs/observability/tests/test_empty_hint_and_lag.py::TestOnARealStore::test_log_tab_reads_a_real_store_written_by_the_real_tap`
- `…::test_error_tab_sees_only_errors_from_the_same_real_store`
- `widgets/tabs/processes/tests/test_system_dashboard.py::TestRefresh::test_refresh_pulls_ring_history_into_series`

**Task 1.4 сравнивается с 2470 / 0 / 3**, не с «всё зелёное».

## 4. Вердикт

**Сокетный аналог есть у 4 из 12 разъёмов (S5, S6, S7, S11), частично — у 4 (S1, S2, S9, S10), нет — у 4 (S3, S4, S8, S12). Блокеров для Ф1 — 2:**
1. **Кадры** (S3/S4) — пути кадров и data-канала в сокете нет → Task 1.3 (мост + SHM по имени).
2. **`_fence` внешнего отправителя** (S1, G1) → Task 1.2.

Не блокеры, но требуют решения: S2 — клиентская отписка по `sub_id` (1.2); S1 — fire-and-forget и PM-relay (1.2); S8 — Пульт теряет debug-plane `ui.tap`; S9 — локальная ФС (для Ф2 блокер); S10 — «закрыл окно — погасил систему» (`process.py:329-330`), решение в 1.4; S12 — мёртвый путь.

## 5. Что не проверено

- **fps дисплея не измерен** — числа для сравнения в 1.4 нет. Нужен рецепт с синтетическим источником, проведённым в `gui` (в репозитории нет), или стенд с вебкамерой.
- **Три красных теста в `multiprocess_prototype/frontend` не диагностированы.** Тесты правились 2026-08-13 / 08-09 / 07-18 — вероятнее, поломка пришла из кода; гипотеза не проверена.
- Грепы ловят комментарии: числа — верхняя граница вхождений, не число вызовов.
- Не воспроизведено, что `send_command` драйвера к не-PM цели эквивалентен PM-relay `CommandSender` при hot-swap рецепта (`command_sender.py:100-105`).
- Не выяснено, шлёт ли кто-то сегодня legacy `status/fps_update/state_changed` (`bridge_impl.py:89`).
- HOL-блокировка `SocketChannel` (remediation 3.1) на живом стенде не проверялась.
- qex не использовался; список S1–S12 собран чтением `process.py`, `app.py`, `app_services_factory.py`, не исчерпывающим поиском.
