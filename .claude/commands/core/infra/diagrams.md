---
description: Regenerate diagrams from code (pyreverse + pydeps, optionally mermaid)
---

Regenerate diagrams from the source code.

## What to do

1. **If there's a `make diagrams` target** — use it:
   ```bash
   make diagrams
   ```

2. **Otherwise — call the tools directly:**
   ```bash
   # Class UML
   mkdir -p docs/diagrams/classes
   uv run pyreverse -o png -d docs/diagrams/classes src/<package>

   # Module dependency graph
   mkdir -p docs/diagrams/deps
   uv run pydeps src/<package> --max-bacon=3 -o docs/diagrams/deps/deps.svg --noshow
   ```

3. **If pyreverse / pydeps aren't installed** — suggest:
   ```bash
   uv add --group diagrams pylint pydeps      # or the matching dep-group from pyproject.toml
   ```

4. After generation — briefly show what got updated (file list + size).

5. If the project has a manual diagram (`docs/diagrams/architecture.mmd` or `.puml`) — remind to update it if the architecture changed.

## Response format

Briefly: what was generated, which files were updated, whether the manual diagrams need updating.
