---
name: No SHM hacks in plugins
description: Plugins must NOT read SHM directly — use framework middleware and managers only
type: feedback
originSessionId: 7bde3598-7b2e-4498-8c8b-09d76cc85d95
---
Плагины — изолированные модули. Они НЕ должны читать из разделяемой памяти напрямую (mm.read_images). Только через RouterManager middleware в процессе.

**Why:** Пользователь пресёк попытку добавить костыль (msg["_frame"]) в каждый плагин. Правильный подход — использовать фреймворк по максимуму. Если чего-то не хватает — допиливать фреймворк, а не обходить его.

**How to apply:** При рефакторинге data pipeline (Phase 5) — вся IPC/SHM логика в GenericProcess (Data Worker + Chain Worker). Плагины получают чистые `process(items) -> items`. Если нужна новая возможность — добавлять в фреймворк (InspectorManager, middleware), не в плагины.
