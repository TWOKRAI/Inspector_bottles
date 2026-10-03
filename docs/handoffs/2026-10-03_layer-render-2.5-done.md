---
date: 2026-10-03
topic: layer-render — Task 2.5 render_scene закрыта; дальше 3.1 / 4.2 / 6.2 / Ф7 на решение владельца
machine: Windows
branch: feat/layer-render
---

## Состояние

- Предыдущий handoff: [2026-10-03_layer-render-wave5-done.md](2026-10-03_layer-render-wave5-done.md) (волна 5: 2.4a, 2.4b).
- **2.5 закрыта** на `feat/layer-render` (2026-10-03): спека `920c11475` (ревью спеки 2 итерации), RED `7d524165d`,
  код `0fbb79e33`, отчёт инъекций `c793a4559`, правки ревью `c04299285`, закрытие — следующий коммит `docs(plans)`.
- Суть: `Services/layer_render/scene.py` — `SceneBackground`, `PlacedObject`, `render_scene(background, placed, effects,
  rng)`: фон → объекты → эффекты; без отсечения, без своего rng. `SceneCompositor` делегирует, держит геометрию ленты,
  отсечение, паспорта. ADR — LR-003. `line_sim` больше не импортирует `dataset_gen.core.compose`.
- Проверки: слепые 113 RED → 124 GREEN; hazard автора 19; инъекции лида 15/16 + 2/2 (i3 — ось цены);
  ревью кода APPROVED (сетка 19 656 входов, 0 байтовых расхождений); A/B стенда `28f51303…`/`54b548c0…` = до задачи;
  цена render 1440×1080: 8.26–8.58 → 7.95–8.55 мс; процессный стенд 16:30–16:32 ok.
  Отчёты: `docs/reviews/2026-10-03_task-2.5-{tester,developer,lead-injections,code-review}.md`.
- `main` не двигался. Worktree тестера `lr25-tester` и ветка `red/layer-render-2.5` удалены. Замок стенда снят.
- agentId 2.5: tester `a8949cab1b396d2a4`, developer `a0e7c03bffbea7437` (~199k — на следующей задаче свежий),
  reviewer спеки `abaed9b9316bd792d`, reviewer кода `ac3f9da1af88ffeee`.
- Расход 2.5 (subagent `total_tokens`): ревью спеки 189k + 13k, тестер 194k, developer 185k + 14k, ревью кода 189k.

## Next step

1. Владельцу: следующая задача. Разблокированы 2.5: **3.1** пресет v2 (эффекты сцены в `produce()` пойдут через `effects`
   этой функции, поток `[seed, 1]`), **4.2** `scene.preview` (кадр `render_scene`; по порядку фаз — после 3.1 и 4.1), **6.2**
   `LayerSceneGenerator` (6.1 DONE `f9ef5c45` — разблокирована полностью, открывает letters-retrain Ф1), **Ф7** источники.
   Рекомендация лида — **3.1**: критический путь редактора (приоритет владельца, Ф3 → Ф4 → Ф5). Если важнее обучение —
   6.2, она независима от 3.1.
2. Порядок тот же: спека отдельным файлом → стадия 0 → слепой tester в worktree → свежий developer → инъекции → ревью.

## Open

- Follow-up: docstring `Plugins/sim/scene_source/plugin.py:955` ссылается на переворот каналов в `SceneCompositor.render()`,
  которого больше нет (вне Files 2.5).
- Свойство «без лишней копии кадра» (i3) держит только замер; цена при многих объектах в кадре не мерилась.
- A8 тестера слеп к дефектам внутри `render_scene` (эталон строится через неё); держат A3 и литералы A7.
- OPEN_QUESTIONS: повтор флака `pult_web` r5 (второй за два дня, под нагрузкой) — кандидат в `investigator`; ответы
  `belt.run`/`belt.stop` похожи на состояние до команды.
- Из волны 5 остаются: `ScenePreset` без каталога принимает `damaged`; `TypeError` в `load_layer_sprite`; `compose_layers`
  с сырым `max()`; `PYTHONIOENCODING`; размер OPEN_QUESTIONS (>168 КБ).
