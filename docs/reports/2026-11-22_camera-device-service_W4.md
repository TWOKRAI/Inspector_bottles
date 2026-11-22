# camera-device-service · W4 (К4') — отчёт лида полосы К, 2026-11-22

Сессия `inspector-bottles-fd`, ветка `feat/camera-w4`, К4' = `a4e1b325d` на `main` `d221d9a9c`; заявка — `docs/handoffs/2026-11-22_camera-W4-merge-request.md`.

- **Сделано:** 4.2a–4.4 одним коммитом: плагин `hikvision` на `camera_device`, цвет BGR и дебайер в ядре, вендорский ресайз, рецепты (4 + `hikvision_dual`), golden β, вкладка GUI, ADR-CAM-006 и ADR-HIK-001. Конвейер: стадия 0 (2 раунда) → слепой tester (65 тестов) → developer → инъекции → Opus-ревью (раунд 2 APPROVED).
- **Числа:** `hikvision_camera/tests` 314 passed; `camera_device/tests` 462 passed; `recipes/tests` 257 passed; вкладка 12 passed; golden 4 passed; `validate.py` чисто. Инъекции: 12 из 14 предсказаний совпали, расхождения M5/M9 безвредны, M14 (`cv2.error`) закрыт двумя hazard-тестами.
- **Отклонения процесса:** стадия 0 закрыта правками N1–N4 без раунда 3 (лимит 2 итерации); пилот «стадия 0 в тень» не применялся (Level Senior, не Senior+); 4.2c вынесена из 4.2a (лимит FILES ≤ 6), ADR писал tech-writer.
- **M2 ждёт владельца:** `mono8` -> BGR (`GRAY2BGR`) против записи 11-20 «gray для `mono8`»; кода под gray нет.
- **День №1:** чек-лист и сухой прогон сверены с main (`docs/reports/2026-11-22_day1-checklist-vs-main.md`); не переписывались; день №1 идёт на старом пути в worktree `../Inspector_bottles--day1`.
- **R4 не начат:** по слову координатора — после слияния К4' (три коммита: β `max_reconnect_attempts: 0` + голая камера; `use_linear: false` + `first_y: -440`; драйвер `delta_v2` последним).
- **C-106** (голые `logging.getLogger` в 4 файлах) в К4' не взят: мост сеанса `camera_device.session` держит stdlib-логгер, правка меняет сам мост и тесты ядра; координатор принял, фаза — после R4 только при свободном К.

| Роль | agentId |
|---|---|
| стадия 0, раунд 2 (reviewer sonnet) | `a5fe99daa6a573519` |
| слепой tester 4.2a | `a5a54120bdf1237a3` |
| developer 4.2a | `a47a6b0a1b5fb1972` |
| инъекции 4.2a (haiku) | `a677a361afd870661` |
| hazard-тесты 4.2a | `afde56f9d0f2c2121` |
| developer 4.2b | `adad5a5d9de372d85` |
| docs-writer 4.2c / tech-writer ADR | `a8fcc2bc490393b51` / `ad2721ac46d826dfd` |
| developer 4.3 | `adca9a9f9b3279eec` |
| developer 4.4 | `ad3550b794c9e2ec9` |
| Opus-ревью ветки К4' | `a1319dc72a49e87f0` |
| тест-раннеры радиуса | `a388b258cf1cf54d5`, `a636aeb4dfbc4846b` |
| сверка чек-листа дня №1 | `a49c8679515f183d2` |

## Открыто

- Железа нет: порядок каналов реального прибора (BayerRG8 по дампу 0.5, проба cv2 на синтетике; при `RGB8` вывод меняется), `GainAuto` (потеряна запись `GainAuto=Off`), `TriggerMode` прибора, размер пакета (`packet_managed=false`, «оптимум» недостижим без ложного `param_errors`), перезахват close/open при правке `gain`/`exposure_time` — всё в `docs/claude/OPEN_QUESTIONS.md`, запись «полоса К · камера W4, К4'» (10 пунктов).
- Живой стенд не гонялся, вкладка GUI вживую не запускалась (qt-mcp не подключился).
- `no_god_files` на новом `test_plugin_on_core.py` (fan-out 18); C-107 и C-108 (красный снимок полей `robot_io`) на `main` не наши; 8 красных probe-тестов `lifecycle_guards` — и на `main`.
- Сим-рецепт `letter_robot_sim.yaml` (чужой) оставил `color_convert`: расхождение с β записано в `_EXPECTED_DIFFS`, судьбу решает владелец сима.
