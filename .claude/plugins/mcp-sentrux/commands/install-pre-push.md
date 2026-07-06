---
description: Install the sentrux pre-push hook (blocks push on rule violations/regression)
---

Установи git pre-push hook, который запускает структурные проверки перед каждым `git push`:

```bash
bash .claude/plugins/core/templates/scripts/install_pre_push_hook.sh
```

Что это даёт:
- `sentrux check` — блокирует push если нарушено правило из `.sentrux/rules.toml`.
- `sentrux gate` — блокирует push при структурной регрессии относительно baseline.

Если sentrux **не установлен** — хук тихо пропустится (warn-skip, exit 0). То есть установка хука безопасна даже без MCP-зависимости.

**Обновить baseline** после намеренного улучшения метрик:

```bash
sentrux gate --save
```

**Аварийный обход** (только в крайних случаях, нежелательно):

```bash
git push --no-verify
```

Файлы:
- `.claude/plugins/core/templates/scripts/install_pre_push_hook.sh` — установщик.
- `.claude/plugins/core/templates/scripts/hooks/pre-push` — сам хук (что копируется в `.git/hooks/`).

После установки хук работает локально (не уезжает в репозиторий). На новой машине надо переустановить.

$ARGUMENTS
