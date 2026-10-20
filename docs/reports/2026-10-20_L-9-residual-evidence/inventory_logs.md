# Опись логов прогонов Task 1.8 (Haiku/Explore, 2026-10-20; записал лид из текста отчёта агента)

Корень: scratchpad/l9_prev (копия scratchpad/l9 сессии 5ea935d9). 301 файл, 57 каталогов.

- Прогоны: before/stand (s2×3, s3×5, s3sd×7), before/stand_pipe (s3×5), after (s2×3, s3×6, s3sd×2, recipe, restart).
- **Сырых логов процессов нет** (messages.log, system.log, robot_exchange.log, каталоги процессов). *.stdout.log, на которые ссылается before/stand_report.md, в копии нет. Есть только JSON, l9dump_*/exit_<proc>_<pid>.txt, pm_<pid>.txt (before).
- В каждом l9dump — 10 процессов (ProcessManager, camera_0, devices, gui, preprocessor, process_flip, process_grayscale, process_negative, region_splitter, stitcher), 1 инкарнация, restart_count 0.
- stop_reply_s до фикса: s3 0.907 / 5.062 / 5.062 / 0.875 / 5.063; stand_pipe s3 5.062 / 5.047 / 0.765 / 0.907 / 5.062; s2 0.922 / 0.812 / 0.922. После: s3 1.015 / 1.0 / 0.813 / 0.968 / 0.875 / 0.781; s2 0.969 / 0.781 / 0.968.
- **Поле verdict = OK и у зависших прогонов** — признак зависания только stop_reply_s и supervision status `crashed`.
- «not reported/lost» и «did not stop in» встречаются только в .md отчётах — по сырым логам не перепроверить.
- Состав ProcessManager.system на стопе (before/stand_report.md:78-96, stand_report_pipe_section.md:16, замер DRAINED): region_splitter|**command** 8 сообщ / 6430 Б, preprocessor|command 7–8 / 4748–5152, camera_0|command 12–13 / 4410–4889, devices|command 8 / 2858. Зависшие: 55/53/56 сообщений, 30859/29598/31608 Б. Тип сообщений — `command` (~550–800 Б каждое); сами команды не названы. Скрипт, давший суммы по отправителям, в копии не найден.

Открыто: разрывы > 1 с по 200 exit-файлам не считались; полные pm_*.txt зависших не читались.
