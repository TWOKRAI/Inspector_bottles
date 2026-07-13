---
name: new-framework-module-registration
description: Новый модуль в multiprocess_framework/modules/ нужно зарегистрировать в ТРЁХ местах, иначе validate.py падает
metadata:
  type: project
---

Новый framework-модуль с локальным DECISIONS.md (ADR-XXX-*) требует регистрации в **трёх** местах, иначе `scripts/validate.py` падает на ADR-дрифте:

1. `scripts/validate.py` → список `MODULES` (иначе не проверяется import/README/STATUS; это curated-подмножество, не все модули там есть — recipe, например, не был).
2. `scripts/sync/_adr_layers.py` → `MODULE_LAYERS` (кортеж `(имя, слой)`) — иначе `validate_all` кидает «Модуль X не зарегистрирован». Если у модуля нет локального ADR — в `MODULES_WITHOUT_LOCAL_ADR`.
3. После правок — прогнать `python -m scripts.sync` (пересобирает сводные разделы `multiprocess_framework/DECISIONS.md`, коды в `docs/ADR_REGISTRY.md`); CI ловит дрифт через validate.py.

**Why:** ADR-код (напр. «APP») автодетектится из заголовков DECISIONS.md; sync проверяет уникальность кода и что модуль зарегистрирован. Пропуск любого шага → красный validate.
**How to apply:** при создании любого нового публичного модуля framework делай все три шага сразу, до финального гейта. Проверено на app_module (Ф5.11, 26-й модуль).
