---
name: GUI tab ordering preference
description: Settings first, then Recipes, then functional tabs — admin/config → presets → operational
type: feedback
originSessionId: 055294d4-05c9-45fb-bfe0-e822fa1bedc1
---
Tab order: Settings → Recipes → Processes → Services → Plugins → Pipeline → Displays

**Why:** Сначала администрирование и конфиг системы, затем рецепты (пресеты), потом функциональные элементы. Логика: настроил → выбрал рецепт → работаешь с функционалом.

**How to apply:** В TabFactory и MainWindow всегда соблюдать этот порядок. Settings не в конце (как обычно), а первый таб.
