---
name: feedback_check_red_on_main_first
description: "Красный тест — сперва проверить на main переключением веток, потом чинить"
metadata:
  node_type: memory
  type: feedback
  originSessionId: eb3dd3af-5a3f-48ed-8b94-aae59f480231
  modified: 2026-07-23T10:21:51.420Z
---

Правило перенесено в `.claude/agents/dev/debugger.md` и skill `systematic-debugging` (2026-10-04).

**Why:** без этой проверки время уходит на поиск несуществующей связи со своим диффом, а настоящая
причина (чужой рефакторинг, не обновивший тесты) остаётся неназванной. Обратная ошибка дороже:
списать своё падение на «предсуществующий шум».


См. также [[feedback_plausible_is_not_verified]], [[feedback_flags_must_not_become_crutches]].
