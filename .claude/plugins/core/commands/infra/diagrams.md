---
description: Regenerate diagrams from code (pyreverse + pydeps, optionally mermaid)
---

Регенерация диаграмм из исходного кода.

## Что делать

1. **Если есть `make diagrams` цель** — используй её:
   ```bash
   make diagrams
   ```

2. **Иначе — прямой вызов инструментов:**
   ```bash
   # UML классов
   mkdir -p docs/diagrams/classes
   uv run pyreverse -o png -d docs/diagrams/classes src/<package>

   # Граф зависимостей модулей
   mkdir -p docs/diagrams/deps
   uv run pydeps src/<package> --max-bacon=3 -o docs/diagrams/deps/deps.svg --noshow
   ```

3. **Если pyreverse / pydeps не установлены** — предложи:
   ```bash
   uv add --group diagrams pylint pydeps      # или соответствующая dep-group из pyproject.toml
   ```

4. После генерации — кратко покажи что обновилось (список файлов + размер).

5. Если в проекте есть ручная диаграмма (`docs/diagrams/architecture.mmd` или `.puml`) — напомни обновить если архитектура менялась.

## Формат ответа

Кратко: что сгенерировано, какие файлы обновились, нужно ли обновить ручные диаграммы.
