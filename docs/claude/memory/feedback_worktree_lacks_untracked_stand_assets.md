---
name: feedback_worktree_lacks_untracked_stand_assets
description: "В новом worktree нет data/models и data/line_sim (untracked): сим молча рисует ровный серый кадр без ленты и дисков (gray frame, missing assets)"
mechanism: [live-stand]
metadata:
  type: feedback
---

Ассеты сима и модели не отслеживаются git, поэтому в свежем worktree их нет, а запуск не падает.

**Замер (run-state 2.10, 2026-11-27).** Стенд показывал серый кадр 1080x1440 без ленты и дисков; сценарии с изделиями
измеряли пустую сцену. После копирования `data/line_sim` из соседнего дерева картинка появилась.

**Как применять:** перед стендом в worktree скопировать `data/models` и `data/line_sim` из дерева, где они есть, и проверить
глазами один кадр.
