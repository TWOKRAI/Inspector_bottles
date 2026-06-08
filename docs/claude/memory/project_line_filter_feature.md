---
name: project-line-filter-feature
description: Фильтр виртуальной линии + Join + рендер overlay — состояние и что осталось
metadata:
  node_type: memory
  type: project
  originSessionId: 06a306ad-29b8-45cb-9159-42a31cb4156d
---

Фича «фильтр виртуальной линии (virtual tripwire)» на ветке **`feat/line-filter-virtual`**. План: `plans/2026-06-08_line-filter-virtual.md` (+ внутренний `precious-doodling-starlight.md`).

**Архитектура (6 этапов):** теги sender/data_type → `JoinInspectorManager` (обобщение `InspectorManager`, корреляция N входов по `(seq_id, data_type)`, left-join+TTL+auto-passthrough) → `line_filter` (категория «Фильтр») → `overlay_draw` → PluginRunner → io-debug.

**DONE и проверено вживую (qt-mcp smoke OK, live-edit работает):** Этапы 0–3 + интеграция. 4 коммита:
- `dd70e2d9` фильтр+Join+рендер; `75d6b3bc` рецепт+inspector-поле; `454c4ffb` фикс frame-ключа; `6201c788` фикс live-edit.

**ОСТАЛОСЬ:** Этап 4 (`PluginRunner` — единый seam вызова process/produce, предусловие io-debug) + Этап 5 (generic io-debug панель внизу карточки ноды + «Заморозить», throttle 1Гц, summary O(1)). Отложено: транспортный co-location адаптер (Level 1, dormant), модуляризация inspector_panel, схема DrawCommand, реестр категорий.

**Ключевые решения/грабли (НЕ повторять):**
- `overlay_draw` пишет результат в ключ **`frame`** (перезапись), НЕ `rendered_frame` — framework-путь SHM→дисплей кеется на `frame` (как `contour_draw`). Дисплей-биндинг `.frame`.
- `register_schema()` теперь фолбэчит на `register_class` (`base.py`) — любой плагин с `register_class` получает RegistersManager → приёмник `register_update` → live-edit БЕЗ override `config_class`. Раньше blob_detector/line_filter молча теряли live-edit.
- Распределённый Join обязателен (в одной цепочке line_filter уронил бы кадр). Топология рецепта `line_filter_inspect.yaml`: `camera→detector→{line, draw}`, `line→draw`; кадр в draw из **detector** (рассинхрон 1 хоп), overlay из line; `inspector.mode=join` на процессе draw.
- line_filter: overlay несёт семантику `vlines` (cx,cy,angle,zone_width), overlay_draw разворачивает в отрезки по размеру кадра (фильтр frame-agnostic).
- Запуск: `python multiprocess_prototype/run.py line_filter_inspect` (внутренний run.py! внешний роутер-run.py НЕ пробрасывает рецепт). qt-mcp: `QT_MCP_PROBE=1`, порт 9142.

См. [[feedback_qt_mcp_smoke_verification]], [[feedback_fix_framework_forward]], [[project_pipeline_live_control_stage2]].
