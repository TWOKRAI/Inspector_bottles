# Handoff — Ф5.19 + Ф5.20b влиты в main (2026-07-10, вечер)

**Читать первым для продолжения Ф5.** Предыдущий handoff: `2026-07-10_f5-gui-observability.md` (был про подхват 5.19/5.20b — теперь закрыты).

## Что влито в main (merge a1338f37, `--no-ff`)

Ветка `feat/observability-gui-tabs` (14 коммитов) в main. Гейт: framework 822 + prototype 2173 + затронутые 193 passed; ruff/pyright 0; sentrux 9/9 (0 reverse-import, quality 7078). Live-провалидировано через `backend_ctl` (region_pipeline).

### Ф5.20b — hub→GUI live-хвост ✅
- **`RecordForwardChannel`** (`channel_routing_module/observability/record_forward_channel.py`) — IChannel-форвардер записей на GUI-подписчика адресным router-push `command="observability.record"`, `queue_type="system"`. `write()` — одна error-запись у tap'а; `push_batch()` — пачка log/stats из drain.
- **`record_display.py`** — `hub_record_to_display` / `log_record_to_display`: единый display-вид `{kind,module,ts,severity,message,extra}` из hub-записи И LogRecord-dict; форма == `store.list_records` без id. **extra под ключом `"context"`** (паритет со стором — исправлено ревью).
- **`wire_observability_forward`** + `drain_process_observability(+forwarder)` (`process_module/managers/observability_wiring.py`): форвардер (log/stats) + error-tap'ы на logger+error (min ERROR, write-through) — симметрия store-tap 5.20a.
- **`ProcessModule.subscribe/unsubscribe_observability_tail`** + команды `observability.tail.subscribe/unsubscribe` (мёртв без подписчика, как log_tail).
- **GUI:** `DataReceiverBridge.observability_received` (ОТДЕЛЬНЫЙ сигнал, НЕ state_updated), `GuiProcess.register_message_handler("observability.record")`, `ObservabilityTailActivator` (`widgets/tabs/observability/tail_activator.py`) подписывает каждый процесс по `processes.*` + **переподписывает новую инкарнацию по `supervisor.event=recovered`** (закрытый долг рестарта).

### Ф5.19 — 3 вкладки на одном виджете ✅
- `widgets/tabs/observability/`: `RecordSource` Protocol + `open_default_source` (общий `observability.db` на чтение), `RecordHistoryPresenter` (Qt-free), `RecordHistoryPanel` (переиспользует `BaseAdminPanel`: фильтр уровня, колонка Источник, Копировать, Очистить, детальный диалог, **инкрементальный live-append**), `ObservabilityTabs` (3 инстанса log/error/stats).
- Вкладка **«Наблюдаемость»** в TAB_ORDER + register_all_tabs + `RuntimeDeps.data_bridge` + `predefined_roles` (admin/operator/viewer).
- **Fake-дельты убраны**: 4 GUI-метрики → `data_type="gui_local_metric"` (в топологию/стор/observability-активатор не течёт).

### Live-валидация (region_pipeline через BACKEND_CTL)
subscribe camera_0 → `start_capture` (ERROR открытия камеры) → `events()` показал `command="observability.record"` с `{kind:error,severity:error,message:"...не удалось открыть камеру 0"}` ОТДЕЛЬНЫМ каналом от log.record. **Урок: `health.report` логирует на WARNING (не ERROR); настоящий ERROR даёт `start_capture`.**

## Код-ревью (4 угла против кода) — исправлено + долги
- **Исправлено:** F1 паритет формы `extra` live↔history; F3+F7 инкрементальный live-append + честная пагинация (коммит 67af7fb2).
- **Долги → задача 5.21** (в plan.md): (a) вынести `BaseAdminPanel` из `settings/administration/_base_panel.py` (приватный, auth-домен) в общий `widgets/base/` — сейчас cross-domain приватный импорт; (b) единый нормализатор `hub_record_to_display`↔`_row_from_record`; (c) имя процесса-источника в record-модели (панель показывает `module`, не процесс); (d) QoS live-хвоста (`system`-очередь + активатор always-on → при error-storm теснит heartbeat, пересекается с Ф7 G.4); (e) мелочи (close стора на teardown, `_format_ts`↔`format_dt`, счётчик truncation >500). F4: переподписка покрыта только `recovered` — ручной restart/hot-swap без события не переподпишет.

## Побочно
backend-ctl прописан в 5 dev-агентов (developer/teamlead/tester/reviewer/debugger, оба зеркала `.claude/agents/dev` + `.claude/plugins/dev/agents`) — live-верификация бэкенда.

## NEXT (свободно)
- **5.3** recipe-orchestrator carve (M+M, крупная, отдельная сессия) → разблокирует **5.11–5.13** app_module skeleton (+3 вопроса скоупа в plan.md).
- **5.8** RuntimeDeps двухслойный контракт (M), **5.18** depth-reduction ≥0.60 (M), **5.6a** diff-отчёт форм → GATE G2, **5.21** добор наблюдаемости, **5.10/5.14опц**.
- main НЕ запушен в origin (220+ коммитов, push owner-gated).
- Грязное дерево (`.claude/agent-memory/*`, `uv.lock`, `health/.claude/`) — не относится к Ф5, грязно с начала сессии.

## Live-инфра (переиспользуемо)
`scratchpad/boot_backend.py` (BackendHarness, port=8765, INSPECTOR_LOG_DIR→obs_logs, BACKEND_CTL=1, spawn на macOS требует `if __name__=="__main__": freeze_support()`); STOP-файл гасит. Камеры физической нет → ошибка «не удалось открыть камеру 0» — полезный live error-кейс.
