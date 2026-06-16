# STATUS — word_layout

**Слой:** plugins · **План:** `plans/word-layout.md` · **Ветка:** feat/pult-control-panel (WIP)

## Готово

- **Ядро** (`geometry.py`, `assembler.py`): раскладка по направлению+шагу / между first-last,
  доворот `wrap180`, проверка зазора; потоковый жадный матчинг (дубли → нужное число раз,
  затем пропуск; готовность слова).
- **Плагин** (`plugin.py`, `registers.py`, `config.py`): `predictions → robot_job {x,y,z,r}`;
  режимы `use_pitch`/between; детект «нового диска» (смена буквы/пауза, дедуп по букве,
  опц. `trigger`); калибровка `angle_zero`/`angle_invert`; команда `reset_word`; прогресс в state.
- **Интеграция:** вписан в рецепт `hikvision_letter_robot` (`infer.predictions → layout.word_layout`),
  валидация структуры headless.
- **Тесты:** 50 (geometry/assembler/plugin), ruff чист.

## Открыто

- **Движение робота:** `layout.word_layout.robot_job → robot_io → devices` — после калибровки
  камера↔робот и pick/place-семантики (ШАГ 2/3 рецепта).
- **Доворот `r` в железе:** `send_job(x,y,rz)` + Lua `cvt_universal_full.lua` + протокол — отдельный шаг.
- **Калибровка на стенде:** `angle_zero_deg`/`angle_invert` (ноль доворота), `place_z_mm`.
- **Мост слова из телефона:** `phone.state.word → порт word` (follow-up).
- **Память:** запись в `docs/claude/memory/` (dual-write).
