---
name: feedback_sentrux_gate_narrowed
description: "Владелец сузил sentrux pre-push gate: жёсткий блок ТОЛЬКО на циклы↑/god↑; мягкие (падение aggregate quality, complex-fn/coupling/depth) → warning, не блок. Источник хука — scripts/hooks/pre-push (git-tracked)."
metadata:
  type: feedback
---

Владелец (2026-07-15) сузил sentrux structural pre-push gate — раньше он был all-or-nothing
(любая регрессия любой под-метрики → блок push).

**Теперь (после доп-сужения 2026-07-20):**
- **Жёсткий блок push:** рост циклов · рост god-файлов (ТОЛЬКО структурные guardrail'ы).
- **Мягкие метрики** (падение aggregate quality · complex-fn / coupling / depth / hotspot) →
  **WARNING, НЕ блок**; фиксируются осознанно через `sentrux gate --save`.
- **Fail-closed:** если summary-метрики не распознаны (дрейф формата sentrux) → блок консервативно.

**Why:** (1) 2026-07-15 гейт заблокировал push, где aggregate **quality ВЫРОС** (7089→7099),
из-за +1 complex-function. (2) 2026-07-20 гейт заблокировал merge Phase E backend_ctl:
quality 7007→6998 (−9) от ДВУХ новых легитимных модулей (audit.py + command_validate.py),
без роста циклов/god. Та же ложная тренировка — владелец снял и падение quality с жёсткого
блока. Guardrail остаётся на реальные структурные регрессии (циклы/god), не на непрозрачный
агрегат. Связано с [[feedback_sentrux_depth_opaque]] (метрики sentrux непрозрачны).

**How to apply:**
- Источник хука — `scripts/hooks/pre-push` (git-tracked; ставится `scripts/install_pre_push_hook.sh`).
  Правку делать в ОБОИХ: `scripts/hooks/pre-push` (источник) И `.git/hooks/pre-push` (установленный).
  НЕ возвращать к all-or-nothing `if ! sentrux gate` и НЕ возвращать quality↓ в жёсткий блок.
- Если push «заблокирован» на мягкой метрике (в т.ч. падение quality) — теперь это warning,
  push пройдёт; зафиксировать осознанно `sentrux gate --save` (обновит `.sentrux/baseline.json`).
- Жёсткий блок остаётся ТОЛЬКО на цикл/god-файл — это правильно.
- **auto-mode:** правка `.git/hooks/pre-push`, `git push --no-verify` И `sentrux gate --save` —
  ВСЕ блокируются классификатором (обход/изменение quality-гейта → нужно явное разрешение владельца).
