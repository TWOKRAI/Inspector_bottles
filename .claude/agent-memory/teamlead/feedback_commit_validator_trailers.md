---
name: commit-validator-trailers
description: commit-msg hook требует непрерывный блок trailer'ов, каждый — ОДНА физическая строка
metadata:
  type: feedback
---

commit-msg hook (`scripts/validate_commit/validate_commit.py`) парсит trailer'ы как
ПОСЛЕДНИЙ параграф, целиком состоящий из строк вида `^[A-Z][A-Za-z\-]*: (.+)$`.

**Why:** дважды получал отказ «Missing required trailers: Layer, Why», хотя они были в
сообщении. Причина: (1) длинный `Why:` перенёсся на вторую физическую строку — вторая
строка не матчит regex и рвёт trailer-блок; (2) пустая строка перед `Co-Authored-By`
разбивала блок на два параграфа, и в «последнем» оставался только Co-Authored-By.

**How to apply:** при генерации commit-сообщения — каждый trailer (`Why:`/`Layer:`/`Refs:`/
`Risk:`/`Reversible:`/`Tested:`/`Rejected:`/`Co-Authored-By:`) строго ОДНОЙ строкой, все
подряд без пустых строк между ними. Длинный Why не переносить. Em-dash/двоеточия внутри
значения — ок. Тело (буллеты) — отдельным параграфом ВЫШE, отделено пустой строкой.
