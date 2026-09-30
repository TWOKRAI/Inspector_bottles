# Передача: 1.3h-c реализована и слита в ветку задачи — дальше инъекции, ревью, Chrome

Дата: 2026-09-29. Ветка `feat/line-sim-layer-editor`, worktree `.claude/worktrees/ls-layer`. В `main` не вливалась.
План разбит на файлы: `plans/line-sim-layer-editor/plan.md` (индекс задач) + фазы; задача —
[`task-1.3h-c-layers.md`](../../plans/line-sim-layer-editor/task-1.3h-c-layers.md) (контракт, S1–S4/C1–C10,
«Закреплено после слепых тестеров», заготовка канала записи 1.3h-d).

## Что сделано (все агенты — Sonnet 5.5, подтверждено их отчётами)

| Коммит | Что |
|---|---|
| `f562f7d8`, `c8fe3540`, `ba10183d` | план: разбивка на файлы, секция 1.3h-c, правка S1 (ограда путей), решения по вопросам тестеров |
| `eba09d9a` | слепой тестер S: `test_acceptance_1_3h_c_sprites.py` (18) + `pult_web/tests/test_acceptance_1_3h_c_route.py` (5) |
| `c9c21658` | слепой тестер C: `test_acceptance_1_3h_c_layers.py` (26, 2 самопроверки харнесса), `page_offline.mjs` (модель `<select>`) |
| `2d9bb4cc` → merge `f5ad21dc` | c1 developer: `preset.sprites` в `layer_preview`, helper `sprite_entry` (шов 1.3h-d), 12 hazard |
| `1eadac12` → merge `a87a1394` | c2 developer: маршрут, разметка, `presetApplyLayersEdit`, `presetAddLayer(entry)`, 10 hazard |
| этот коммит | `test_layer_preview.py` ждёт третью команду в `commands`; эта передача |

Лид проверил: до реализации 46 RED / 3 зелёных самопроверки. После слияния все приёмочные S и C зелёные.
Отчёты: `docs/reviews/2026-09-29_line-sim-layer-editor-task-1.3h-c-{tester-s,tester-c,dev-c1,dev-c2}.md`.

## Радиус после слияния — не чистый, разобрано

`pytest Plugins/sim Services/line_sim` → 14 FAILED. Классы:
- **Наш, первый шаг следующей сессии:** `test_hazards_1_3h_c_sprites.py::test_file_on_another_drive_from_preset_dir_is_skipped_not_fatal`
  **виснет** 20 с: тест берёт `Z:` как «несуществующий диск», а на этой машине `Z:` — сетевой
  `\\192.168.11.11\innotech` (отключён), `resolve()` ждёт сетевой таймаут. Правка теста: букву брать вне
  `ctypes.windll.kernel32.GetLogicalDrives()` (маска включает и сетевые). Отдельно решить: `_preset_dir()`
  зовёт `resolve()` на каждый запрос — пресет на недоступном сетевом диске повесит команду (скорее запись
  в README как предел, чем код).
- **Средовые, есть и на базе до 1.3h-c** (проверено в worktree `ls-13hc-s-tester`, 6 из 7 падают там же):
  scene_source `test_commit_keeps_file_mode`, `test_h8_…`, `test_texture_channel_order_in_frame`;
  line_sim `test_font_tool_…` ×2 (WinError 10106 в подпроцессе), `test_save_as_on_windows_…` (RecursionError);
  tmp на `C:` при репо на `D:` (`relpath` между дисками). Ветка `fix/sim-windows-tests` (другая сессия).
- **Флейки чужих веток:** `pult_web` ранние отказы (10053/415) — `fix/pult-web-early-reject-flake`
  (inspector-bottles-18); `layer_preview::test_p6` — `fix/layer-preview-p6-flake`. `robot_host` ×5 (порты,
  10106) — в этом прогоне среда сети деградировала; прогнать повторно отдельно.

## Дальше — по порядку

1. Поправить hazard `Z:` (выше), прогнать радиус `Plugins/sim/layer_preview/tests Plugins/sim/pult_web/tests`.
2. **Инъекции лида**, предсказания до прогона, против ОБОИХ наборов (тестеров и авторов). Свойства:
   ограда раньше существования; junction-петля (c1 уже проверил одну строку); отсечение >500 после сортировки;
   `sprite_source` от каталога пресета; `layer_template` из `LayerSpec`; имя из основы + резерв `base`/`damaged`;
   слой встаёт последним и выбирается; no-op без undo и без запроса; `clearTimeout` таймера стрелок;
   `presetCancelGesture` при удалении; `presetLayoutSeq` для запоздалого ответа; отмена удаления на прежний индекс;
   `textContent` (не `innerHTML`) в `<option>`. Непроверенные автором c2: генерация имён, undo удаления на краях,
   «Заменить» тем же файлом.
3. `reviewer` (Opus) синхронно, `run_in_background: false`.
4. **Живой Chrome лидом** (`@browser` в сообщении владельца). Подозрения из отчётов, харнесс их не видит:
   - фокус остаётся на кнопке после клика → Space/Enter повторит «Добавить»/«Выше» (родня B1 из 1.3h-b;
     c2 фокус на канву **не** переводил);
   - «Отмена» после «Добавить» оставляет `presetSelected` на исчезнувшем имени (кнопки инертны);
   - события `<select>`, кириллица и пробелы в именах файлов/слоёв, сохранение выбора при «Обновить список».
   Стенд — как в прошлой передаче (`apps/line_sim/run.py`, порты 8092/8091/8766/5021), без «Сохранить»;
   положить копию `letters_font_disk.png` в `data/line_sim/`.
5. План: статус 1.3h-c DONE, индекс в `plan.md`; снести worktree `ls-13hc-{s-tester,c-tester,c1,c2}` и ветки
   `tests/ls-13hc-*`, `feat/ls-13hc-*` (слиты).

## Соседи (сверено 2026-09-29)
- **inspector-bottles-18** — `fix/pult-web-early-reject-flake` (`handle`, `_linger_close`, `_read_command_body`
  + 400/411 на chunked) и `fix/layer-preview-p6-flake` (только `test_layer_preview.py::p6`). Наши секции
  не задевает; пришлёт SHA, когда уйдёт в `main` — тогда подтянуть `main` в ветку. `plugin.py` в индексе LF
  (CRLF только в рабочей копии из-за `core.autocrlf`).
- **inspector-bottles-8b** — transport-single-policy Ф4 во фреймворке; не пересекаемся.

## Ловушки (новые)
- Буква диска как «несуществующая» — не бывает на машине с сетевыми дисками.
- Хук `append session log` дописывает `docs/sessions/2026-09-29.md` в коммиты агентов — это не их правка.
