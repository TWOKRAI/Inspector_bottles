---
name: unused-paths-are-contracts
description: "Конструктор универсален: «путь сейчас не используется» ≠ «не нужен» — публичные API/формы конвертов без живых вызывающих квалифицировать в ревью как контракты (чинить или отклонять громко), не отмахиваться «мёртвый путь»"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 0930f3cb-ce11-4c8b-94d5-186f9a19db5e
---

Правило перенесено в `.claude/agents/dev/reviewer.md` (чек-лист) и `.claude/skills/project-rules/SKILL.md` §5 (2026-10-04).

**Why:** по этим контрактам (ISQLManager.execute_command, формы конвертов, Message.set_command) будет собрано следующее приложение из «рыбы»; сломанный неиспользуемый путь = баг, найденный через полгода в чужом приложении.
