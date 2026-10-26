# STATUS — word_layout

**Слой:** plugins · **План:** `plans/word-layout.md` · **Ветка:** feat/pult-control-panel (WIP)

## Готово

- **Ядро** (`geometry.py`, `assembler.py`): раскладка по направлению+шагу / между first-last,
  доворот `wrap180`, проверка зазора; потоковый жадный матчинг (дубли → нужное число раз,
  затем пропуск; готовность слова).
- **Плагин** (`plugin.py`, `registers.py`, `config.py`): `predictions → robot_job {x,y,z,r}`;
  режимы `use_pitch`/between; детект «нового диска» (новый `sidecar.track_id`; без него — смена буквы/пауза, дедуп по букве,
  опц. `trigger`); калибровка `angle_zero`/`angle_invert`; команда `reset_word`; прогресс в state.
  Ограничение: id zone_edge — счётчик процесса line; его рестарт без рестарта layout обнуляет
  id, и диск с id, равным последнему взятому до рестарта, отбрасывается (`reset_word` это не лечит).
  Новый id = новый диск, только если zone_edge даёт одно событие на диск. Диск, пропавший из детекции на ≥ rearm_frames кадров внутри зоны, и рестарт line при диске в зоне дают второй id → второе задание на тот же диск (правка в line_filter — C-42).
- **Интеграция:** вписан в рецепт `hikvision_letter_robot` (`infer.predictions → layout.word_layout`),
  валидация структуры headless.
- **Тесты:** 117 (geometry/assembler/plugin/nan-guard/below_threshold-guard, `test_disk_identity*.py` — C-32, `test_word_source_order*.py` + `test_word_source_chain.py` — C-37), ruff чист.
- **Слово (C-37):** регистр `target_word` — единственное хранилище; слово с порта пишется в него, действует последнее
  пришедшее, журнал называет источник. Ограничения (а)–(и) — в README «Слово: регистр и порт».

- **Страж `below_threshold` (Task 0.3 letters-retrain):** `_top_pred` отказывает предсказанию
  с `below_threshold=True`; тесты `test_acceptance_below_threshold_guard.py`.

## Открыто

- **Движение робота:** `layout.word_layout.robot_job → robot_io → devices` — после калибровки
  камера↔робот и pick/place-семантики (ШАГ 2/3 рецепта).
- **Доворот `r` в железе:** `send_job(x,y,rz)` + Lua `cvt_universal_full.lua` + протокол — отдельный шаг.
- **Калибровка на стенде:** `angle_zero_deg`/`angle_invert` (ноль доворота), `place_z_mm`.
- **Мост слова из телефона:** `phone.state.word → порт word` (follow-up).
- **Память:** запись в `docs/claude/memory/` (dual-write).
