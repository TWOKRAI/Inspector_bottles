# План: доработка режима рисования робота (draw-mode-rework)

Ветка: `feat/draw-mode-rework`. Slug: `draw-mode-rework`.
Полная версия с обоснованиями — внутренний план Claude Code (`snug-gliding-book`).

## Контекст

Робот-плоттер Delta universal3 рисует по карте точек:
`камера → seg → crop → edge → blob → strokes_to_points → robot_scale → points_render → robot_draw`
→ Modbus → прошивка `robot/universal3/cvt_universal_full.lua` (`execute_path`).
Владелец: теряется ~25% точек, нужен crop без масштаба, текст/имя/сердце, сохранение
рисунка, корректный Стоп, без призрачных линий при переезде. Решения: текст = векторный
Hershey; передача = мельче пачки + read-back ACK (не ping-pong); сохранение = JSON+PNG;
порядок A→B→C→D; без костылей, проще-но-лучше.

## Этап A — точность точек + Стоп + подъём (п.1,6,8)

- [x] A1. Lossless preview (`reduce_mode: none`) + `REG_DRAW_DONE_N=0x1409` + `draw_pass_size`
      (рецепт 30) + read-back ACK с повтором (`draw_verify`/`draw_retry`). Lua+registers+yaml+sim+client.
- [x] A2. Стоп = `draw_home_after(1)`→`draw_abort()`→очистка очереди→`draw_flush()`; рестарт с начала.
- [x] A3. П-образный переезд между штрихами через скретч `GL_MAN` (lua execute_path).
- [x] A-тесты: +7 unit (test_client, test_robot_driver); 273 passed. ADR-RC-006/007/008.
- [ ] A-smoke: headless backend_ctl + qt-mcp (phone_sketch против sim) — общий прогон после стадий.

## Этап B — crop без масштаба + прижим к зоне (п.2)

- [ ] B1. crop `mode=clip` + `paste_x/y` + `clamp_edge` (clip-вставка на холст, без resize).
- [ ] B2. robot_scale `clamp_to_zone` — точка за листом ложится на границу.
- [ ] B3. Контролы пульта (select режим crop, paste_x/y, clamp toggle). Тесты.

## Этап C — текст/имя/сердце, векторный Hershey (п.3,4,5)

- [x] C1. Плагин `text_vector`: strokes_font (0-9, A-Z, А-Я, пробел, сердце); geometry (layout,
      матрица 2×2 центр+поворот+масштаб, → px draw_points); registers; plugin (merge/override, passthrough).
- [x] C2. Интеграция в рецепт: 2 экземпляра (text_main/text_name) в конце `lines` (резолв по class_path,
      distinct plugin_name), провод → robot_scale, 16 контролов пульта. 17 тестов text_vector.
- [x] C3. Несколько элементов = несколько экземпляров (merge=true накапливает); 48 recipe-тестов зелёные.

## Этап D — сохранение/загрузка (п.7)

- [x] D1. Плагин `drawing_io`: store (save JSON+PNG / load round-trip), plugin (cmd_save armed,
      cmd_load override draw_points при load_active). 10 тестов.
- [x] D2. Интеграция: drawing_io в points index 1 (после robot_scale, до points_render — load
      обновляет превью И робота); контролы пульта (Сохранить/Загрузить/Рисовать загруженное);
      dry_run контрол сдвинут 2→3; drawings/ в .gitignore. 58 passed.
- Примечание: PNG-референс = кадр на позиции (line-art), не сырое фото — сырое фото в points
  потребовало бы chain seg→points (пачкает превью), сознательно отложено (ядро save/load доставлено).

## Ревью (многоагентное, 50 агентов, 5 линз + adversarial-verify)

Подтверждено: точки НЕ теряются — split_draw_passes лосслесс, verify-net ловит усечение,
кэпов нигде нет, e2e-тест на 2000 точек зелёный. Исправлены подтверждённые дефекты качества:
- **FIX-1 (важно):** overlap-возобновление длинного штриха — раньше на каждой границе прохода
  терялся 1 сегмент (хуже из-за pass_size=30); +connectivity-тест (каждый смежный сегмент рисуется).
- **FIX-2:** Стоп МЕЖДУ проходами теперь честно ведёт домой (idle-DRAW abort ветка lua + sim).
- **FIX-3:** загруженный рисунок прижимается к ТЕКУЩЕМУ листу (не рисует мимо бумаги).
- **FIX-4:** on_progress→snapshot — диагностика «verify_failed/N из M» больше не теряется;
  disconnect не глотает ошибку молча.
- **FIX-5:** добавлена Ё (имена с ё не теряют букву) + тест полного А-Я+Ё.
- **FIX-6:** честный docstring про overdraw при retry; split нормализует первый pen=0; crop
  clip no-op fast-path (не тратит холст); уникальный stem сохранения; правки комментариев.

Отложено осознанно (low/документировано): async-сохранение drawing_io (one-shot, мал. эффект),
points_dropped-счётчик (нет активных продюсеров плохих dict), surface points_clamped в дашборд.

## Проверка

- pytest (Services/robot_comm, device_hub, Plugins/processing/{crop,text_vector}, Plugins/io/drawing_io)
- headless backend_ctl против sim (`python -m Services.robot_comm.server`)
- qt-mcp smoke (`QT_MCP_PROBE=1 ... run.py phone_sketch`, порт 9142)
- железо: нет призрачных линий (A3), зелёные точки = нарисованное (A1).
