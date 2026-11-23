---
name: primary-tree-may-sit-on-another-branch
description: основное дерево может стоять на ветке чужой сессии; `git merge` в нём сливает в неё, а не в main
metadata:
  type: feedback
---

Перед слиянием в `main` смотри `git -C <корень> branch --show-current`. 2026-11-09 основное дерево стояло на `feat/run-state-1.1` соседней сессии: `git merge --ff-only <ветка>` пошёл бы в неё и отказал только потому, что ветки разошлись.

**Why:** ветка основного дерева меняется между вызовами — другая сессия переключила её, пока шла моя работа; `main` при этом не выведена нигде.
**How to apply:** сливай через detached worktree: `git worktree add --detach <каталог> refs/heads/main`, `git merge --ff-only <ветка>` там, затем `git update-ref refs/heads/main <новый> <старый>` (старое значение — защита от гонки), `git worktree remove`. Если `main` выведена в каком-то дереве — слияние в нём, а не update-ref. См. [[feedback_merge_commit_needs_feat_type]].
