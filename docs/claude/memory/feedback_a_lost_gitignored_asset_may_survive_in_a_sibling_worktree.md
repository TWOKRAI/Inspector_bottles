---
name: feedback-a-lost-gitignored-asset-may-survive-in-a-sibling-worktree
description: "«Потерянный» gitignored-ассет (data/) может жить в соседнем worktree — искать по sha в .claude/worktrees/*/data до реконструкции; a lost gitignored asset may survive in a sibling worktree"
module: [services/line_sim]
mechanism: [git, spec-scope]
metadata:
  node_type: memory
  type: feedback
  modified: 2026-10-13
---

Ловушка: посылка плана «ассет потерян» (gitignored `data/` перезаписан) ведёт к реконструкции «по описанию» —
и реконструкция правдоподобна, но не та.

Замер (line-sim 6.5, 2026-10-13): `data/line_sim/belt_photo_full.png` с бортами, выровненными 2026-09-30, в основном
дереве перезаписан стендом из невыровненной фикстуры. Лид спроектировал сборку с `np.round(np.median(...))`. Ревьюер
нашёл оригинал в `.claude/worktrees/merge-main/data/line_sim/` (sha256 `4444f158…` совпал с записанным в
`plans/layer-render/phase-1.md:232`): оригинал собран усечением `astype(uint8)` — с `np.round` 7774 пикселя мимо на 1.
С усечением сборка дала фото и RGB тайла пиксель в пиксель (0 отличий).

**Why:** `data/` не в git, у каждого worktree своя копия; удаление в основном дереве не трогает соседей, а git их не видит.

**How to apply:** прежде чем принять «ассет потерян» — `sha256sum .claude/worktrees/*/data/<путь>` и `git grep` sha в
`plans/`. Нашлась копия — сохранить её в основное дерево (`data/<имя>_original_<дата>/`) до чистки того worktree и
закрепить реконструкцию пиксельным равенством с ней. Связано: [[feedback_a_plans_premise_expires]].
