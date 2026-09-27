# Передача: редактор слоёв симулятора (полоса С) — 2026-09-27

**Ветка:** `feat/line-sim-layer-editor` (от `main` `bd2b52ab`, 40 коммитов, в `main` НЕ влита, не запушена).
**Worktree:** `.claude/worktrees/ls-layer` — работать только там; общее дерево занято сессией робота.
**План:** [`plans/line-sim-layer-editor.md`](../../plans/line-sim-layer-editor.md) (APPROVED 09-27), очередь — `plans/queue/ORDER.md`, полоса С.

## Сделано

| Задача | Итог | Коммиты |
|---|---|---|
| 1.0 переносимые пути пресета | `base_dir` вместо абсолютизации, save-as пересчитывает пути, прямые слэши (Windows → Mac/Orin); LS-013 | `f8687318`..`68e07f49` |
| 1.1b диск и буква раздельными слоями | слой `class://`, заливка `color_rgb`, `tools/make_font_letters.py`, пресет `letters_layered.yaml`, `.yaml` в `preset_path`; LS-014 | `c0b4ad58`..`97b7c4cd` |
| 1.2a команды пресета | `preset.get/commit` у `scene_source` (rev и запись — из фреймворка `recipe`), горячая подмена фабрики; `preset.preview` в своём процессе `layers` (`Plugins/sim/layer_preview`); запись `recipe.yaml_io` стала атомарной (ADR-RCP-008) | `1ca9b75b`..`9cad8fd0` |
| 1.1 демо-бутылка | DEFERRED — у владельца нет картинок | — |

Каждая задача прошла канон: тестер в worktree до кода → реализация → инъекции лида (все свойства, пробелы
закрыты тестами лида `test_lead_1_1b.py`, `test_lead_1_2a.py`) → ревью (везде 2 итерации, итог APPROVED).
Радиус `Services/line_sim/tests Plugins/sim multiprocess_framework/modules/recipe/tests apps/line_sim`:
661 passed, 7 skipped; `scripts/validate.py` без ошибок.

## Следующий шаг — Task 1.2h (HTML-редактор на `pult_web`)

Первый графический редактор: маршруты `pult_web` → `preset.get/commit` в процесс `camera`, `preset.preview` в
процесс `layers` (форвард через `DeviceHubClient`, как `truth.*`); страница: список слоёв, поля по схеме модели,
превью, сетка образцов, сохранить с `base_rev`/`conflict`. Владелец хочет и перетаскивание слоя мышью — дёшево
добавить сюда. Спеку уточнить при постановке (сейчас в плане набросок). Qt-вкладка (1.2b) ждёт gui-constructor И3.

## Правила, которые действуют

- **Владелец 09-27: собирать из фреймворка как конструктор** — процессы, воркеры, роутер, `recipe` и т.п.; фронт
  тоже конструктор. Перед заданием искать готовый механизм и писать «возьми X». Память:
  `.claude/memory/feedback_build_from_framework_as_constructor.md`.
- **Соседняя сессия — полоса Р** (`robot-protocol-v2`, сейчас `inspector-bottles-4d`): её файлы
  `Services/robot_comm/**`, `Plugins/sim/robot_host/**`, `plans/robot-protocol-v2/**`; в `main` не сливается до M1;
  перед T2.4 напишет (С3 уже закрыта). В `apps/line_sim/pipeline.yaml` она правит только блок `robot`.
  Слияние: пишем друг другу «сливаю…, трогаю…», второй вливает `main` к себе, в ORDER.md каждый — свою полосу.
- `apps/line_sim/pipeline.yaml` в ОБЩЕМ дереве: строка `preset_path` (`letter_catalog_rep`) — незакоммиченная
  правка владельца, не трогать и не коммитить.
- Хуки: задание исполнителю ≤ 6 файлов (иначе `BRIEF-OVERRIDE: <причина>`); `--backend-live` у `apps/line_sim`
  нет — живые тесты `LINE_SIM_LIVE=1` и каталог классов (в worktree его нет — временная ссылка на
  `/Users/twokrai/Project_code/Inspector_bottles/data/line_sim`, убрать после прогона).

## Открытое

- Хвосты 1.2a: N7 — ограда отвергает собственные пути пресета, лежащие вне репо через `../`/симлинк (главное
  дерево не задевает); N8 — цена рендера крупных спрайтов (1200 px → 1.3 с на превью, держит только `layers`);
  дубль `preset_path`/`defect_probability` у `scene_source` и `layer_preview` (YAML-якорь — дешевле всего).
- Хвосты 1.1b: холст объекта с вариациями буквы до ~650 px при видимых ~330 (`composite` 3.6 против 1.3 мс);
  высота буквы нормируется с хвостами.
- Канал «файлы по id» (добавить новый PNG из редактора) не сделан — нужен для 1.2h/1.2b, решается при постановке
  (общий с `dataset-annotation` 1.3).
- Worktree тестеров `ls-1.0-tester`, `ls-1.1b-tester`, `ls-1.2a-tester` можно удалить (их коммиты перенесены
  cherry-pick в ветку).
- Слияние ветки в `main` не делалось — решение владельца.
