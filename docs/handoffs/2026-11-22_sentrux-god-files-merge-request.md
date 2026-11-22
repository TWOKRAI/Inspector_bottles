# Заявка на слияние: Гейт (C-107, C-109) — 2026-11-22

Полоса «Гейт», сессия inspector-bottles-21 → координатору inspector-bottles-30.

- Ветка `test/sentrux-god-files` (worktree `../Inspector_bottles--lane-gate-god`), от `main` `2a8637e9c`; два коммита: тесты (`9dd89e86e`) и docs (дефекты, отчёт, заявка).
- Затронуто только: `Services/hikvision_camera/tests/{test_plugin_on_core,core_rig,test_plugin_on_core_contract,test_plugin_on_core_session}.py`, `multiprocess_prototype/frontend/widgets/tabs/services/control_panel/tests/{test_recipe_1_0,recipe_pult_support,test_recipe_1_0_word_dispatch,test_recipe_1_0_belt_monitors}.py`, `plans/queue/defects.md` (C-107, C-109), отчёт `docs/reports/2026-11-22_sentrux-god-files.md`.
- Проверка на ветке: `sentrux check .` — «All rules pass»; 94 passed по 8 файлам; ревью APPROVED. После слияния повторить `sentrux check .` на `main`.
- Пересечение с полосой Пульт: файлы `test_letter_robot_sim_diff.py` и golden не трогал. Если Пульт правит `test_recipe_1_0*.py`, конфликт разбирать вручную, не мёржить вслепую.
- Слияние — тема `feat(...)` (хук режет `merge(...)`), сообщение из файла; `git merge -F -` не читает stdin.
- Push — не делал и не делаю: только один исполнитель и по слову владельца (около 232 коммитов всех полос; рекомендация координатора — он сам после повторного `sentrux check .` на `main`).
- Открытое — в разделе «Открыто» отчёта.
