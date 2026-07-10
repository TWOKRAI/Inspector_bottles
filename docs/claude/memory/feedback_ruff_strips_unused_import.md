---
name: feedback-ruff-strips-unused-import
description: "PostToolUse-форматтер (ruff --fix) удаляет только что добавленный импорт, если он ещё не используется в этом же Edit — добавлять импорт и его использование ОДНИМ Edit"
metadata:
  node_type: memory
  type: feedback
---

В этом репо на Edit/Write висит PostToolUse-хук с автоформаттером (ruff --fix). Он
срабатывает ПОСЛЕ каждого Edit. Если добавить `import X` одним Edit, а
использование `X` — следующим Edit, то между ними ruff увидит импорт «неиспользуемым»
и **удалит его** → следующий Edit/тест падает `NameError: X is not defined`.

**Проявление (реально стоило лишнего прогона):** правил `observability_wiring.py` —
первым Edit расширил import-блок (`Callable`, `List`, `RecordForwardChannel`,
`hub_record_to_display`), вторым Edit добавил функции, их использующие. Тесты упали
`NameError: RecordForwardChannel is not defined` — ruff вырезал импорты после
первого Edit.

**Как избегать:**
- Добавлять импорт и его первое использование в ОДНОМ Edit (один old_string→new_string, покрывающий оба места), либо
- Сначала добавить код-использование, потом импорт (или наоборот, но проверить `git diff`/re-Read перед прогоном тестов).
- Системный reminder «PostToolUse hook modified <file> (likely a formatter)» — сигнал перечитать import-блок перед следующим шагом.

Смежное: [[feedback-commit-msg-format]] (тот же слой хуков — commit-msg валидация trailers).
