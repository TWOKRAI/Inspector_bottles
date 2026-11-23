# Старт полосы «до-обучение: данные сима» — промпт для нового чата

Вставить в новый чат целиком. Первая строка — название вкладки. Сверено с git `main` = `41e053466` (2026-11-12); шапки планов местами отстают от кода — верить git.
Откуда это: хвост полосы «Приёмка α» (`docs/handoffs/2026-11-12_alpha-rerun.md`) и архитектурное ревью Opus (`docs/reports/2026-11-12_opus-arch-review.md` §5, F3, F4).

```
ВКЛАДКА: До-обучение · данные сима · frame_saver в рецепт, LayerSceneGenerator, augment
ROLE: lead of lane «данные для до-обучения сети на симе». Три дорожки, одна цель: letters-retrain Ф1 получает пары «вырез сима + истина + ответ сети»
  и обучающие кадры из ОДНОГО генератора. Планы: plans/2026-11-11_dataset-sidecar-truth (DS-1), plans/layer-render (Ф6), plans/letters-retrain.
READ FIRST: docs/handoffs/2026-11-12_retrain-data-lane-start.md — разделы «Состояние», «Вопросы владельцу», «Дорожки А/Б/В», «Входы от α» (ПРОЧЕСТЬ ПЕРВЫМ; пока не влит в main — лежит в worktree
  /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/alpha-hard-split, ветка feat/alpha-hard-split); docs/handoffs/2026-11-12_alpha-rerun.md (хвост); plans/2026-11-11_dataset-sidecar-truth/{plan.md, design.md, amendments.md,
  tasks/1.1c.md, tasks/2.3.md}; docs/reports/2026-11-11_ds1_{0.1,1.1a,1.1b,2.1}.md; docs/reports/2026-11-12_opus-arch-review.md §5 (F3, F4);
  plans/layer-render/plan.md (Task 3.1, 6.5) и plans/layer-render/phase-6-task-6.2.md; plans/letters-retrain/plan.md; plans/queue/ORDER.md строки 27, 40.
GOAL: (А) пары сима пишутся стендом сами — `frame_saver` в рецепте `letter_robot_sim`, истина сведена (DS-1 Task 1.1c + 2.3);
  (Б) GUI (вкладка генерации датасета) и `ml_train` берут обучающие кадры из `LayerSceneGenerator`, `DatasetEngine` — FREEZE; (В) штатный пресет сима имеет `augment`, эффекты реально идут.
ГРАНИЦЫ
  Твои файлы: Plugins/io/frame_saver, Plugins/sim/scene_source, Services/line_sim/tools, Services/line_sim/presets/letters_layered.yaml, Services/dataset_gen, Services/ml_train,
  multiprocess_prototype/frontend/widgets/tabs/services/neural, рецепт letter_robot_sim.yaml (только 2.3), apps/line_sim/pipeline.yaml (только `truth_journal_*`).
  Не трогать: scripts/alpha_sim и plans/release-1.0 (полоса «Приёмка α»), робот, Атлас (ветка docs/atlas-pilot-1111), framework; plans/queue/ORDER.md и backlog.md правит сессия Атласа;
  plans/2026-11-11_draw-universal утверждён (contract.lock) — через amendments.md + plans_ledger.py amend; тот же рецепт сима правит draw-universal 3.1 — не в одной волне.
  Слои импортов: framework → Services → Plugins → multiprocess_prototype; `frame_saver` знает только SDK плагинов.
PIPELINE: `.claude/CLAUDE.md` «Task launch convention»: stage 0 (reviewer sonnet, один раз на Task) → слепой tester (новый механизм: 1.1c) → developer sonnet → break-injection (предсказания коммитятся ДО прогона) → reviewer sonnet, живой стенд — лид.
  Не более ДВУХ писателей одновременно, пока координатор не даст третий слот; у каждого свой worktree. Субагенты только диагностика и файлы; коммитит лид (protect-branch).
  Бриф Agent: блоки `DESIGN:`/`FILES:`/`REDS:`/`REPORT:` с двоеточием (линтер) либо `BRIEF-OVERRIDE: <причина>`. Каждая тест/стенд-команда через `machine_gate.sh` (абсолютный путь основного чекаута); heavy и стенд — только в своём окне.
LIMITS: две итерации на петлю, на третьей — вверх (teamlead); вопросы владельцу — списком; не угадывать; Never commit/push без слова в брифе агента.
COMMITS: Conventional Commits + `Why:`, `Layer:`, `Refs: plans/<…>/plan.md`; трейлеры одним абзацем в конце; заголовок ≤ 72; слияния `git merge --no-ff -F <файл>`; не пушить.
REPORT: по-русски, числа, непустое «что осталось открытым», таблица agentId; по задаче — файл отчёта `docs/reports/2026-11-<дата>_<задача>.md`; в конце — handoff и /clear.
```

## Состояние (проверено git, 2026-11-12)

```
СОСТОЯНИЕ (проверено git, 2026-11-12)
  А. DS-1: в `main` — 2.1 (`ml_inference`: `angle_symmetry`, `model_id`) и итоги 0.1, 1.1a, 1.1b (docs). Код 1.1a (`Plugins/io/frame_saver`, `sidecar_keys`/`sidecar_source`) и 1.1b
     (`Plugins/sim/scene_source`, журнал истины JSONL) — на ветках feat/ds1-1a (worktree .claude/worktrees/ds1-1a, +3 коммита) и feat/ds1-1b (.claude/worktrees/ds1-1b, +3), НЕ влиты;
     ревью sonnet r2 APPROVED у обоих. Шапки `[PENDING]` в plan.md устарели. 0.1 = «K2 годится»: p95 задержки 298,2 мс < 500, макс. невязка 4,41 мм < 60, п.7 = 41/46 = 0,891; классы сима и модели 33 = 33.
     Task 1.1c (`join_frame_truth`, новый модуль, слепой tester до кода) — не начата. Task 2.3 — после 1.1c и draw-universal 3.1. В рецепте `letter_robot_sim.yaml` узла `frame_saver`/`dataset_saver` нет.
     draw-universal: ветка feat/draw-universal без коммитов впереди main; Task 3.1 (`ml_inference` только данные, `draw_overlay` убирается) — в конце цепочки 1.4 → 2.2 → 3.1, не начата.
  Б. Вызовы старого движка: `multiprocess_prototype/frontend/widgets/tabs/services/neural/dataset_gen_section.py:214-222` (`DatasetEngine.from_yaml(preset)`, превью и `export_splits`),
     `Services/ml_train/data.py:201-203` (`_build_synthetic`, `config.generator_preset`), `Services/dataset_gen/service.py:32` (проверка импорта). Шов уже есть: `export_splits(generator: SampleGenerator)`
     (`Services/dataset_gen/export.py:48,107`), `bundle_from_generator(generator, config)` (`ml_train/data.py:206`), `LayerSceneGenerator.from_yaml(path, seed=)` (`core/layer_scene.py:211`) — сегодня его зовёт только CLI
     `Services/dataset_gen/tools/export_sim_crops.py`. ФОРМАТЫ ПРЕСЕТОВ РАЗНЫЕ: `DatasetEngine` читает `Services/dataset_gen/presets/*.yaml` (cut-and-paste), `LayerSceneGenerator` — слоёный пресет с секцией `train`
     (`Services/line_sim/presets/letters_layered.yaml`). Просто сменить класс нельзя: нужен выбор пресета в GUI и `DataConfig.generator_preset`.
     layer-render Task 6.5 «свести `DatasetEngine` к пресету слоёв и удалить второй путь» — [PENDING], но УДАЛЕНИЕ противоречит принципу владельца 3 (FREEZE, не KILL): правится амендментом на «заморозить, переключить вызывающих».
  В. `Services/line_sim/presets/letters_layered.yaml`, секция `train` без `augment` → `effects without augment: []` (проба `probe_fx.py` в scratchpad сессии Opus-ревью — в git её нет; воспроизвести своей пробой).
     С `augment: {noise, gaussian_blur, glare, brightness_contrast}` эффекты идут (средняя |разность| пикселей 7,6 / 17,78 / 30,11 / 26,69 / 25,19; разность включает сдвиг RNG — это не чистый эффект).
     Геометрия `augment` (`rotation`, `shift`, `scale`, `contact_shadow`) игнорируется ПО ЗАМЫСЛУ (`layer_scene.py:21`): поворот дают слои пресета.
     Известное расхождение: фотометрия считается на окне `W×W`, а не на кадре сима (`layer_scene.py:22`). layer-render Task 3.1 (пресет v2: `schema_version`, `background`, `effects`, `LayerSpec.enabled/effects`) — [PENDING],
     она меняет схему пресета: добавлять `augment` в существующую секцию `train`, схему НЕ менять.
```

## Вопросы владельцу — первым делом

```
ПЕРВЫМ ДЕЛОМ — вопросы владельцу (списком, с рекомендацией; не угадывать)
  1. draw-universal 3.1 держит 2.3 (тот же рецепт, `draw_overlay: false`; пока `ml_inference` рисует рамку на кадре, `frame_saver` после него сохранит вырез С РАМКОЙ — для обучения непригодно).
     (а) ждать draw-universal 1.4 → 2.2 → 3.1 — рекомендация, если ветка стартует скоро; (б) в рецепте сима поставить `draw_overlay: false` в 2.3 самим и согласовать с владельцем draw-universal (вид в GUI теряет рамку до 3.1);
     (в) `frame_saver` до `ml_inference` — не годится, ответ сети нужен в sidecar. Узнать у координатора/владельца, где сейчас draw-universal, ДО старта 2.3.
  2. Task 6.5: амендмент «заморозить `DatasetEngine`, переключить GUI и `ml_train`» вместо «удалить» — рекомендация да (принцип 3, Opus-ревью §5 п.5).
  3. Фотометрия на окне `W×W` или на кадре сима: рекомендация — оставить окно, пока не замерено, что это влияет на точность сети; выбор зафиксировать в DECISIONS модуля.
  4. Значения `augment` (шум, размытие, блик, яркость) — оценка или замер на реальных кадрах дня №1 (ORDER 27: «сеть с сима может не узнать буквы с MVS»); рекомендация: консервативные значения сейчас, подбор — после замера на реальных кадрах.
```

## Дорожка А — frame_saver в рецепт (DS-1)

```
ДОРОЖКА А — frame_saver в рецепт (DS-1)
  А1. Влить feat/ds1-1a и feat/ds1-1b в main (rebase на main, validate.py + тесты модулей, `git merge --no-ff -F <файл>`; main может стоять на чужой ветке — `git branch --show-current` до коммита; слияние через machine_gate merge-begin/merge-end).
  А2. Task 1.1c `join_frame_truth` (`Services/line_sim/tools`, не импортирует `Plugins` и `multiprocess_prototype`): слепой tester до кода → developer → инъекции → reviewer → `sentrux check .` = 0 нарушений.
      Параметры из 0.1: `--time-offset-ms`, `--radius-mm`; правило «трудного» из DS-1 §6 — единственный источник.
  А3. Task 2.3 — рецепт `letter_robot_sim.yaml` (узел `dataset_saver` в `recog` после `ml_inference`: `save_mode: stream`, `image_format: png`, `index_source: counter`, `max_days: 0`, `subfolder_by_date: true`,
      `write_sidecar: true`, `sidecar_keys: "predictions,pick_xy,model_id"`, `sidecar_source: synthetic`, `output_dir: data/dataset/sim`) и `apps/line_sim/pipeline.yaml` (`truth_journal_dir`, `truth_journal_enc_hz: 10.0`);
      тест `test_letter_robot_sim_diff.py` — узел `dataset_saver` как второе допустимое различие (DS-В3, решено владельцем). Литералы REDS, приёмка на стенде (окно `stand`) — `tasks/2.3.md`.
  Приёмка А: пар в `data/dataset/sim` ≥ `floor(0,9 × вырезов за 10 мин)`; `matched / synthetic ≥ 0,95`; доля верных среди `matched` с `below_threshold: false` ≥ `max(0,5; 0,891 − 0,1)`; 20 случайных пар открыты глазами — буква == `truth.class`, 20 из 20.
  Побочное: когда 1.1c в `main`, СКАЗАТЬ лиду полосы «Приёмка α»: `scripts/alpha_sim` заменит свой `hard_reasons` (три расхождения с DS-1 §6) импортом.
```

## Дорожка Б — GUI и ml_train на LayerSceneGenerator

```
ДОРОЖКА Б — GUI и ml_train на LayerSceneGenerator (layer-render Task 6.5, переформулированная)
  Б1. Амендмент к layer-render (6.5: FREEZE вместо удаления) — по ответу владельца 2.
  Б2. `dataset_gen_section.py`: выбор слоёного пресета (список — `Services/line_sim/presets/*.yaml` с секцией `train`), превью и экспорт через `LayerSceneGenerator.from_yaml(preset, seed=…)`; GUI-код остаётся в `multiprocess_prototype` (расходный), логика выбора — через SampleGenerator.
  Б3. `ml_train`: `_build_synthetic` берёт `LayerSceneGenerator`; `DataConfig.generator_preset` принимает слоёный пресет; смоук обучения на малом наборе (контракт 6.3 в `plans/layer-render/phase-6-task-6.3.md`).
  Б4. `DatasetEngine` остаётся, помечен FREEZE (README/STATUS/DECISIONS модуля), `service.py:32` не ломается. Не удалять.
  Приёмка Б: тесты `Services/dataset_gen`, `Services/ml_train`, виджета зелёные; ни один вызов `DatasetEngine.from_yaml` вне самого модуля и его тестов (`git grep -n "DatasetEngine"` — таблица до/после); GUI-превью строит кадр на слоёном пресете.
```

## Дорожка В — пресет с augment

```
ДОРОЖКА В — пресет с augment
  В1. Пробой воспроизвести F4 (без `augment` → эффектов нет; с `augment` → есть) на `letters_layered.yaml`; зафиксировать пробу в тесте (дорожка ловит возврат «эффекты молча не идут»).
  В2. Добавить `augment` в секцию `train` по ответу владельца 4; секцию читает `layer_scene.py` (`TrainSection`), схему не менять.
  В3. Контрольные числа: кадры с `augment` и без — эффекты применены; детерминизм по seed не сломан (контракт порядка розыгрышей `layer_scene.py:15-22`); при необходимости — обновить golden 6.3.
```

## Входы от полосы «Приёмка α»

```
ВХОДЫ ОТ ПОЛОСЫ «ПРИЁМКА α» (для до-обучения; в git их нет — лежат в worktree .claude/worktrees/alpha-hard-split/data/, при чистке worktree пропадут)
  data/alpha_rerun/run1…run3 (сид 0) и data/alpha_seeds/seed1…seed3: `hard.jsonl` (формат DS-1 §6, порог угла 5,0° — решение владельца 2026-11-12), `pick_table.csv`, `out.txt`.
  Что видно: «трудных» 6–7 за прогон; на сиде 0 «М» узнаётся, но с ошибкой угла (300° → 281,5°); на сидах 1–3 «М» прочитана как «И» ниже порога 0,50 (0,42 / 0,45 / 0,28). Это материал letters-retrain Ф1, не дефект механизма α.
  Реальных кадров MVS в списке нет (DS-В4, день с железом №1).
```
