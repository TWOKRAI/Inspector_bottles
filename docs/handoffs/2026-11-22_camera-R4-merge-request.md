# Заявка на слияние R4 — рецепт β: лимит переподключения, `readiness`, `use_linear: false`, `first_y -440`, `delta_v2` (полоса К)

Автор: лид полосы К, сессия `inspector-bottles-fd`, 2026-11-22. Ветка `feat/camera-r4` (дерево `Inspector_bottles--lane-K-w4`), от `main` `6cb212213` (К4' слит), три коммита рецептов + docs. Резерв до ревью — `feat/camera-r4-pre-review` (не сливать). Файлы β правит только К; блок `pult` и сим-рецепт не тронуты.

## Три коммита в порядке владельца (откат каждого — `git revert`; R4-3 проверен: revert применяется чисто)

| SHA | Что | Golden β (дифф просмотрен) |
|---|---|---|
| `72c33987d` R4-1 | `max_reconnect_attempts: 0` у `robot_main` и `vfd_belt` (дифф Р2); ключ `readiness: {severity: {out_of_spec: check_function}}` в плагине камеры — повышает `stopping` до блокирующего (2.2c, вариант (б)); снятие двух записей `max_reconnect_attempts` в `_EXPECTED_DIFFS`. Часть «камера на `camera_device`» сделана рецептами К4' (4.3) | `readiness`, `max_reconnect_attempts` |
| `2a8607155` R4-2 | `pixel_to_robot.use_linear: false` (гомография F7), `word_layout.first_y: -440.0` (как сим); комментарии в рецепте: без калибровки F7 (`config/calibration/cam0.yaml`) β не выдаёт `pick_xy` и слов не соберёт — ожидаемо; в `_EXPECTED_DIFFS` снят `first_y`, добавлен `use_linear` (сим держит линейный режим) | `first_y`, `use_linear` |
| `a4e60072f` R4-3 | `robot_main.protocol: delta_universal3 -> delta_v2` — ПОСЛЕДНИМ и отдельно; адрес `192.168.1.7:502` прежний; снят `.devices[0].protocol` из `_EXPECTED_DIFFS`, переписано закрепление «β на v1» | `protocol` |

## Проверено

- Каждый коммит атомарен (ревью sonnet, одноразовый worktree): `recipes/tests` + `test_build_characterization` — 263 / 265 / 266 passed, 5 skipped (skipped — `test_demo_recipe.py`, не R4); HEAD после правок ревью: 266 passed; `control_panel/tests` 95 passed; `Plugins/hub/device_hub/tests` в составе прогона (848 passed до правок комментариев).
- Инъекции (предсказание до прогона = факт): `use_linear` -> true: 4 красных; `first_y -200`: 4; нет `max_reconnect_attempts` у `vfd_belt`: 4; нет `readiness`: 3; `protocol delta_universal3`: 5.
- Ревью R4 (sonnet): CHANGES REQUESTED без блокеров -> исправлено: описание `readiness` (повышает `stopping`, а не снимает блокировку; поведенческий тест через реальный `CameraDevicePlugin.readiness` + `apply_policy`), комментарий `use_linear` (`pick_xy` не выдаётся, а не «нули»), ruff, устаревшие упоминания «β на v1».
- `ruff check`/`format --check` по двум тестовым файлам чисты.

## Не проверено (железа нет)

v2 на реальном роботе (T0.3/T4.0; `probe` на прошивке v1 не пройдёт, серво включается при подключении), рабочая зона (`P_ZONE_MAX` по умолчанию 500 мм против 600 в симе), досягаемость 544 мм (слово из 9 букв: `r_max 544.06` на двух крайних ячейках), калибровка F7, полный `readiness_snapshot` на живом сеансе камеры. Всё в `docs/claude/OPEN_QUESTIONS.md`, запись «полоса К · R4».

## Что нужно от других до/после слияния

- **Владелец Пульта:** в β на v2 нет «Домой»/«Серво ВКЛ» — добавить контролы, снять `controls[len=8 vs 10]` из `_EXPECTED_DIFFS` и `test_beta_has_no_home_servo_before_r4`; старая вкладка «Робот» шлёт 16 операций v1, на v2 неизвестных.
- **Р2:** `docs/handoffs/2026-11-22_R2-day2-recon.md` пп. 13 и 20 («β остаётся v1») устарели.
- Живой стенд для R4 не гонялся: рецепт β без робота и камеры не поднимается headless; проверено сборкой драйверов хаба без соединения и тестами.
