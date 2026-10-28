---
name: feedback-gui-stand-in-worktree-needs-user-and-recipe-by-name
description: "GUI-стенд вкладки сервисов из worktree: гостю вкладки скрыты, а страница устройства пуста, пока рецепт не лежит в multiprocess_prototype/recipes/ — нужен одноразовый dev-пользователь и копия рецепта; gui_stand.py T5.3e.4 делает оба шага"
module: [prototype/frontend]
mechanism: [live-stand, qt]
metadata:
  node_type: memory
  type: feedback
---

**Ловушка.** Боевой подъём (`frontend/run.py`, `INSPECTOR_GUI_UNATTENDED=1`, `QT_MCP_PROBE=1`) с чистым `INSPECTOR_DATA_DIR` и
рецептом-копией вне дерева даёт окно, в котором нечего кликать: порты 5021/8765/9142 слушают за 10–26 с, `qt_find_widget`
не находит кнопок.

**Замер (T5.3e.4, 2026-10-28, три подъёма подряд).**
1. Вход: GUI без пользователя. Выход: роль «гость», `QTabBar` 0×0, модалку входа закрывает сторож UNATTENDED. Лечится
   одноразовым `dev` в своём `users.yaml` (`MULTIPROCESS_AUTH_USERS_PATH`, `python -m Services.auth.bootstrap` с
   `MULTIPROCESS_DEV_PASSWORD`) и `INSPECTOR_AUTH_DEV_AUTO_LOGIN=1` + `INSPECTOR_DEV_USERNAME/PASSWORD`; настоящий
   `~/.inspector_bottles/auth` не трогать.
2. Вход: Services → «Робот Delta» при рецепте `stand_delta_v2` вне `multiprocess_prototype/recipes/`. Выход: список
   устройств пуст, «Активируйте рецепт, чтобы управлять устройством». GUI восстанавливает активный рецепт по имени
   (`_manifest.pipeline.stem`) из этого каталога: копию положить туда на время прогона (untracked) и убрать после.
3. Клики по `QTreeWidget` / `QListWidget` — по дочернему `qt_scrollarea_viewport` (ref находится `qt_find_widget root_ref=`),
   не по самому виджету; координата — внутри viewport, строка ≈ 36 px.

**Триггер:** GUI-стенд вкладки `Services` (или любой вкладки за ролью) из worktree; `gui_stand.py start` — готовый образец
(`plans/robot-protocol-v2/tasks/T5.3e.4.stand/`).

Связано: [[project-gui-stand-production-entry-only]], [[feedback-backend-ctl-for-agents]], [[reference-qt-mcp-launch]].
