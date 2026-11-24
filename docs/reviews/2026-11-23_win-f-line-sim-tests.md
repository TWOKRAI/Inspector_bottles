# Win-F: три устаревших теста стенда line_sim/letters

STATUS: DONE_WITH_CONCERNS (без коммита; патч: scratchpad/patches/wf-f1.patch)

Preflight: `import multiprocess_framework` -> `D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles--wf-c\multiprocess_framework\__init__.py`.

## Что сделано
1. `apps/line_sim/tests/test_fit_letter_robot.py` — `_recipe_pixel_to_robot_config` читает `_SIM_RECIPE_PATH`; докстринг теста
   уточнён (сим-рецепт `use_linear: true` + ROI β-рецепта против `object_robot_xy` сима).
2. `apps/line_sim/tests/test_f1_task11_acceptance.py` — тест разделён: `test_robot_client_connects` (`RobotClient.connect() is True`)
   и `test_robot_client_reads_growing_encoder` (сырое чтение `TLM_ENC` из `protocol_v2.REG`, два слова `lo | hi << 16`, через
   `ModbusDevice`). Правка сделана лидом (отмечено в докстринге).
3. `scripts/tests/test_letters_baseline.py` — второй skip-guard: пропуск, если в `letters_ink` нет подкаталога нужной буквы;
   причина называет найденные буквы и команду `build_stand_assets.py --force`.

## Красные до правки
- fit_letter_robot: `1 failed, 2 passed` (assert `use_linear is True`).
- f1_task11: `1 failed, 5 passed in 49.95s` (`test_robot_client_reads_growing_encoder`).
- letters_baseline: копия HEAD-версии с `LETTERS_BASELINE_DATA_ROOT=<основное дерево>/data` -> `1 failed` (причина по `--tb=line` не выведена, см. «открыто»).

## Зелёные после
- `test_fit_letter_robot.py`: `3 passed`.
- `test_f1_task11_acceptance.py`: `7 passed in 46.18s` (было 6 тестов, +1 за разделение).
- `test_letters_baseline.py` (данные основного дерева): `10 passed, 1 skipped`; SKIPPED: `в ...\data\line_sim\letters_ink нет букв ['П'] (есть: ['А', 'К', 'Р', 'Х']): ассеты сима устарели; пересоберите: python Services/line_sim/tools/build_stand_assets.py --force`.
- Остальные файлы каталогов (по одному): task12_acceptance 4 passed; task12_wiring 3 passed; task15_16 7 passed; f2_task22_live 5 skipped;
  f2_task23_live 1 skipped; state_proxy_live 3 passed; day1_capture_check 7 passed; validate_services_decisions 9 passed. Все exit=0.
- `ruff check -q` на трёх файлах: exit 0.

## Что истолковал, а не выполнил буквально
- Энкодер читаю `ModbusDevice` + `REG["TLM_ENC"]`: в `RobotClientV2` метода чтения энкодера нет (проверено по списку методов `client_v2.py`),
  поэтому «клиент v2» не нужен, взято сырое чтение (второй вариант брифа).
- Критерий «буква есть» — наличие подкаталога `letters_ink/<буква>`; что генератор берёт имена классов именно из подкаталогов, прямо
  не проверял (по выводу ошибки «4 классов» и 4 подкаталогам — совпадает).
- ROI в тесте 1 по-прежнему из β-рецепта (бриф менял только калибровку); в докстринге это сказано.

## Открыто / ненадёжно
- Красное п.3 воспроизведено, но причина `ValueError` в моём прогоне не выведена (`--tb=line`, хвост обрезан); опираюсь на диагноз investigator.
- Skip-guard — прокси по каталогам; если каталог букв есть, но пуст, тест упадёт в генераторе, а не пропустится.
- Приёмка «основное дерево при 4 буквах SKIPPED» проверена запуском из worktree с `LETTERS_BASELINE_DATA_ROOT`, не из основного дерева.
- Тест роста энкодера не проверен инъекцией (стоп ленты); контрфакт — прежнее красное: чтение 0x1112 даёт ноль и тест падал.
- Живые тесты f2_task22/23 пропущены сами (5+1 skipped) — регрессий по ним не видно.

memory hits: python scripts/memory/search.py line_sim test stale recipe encoder -> feedback_a_decision_orphans_what_encoded_the_previous_one.md (по смыслу — п.1, тест кодировал прежнее решение R4-2) | остальное нерелевантно
