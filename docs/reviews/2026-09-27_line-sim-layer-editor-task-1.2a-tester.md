# Task 1.2a — приёмочные тесты (тестер, RED до реализации)

Файл: `Plugins/sim/scene_source/tests/test_acceptance_1_2a_preset_commands.py` (9 тестов:
1 GREEN-контроль + 8 приёмочных P1–P8). Работа велась в worktree
`.claude/worktrees/ls-1.2a-tester` (ветка `test/ls-layer-1.2a`, коммит перед реализацией).

## Результат прогона

```
PYTHONPATH=$PWD .venv/bin/python -m pytest \
  Plugins/sim/scene_source/tests/test_acceptance_1_2a_preset_commands.py -q --tb=short
```

`9 collected`, `1 passed` (GREEN-контроль), `8 failed` — все восемь падений с одной и той
же причиной: `plugin.commands` не содержит `preset.get`/`preset.commit`/`preset.preview`
(текущая карта — только `scene.job_done`, `scene.status`, `truth.status`, `truth.reset`).
Ни одного падения по другой причине (импорт, сборка движка фикстуры, синтаксис) — GREEN-
контроль подтверждает, что фикстура (каталог классов + `disk.png` + `preset.yaml` с диском
`static`/белый и буквой `class://`/чёрная) реально собирает `SceneSourcePlugin` и рендерит
кадры на НАСТОЯЩЕМ коде движка (`Services.line_sim`), а не на моках.

| Тест | Предсказано | Факт | Строка падения |
|---|---|---|---|
| `test_control_fixture_engine_ready_and_produces_frames` | GREEN | **PASSED** | — |
| `test_p1_get_returns_file_preset_and_sha_rev` | RED, нет команды | RED, нет команды | `_call_command` (assert `'preset.get' in commands`) |
| `test_p2_commit_fresh_rev_writes_file_and_new_rev` | RED, нет команды | RED, нет команды | `_call_command` (`'preset.commit'`) |
| `test_p3_stale_rev_conflict_and_single_winner` | RED, нет команды | RED, нет команды | `_call_command` (`'preset.commit'`, до входа в потоки) |
| `test_p4_invalid_preset_rejected_file_untouched_frames_continue` | RED, нет команды | RED, нет команды | `_call_command` (`'preset.commit'`) |
| `test_p5_hot_swap_recolors_new_objects_without_restart` | RED, нет команды | RED, нет команды | `_call_command` (`'preset.commit'`) |
| `test_p6_preview_grid_and_no_effect_on_frames` | RED, нет команды | RED, нет команды | `_call_command` (`'preset.preview'`) |
| `test_p7_preview_unsaved_preset_and_limits` | RED, нет команды | RED, нет команды | `_call_command` (`'preset.preview'`) |
| `test_p8_catalog_plugin_commit_bad_request` | RED, нет команды | RED, нет команды | `_call_command` (`'preset.commit'`) |

SHA коммита с тестами — см. `git log -1` после коммита ниже.

## Что я истолковал, а не выполнил буквально

- **Формат `to_dict()`/`from_dict()` ScenePreset.** README называет только сигнатуры, не
  форму (list vs tuple для `layers`, `color_rgb`). Я предположил, что `layers` — список
  словарей (обязательное для Dict at Boundary), а `color_rgb` при записи в мутируемый
  dict передаю как список `[r, g, b]` (pydantic коэрсит в tuple при повторной валидации).
  Тест `test_control_...` подтвердил, что `ScenePreset.to_yaml`/`from_yaml` работают на
  этой фикстуре, но НЕ подтвердил форму `to_dict()` — она пока не вызывалась ни разу
  успешно (команды нет). Если реализация вернёт другую форму (например `layers` как
  список объектов `LayerSpec` без `.model_dump()`), P2/P3/P4/P5/P7/P8 могут потребовать
  правки на стороне теста, а не имплементации — решить на ревью.
- **Текст ошибки P4 (два слоя `class://`).** Спека требует «имя слоя в тексте», не говоря
  какое из двух. Ослабил проверку до `any(name in message for name in (...))` — приму
  любое из трёх имён слоёв, лишь бы имя присутствовало.
- **Числовые константы P5 (шаг энкодера, `cap`, `sleep`).** Спека просила «generous upper
  bound» и не дала числа. Взял шаг `5.0` по энкодеру (масштаб из разрешённого
  `test_scene_source_hazards_1_1b.py`, там `10.0` уже давало видимый объект за 2–3 кадра),
  `cap=400`, `sleep=0.01`/`0.005` — не проверено на реальной реализации (команды ещё нет),
  риск ложного RED из-за слишком редких кадров при другом `FACTOR_MM` не исключён.
- **`spawn_interval_s`, а не `spawn_spacing_mm`**, хотя гармоничный образец
  (`test_scene_source_hazards_1_1b.py`) использует `spacing_mm` — выполнил буквально
  указание лида «spawn_interval_s short» в DESIGN, это времязависимый режим, тест P5
  использует реальные `time.sleep`.

## Что оставил открытым / ненадёжным

- **P2/P3/P4/P5/P7/P8 ни разу не проверялись на настоящей реализации команд** — RED
  наступает раньше, на отсутствии команды в `plugin.commands`, так что раздел «после
  `preset.commit`» каждого теста (сравнение содержимого файла, `rev`, кодов ошибок)
  синтаксически корректен (импорты, фикстура, `ScenePreset` — всё реальное), но
  СЕМАНТИЧЕСКИ не подтверждён прогоном — как и требует протокол RED, это ожидаемо и
  является следующим шагом (GREEN у teamlead).
- **P3, шаг с двумя потоками** — join-таймаут 10 с страхует от зависания сьюта, но сам
  тест НЕ проверял, что реализация действительно возьмёт какой-то лок вокруг записи
  файла (на RED-этапе это невозможно проверить — команда отсутствует).
- **P6 bitwise-сравнение двух инстансов** предполагает, что `seed`-детерминизм плагина
  зависит только от `cfg["seed"]` и последовательности `produce()`, без скрытого
  недетерминированного состояния (текущего времени, PID и т.п.) — это утверждение взято
  из README (`rng` плагина — единственный producer случайности), не проверено напрямую.
- **`Path(result["path"]).resolve() == preset_path.resolve()` в P1** — сравнение через
  `.resolve()`, а не строковое, на случай, если плагин хранит `Path`-объект или строку в
  другой нормализации; не проверялось, что это верное решение для macOS `/private/var`
  symlink-путей `tmp_path`.

## Утечки

Не обнаружено. Работал только в worktree `.claude/worktrees/ls-1.2a-tester`; читал
только: план (раздел Task 1.2a), `Plugins/sim/scene_source/README.md`,
`Services/line_sim/README.md`, `Services/line_sim/interfaces.py`,
`Services/line_sim/__init__.py`, единственный разрешённый файл-образец
`Plugins/sim/scene_source/tests/test_scene_source_hazards_1_1b.py`. Тела
`Plugins/sim/scene_source/plugin.py`, `Services/line_sim/core/*.py`,
`multiprocess_framework/modules/recipe/*` и прочих тестовых файлов не открывал; широких
grep по тестовым каталогам не запускал.

Boundary: task closed. /compact (focus: files + tests + plan path).
