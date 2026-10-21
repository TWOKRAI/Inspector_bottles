# Передача координатора — 2026-10-21 ~10:00

Уходит: inspector-bottles-7f. Новый координатор: навык `coordinator`, первым делом — своё имя в строку `coordinator:` в
`D:\PROJECT_INNOTECH\Inspector_vision\machine.lock` (остальные строки не трогать) и одно сообщение каждой полосе:
«координатор теперь <имя>».

## Полосы (все три на связи, ListAgents)

| Сессия | Полоса | Задача | Состояние ~10:00 |
|---|---|---|---|
| inspector-bottles-a9 | Р2 (робот v2, device_hub) | T5.3g — окна W1/W4/WW гонки connect ↔ request_stop | C-11 в main `a178e0b64`; проба воспроизвела W1/W4/WW (10/10 по прогнозу); слепой тестер написан (9 тестов), developer правит; ветка `feat/robot-v2-t53g` |
| inspector-bottles-48 | Ф (фреймворк, L-9) | Task 1.9a — KeyedExecutor + развилка в CommandManager | реализация `8e7cf6a7a` (R 15/15, H 8/8, радиус medium зелёный); прогнозы инъекций закоммичены; в окне до ~10:06 |
| inspector-bottles-66 | Д (дефекты) | C-13 → C-16/C-17 | C-13 (`fix/c13-validate` 9e4623b95) готов, ждёт «да» владельца; C-16 (`fix/c16-collector` e5819bd88) реализован, ревью ветки Opus идёт, нужно окно |
| claude-seed-b7 | — | не проект | простаивает; владелец может закрыть |

## Очередь окон (machine.lock)

1. Ф — heavy до ~10:06: robot_comm → база → инъекции A/B → framework suite → validate → backend/tests.
2. Р2 — heavy (timed medium device_hub) ~25 мин по «готов» (уже прислала): тестер + прогон правки developer.
3. Д — heavy ~20 мин: framework suite + backend/tests + validate на C-16.
Окно на машине одно (gate). Timed device_hub рядом с framework suite не пускать — тайминги.

## Границы, выданные сегодня

- Д получила из границы Ф (Ф подтвердила, что 1.9a–1.11 их не трогают): `process_module/plugins/port.py`,
  `process_manager_module/topology/blueprint.py`, раздел ADR-PMM-017 в `process_manager_module/DECISIONS.md`,
  `process_module/commands/builtin_commands.py` — только интроспекция портов (~:1003–1007; карточку capabilities :866–870 НЕ трогать —
  туда позже executor/key_from Ф, Ф спросит координатора), `process_module/tests/test_blueprint_wire_collector.py`;
  плюс `Plugins/render/overlay_draw/**` и рецепты `hikvision_letter_robot`, `letter_angle_inspect`, `letter_robot_sim`,
  `dataset_circle_capture`, `line_filter_inspect`.
- Ф в T1.11 может тронуть схему конфига процесса в `topology/` (не blueprint.py); если blueprint.py — спросит координатора.
- 1.9a меняет API: `handle_command(self, message, *, reply=None)`, `register_command(..., executor=None, key_from=None, targets=None)`,
  новые отказы регистрации. Р2 проверила device_hub — не задета. SPI хаба (Р2, позже) учтёт новый API.

## Порядок слияний и ловушки

- Сливают полосы сами, после «да» владельца; координатор только записывает итог в ORDER.md/defects.md.
- Кто вливается позже — rebase на новый main и прогон уже на нём (C-13 → validate 0 FAIL; 1.9a рядом с builtin_commands Д).
- Ожидаемые красные на main сейчас: validate 3 FAIL (C-13, до слияния); backend/tests 3 (C-16: `test_build_characterization[hikvision_letter_robot]`,
  `topology/tests/test_join_collector_from_wires.py` × 2); C-19 — только в общем pytest-процессе.

## Реестр и правила, изменённые сегодня (main)

- `65d526319` — ревью на Sonnet по умолчанию; Opus только ревью ветки перед слиянием, стадия 0 Senior+, живые дефекты (решение владельца).
- `5f48c1672`, `83f95dbac` — C-16: регресс от `7e1640c97` (порт overlay стал optional); владелец: «универсально, без костылей» →
  поле `Port.join: bool | None` (None = not optional), metadata.inspector deprecated с предупреждением; делает Д.
- `9c8e4e6a4` — C-17 (громкий отказ при потерянном join) — вместе с C-16 у Д.
- `aad763838` — C-11 закрыт; ORDER строка 2 → T5.3g.
- `e7a215a05` — C-18: `modbus_demo` и `robot_demo` не собираются (провода); полоса не назначена.
- `f99a24b82` — C-19: `test_build_characterization[phone_sketch]` зависит от порядка файлов в pytest-процессе; полоса не назначена.

## Ждут ответа владельца

1. «да» на слияние C-13 (вкладка Д).
2. Кто берёт C-18 (предложение: robot_demo — Р2 после T5.3g; modbus_demo — заморозить, если заброшен) и C-19.
3. Разрешить ли Д запуск стенда для наблюдения C-16 (запуск `run.py --headless` отклонил классификатор auto mode;
   разрешение — во вкладке Д, не через координатора).
4. Правило «перед слиянием: validate.py + multiprocess_prototype/backend/tests + framework suite» — уже стоит в трёх стартовых промптах; закрепить ли.
5. Удалить ли пустой `D:\PROJECT_INNOTECH\Inspector_vision\stand.lock` (0 байт, с 2026-10-19).
6. Место C-17-подобных framework-задач в очереди (сейчас C-17 у Д); журнал дня `docs/sessions/2026-10-21.md` не написан.

## Уроки дня

- Решения владельца, отданные прямо во вкладке полосы, координатор узнаёт только из её сообщения — записывать в реестр сразу.
- Запуск бэкенда из сессии может отклонить классификатор auto mode — окно stand закрывать сразу, без наблюдения не считать сделанным.
