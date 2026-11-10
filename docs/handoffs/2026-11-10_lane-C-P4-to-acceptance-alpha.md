# Handoff · полоса С · P4 → приёмка α (Task 1.2) · 2026-11-10

Первая строка ответа владельцу в новом чате: «Полоса С · P4 · <имя сессии>».

- **Сделано:** скрипт `scripts/alpha_sim/` одной командой проверяет случаи B «ПЕРЕМИРИЕ», D (смена на «МИР»), C (одинаковые диски), «домой» (`robot_park_all`) и чистый стоп; печатает «вход → наблюдение» и PASS/FAIL по диску, код выхода 0/1/2/3. Отчёт: `docs/reports/2026-11-10_word-layout_P4.md`; запуск и коды — `scripts/alpha_sim/README.md`.
- **Ветка:** `feat/word-layout-p4` (rebase на `main` `be93fd2ae`), worktree `.claude/worktrees/wl-p4`, `wl-p4-tester`, `wl-p4-inj` — снять после слияния. Слияние через ветку и файл сообщения, тип `feat`; push не выполнялся.
- **Для Task 1.2:** три полных стенд-прогона дали одно и то же: B/D/C — строки диска 12/5/4 и задания 9/3/3 совпали с литералами, красные по геометрии (`py` −340,9…−343,2 против окна §2.8; `ARGS[3]` 62117…62132; `r`/`ARGS[9]` где сеть ошибается > 5°). Конвенция угла сим ↔ сеть: инверсии нет. «М» сеть местами не выдаёт. Скрипт вердикт α не выносит.
- **Как повторить:** сим `BACKEND_CTL=1 BACKEND_CTL_PORT=8766 PYTHONUTF8=1 python apps/line_sim/run.py`; прототип свежий `BACKEND_CTL=1 PYTHONUTF8=1 INSPECTOR_LOG_DIR=<tree>/data/logs/prototype INSPECTOR_MANIFEST=<копия app.yaml> python multiprocess_prototype/run.py letter_robot_sim --headless`; затем `PYTHONUTF8=1 PYTHONPATH=<tree> python -m scripts.alpha_sim.run_alpha --tree <tree> --dump <файл>`. Порты 8765/8766/8091/8092/5021 свободны.
- **Решения владельца:** списком в отчёте (окна §2.8, `r`/`ARGS[9]` FAIL или INFO, потеря «М», push/слияние).
- **agentId:** developer a138727d62937f83d (~380k), reviewer стадии 5 af87827d0a6cf8f7c, docs-writer a158f8f767bd7ed86, haiku-инвентарь логов a64fb7ee8e4e5196f.
