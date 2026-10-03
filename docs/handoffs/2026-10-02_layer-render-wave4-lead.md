---
date: 2026-10-02
topic: layer-render волна 4 (2.3 layers.py, 6.4 holdout на формуле конвейера) — реализации закоммичены, дальше инъекции лида
machine: Windows
branch: feat/layer-render
---

## Состояние

- Спеки: 2.3 — `plans/layer-render/phase-2-core.md`, 6.4 — `phase-6-train.md`; финал `183e2c60`. Ревью спеки (reviewer Opus
  `a6e6a2c00adf101e0`): ит.1 3 MAJOR + 16 MINOR, ит.2 — 2.3 APPROVED, 6.4 4 MINOR внесены дословно.
- Решения владельца по Ф9 (разметка) записаны в `plan.md` → Ф9: свой формат + экспорт; 4 типа регионов; веб, затем Qt;
  кадры со стенда, из папки, из сима. Следствие: Task 3.1 несёт `kind` слоя. Вопрос в OPEN_QUESTIONS закрыт.
- Слепые RED-наборы влиты в `feat/layer-render` (`e8c58a44`, `b8e57092`): 2.3 — 230 кейсов (130 RED / 100 GREEN до кода),
  6.4 — 60 кейсов (46 RED / 14 GREEN). Тестер 6.4 воспроизвёл `IndexError` `holdout_eval.py:118` на базе.
- Реализации закоммичены лидом (не влиты):
  - 2.3 — `dfb0a6b3` на `feat/lr-2.3-impl`, worktree `../Inspector_bottles--lr23-impl`. Прогон лида: layer_render+line_sim 1247 passed / 2 skipped.
    Teamlead: Plugins/sim 743 passed, sentrux ✓, validate чисто, перенос сверен `ast.dump`.
  - 6.4 — `1d618b0b` на `feat/lr-6.4-impl`, worktree `../Inspector_bottles--lr64-impl`. Прогон лида: 573 passed (без файла 2.3).

## agentId (дозов — SendMessage по id)

| Роль | agentId |
|---|---|
| reviewer спеки (Opus) | `a6e6a2c00adf101e0` |
| tester 2.3 (Sonnet) | `ae6198471e6bd0937` |
| tester 6.4 (Sonnet) | `ab531d13db0a0f447` |
| teamlead 2.3 (Opus) — автор, правки ревью ему | `a682348167aef3b20` |
| developer 6.4 (Sonnet) — автор, правки ревью ему | `a205b0d53753ccaf0` |

## Next step

1. **Инъекции лида** (предсказание ДО прогона, против файла тестера И hazard-файла автора), в impl-worktree, после — `git checkout` файла:
   - 2.3: (а) `rng.spawn` → последовательные `rng` у слоёв; (б) порядок `AUGMENT_FIELDS` переставлен; (в) `color_rgb` defect-слоя после `continue`;
     (г) `transform_layer` «как есть» отдаёт `.copy()`; (д) `rgba` read-only в `compose_layers`; (е) проверка дублей после неизвестного дефекта;
     (ж) `label` не подставлен; (з) `canvas_size` убран из `__all__` `layered_object`; (и) импорт `line_sim` в `layers.py`; (к) `_hue_shift_color` без короткого пути при 0.
   - 6.4: (а) `oob="replicate"` вместо `pad`; (б) без `resize_square`; (в) формула стороны старая; (г) `pad_value` не передан; (д) дефолт `margin_px 18`;
     (е) CLI `default=14` вместо `None`; (ж) гейт `ok` в логе снят; (з) `pad_color_bgr` в сводке кортежем; (и) `--pad-color-bgr` принимает 300.
2. **Живой прогон A7 (6.4):** старое — в worktree на `b8e57092` (до кода), новое — на `1d618b0b`; модель `mobilenet_v3_large_20260616_050828`,
   `data/real_photos` (8 кадров, участвовали в обучении); команда в TRAPS спеки. Числа — в `Services/ml_train/STATUS.md` (строка «TBD»).
3. **Ревью** — reviewer Opus на каждую задачу, синхронно, свежий (не ревьюер спеки).
4. **Слияние** в `feat/layer-render`: обе задачи правят `Services/layer_render/README.md` — конфликт свести руками;
   `docs/sessions/*` — union. После слияния: `layer_render/STATUS.md` строка 7 про `_crop_disk`/`replicate` устарела (нит developer 6.4).
5. План: статусы 2.3/6.4 DONE с SHA, журнал; потом вопрос владельцу — волна 5 (2.4 переезд пресета/фабрики ∥ ?).

## Open

- Teamlead 2.3: разбор `passport.defect` теперь до проверки пустого списка (для не-строки `AttributeError` раньше); h1/h5/h6 и
  файл тестера импортируют `line_sim` из `layer_render/tests/` — нарушение правила STATUS, нужно решение (исключение для приёмки переезда?).
- Developer 6.4: лог промаха убран целиком (`angle=` и `err=`), по тесту тестера; `--pad-color-bgr` принимает пробелы и `1_0`; `--radius-scale 0` не отвергается.
- Тестер 6.4: 7 тестов «плохой pad» зелёные на базе по неверной причине (argparse отвергал неизвестный флаг).
- «grep рамки = 0» в Gate — шаблон не определён ни для кого; уточнить в шаблоне спеки.
- Сосед (сессия 19, transport-single-policy): рецепты `inspection_basic`/`multi_camera` не стартуют — чинит их Task 5.9a, нас не касается.
- `docs/claude/OPEN_QUESTIONS.md` 168 КБ при бюджете 32 КБ (doc-size-guard) — разбить по разделам, отдельной задачей.

## Unreliable

- Прогоны агентов шли на основном `.venv` с PYTHONPATH worktree; Plugins/sim после 2.3 гонял только teamlead (поддиректории pult_web — нет).
- 6.4 проверен только на stub-движке; сквозная проводка — только после живого прогона A7.
