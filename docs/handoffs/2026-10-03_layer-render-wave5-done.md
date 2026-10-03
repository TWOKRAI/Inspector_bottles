---
date: 2026-10-03
topic: layer-render волна 5 закрыта (2.4a + 2.4b); дальше — состав волны 6 на решение владельца
machine: Windows
branch: feat/layer-render
---

## Состояние

- **2.4a** влита `be42ba755` (2026-10-02). **2.4b** закрыта на `feat/layer-render` (2026-10-03): спека `55d328cc5`,
  RED `081329dab`, реализация `bb085a9ee`, инъекции `7a40f4dc3`, правки ревью `548144ef4`, закрытие `b8c0624cd`.
  Отдельной ветки реализации не было — коммиты прямо в `feat/layer-render`.
- 2.4b: фабрика и превью в `layer_render` (`ObjectFactory.render -> RenderedObject`); `line_sim.ObjectFactory` — наследник
  базы (флаг оператора + паспорт, `LayeredObject.from_rendered`); старые пути — реэкспорт.
- Проверки 2.4b: слепые 369 RED → 659 GREEN; радиус layer_render 1470, line_sim 580, dataset_gen 188, ml_train 141,
  Plugins/sim 743, apps/line_sim 26, sentrux и validate чисто; инъекции 14/15 (i9 — ось пуста, зонд); ревью кода ит.1
  APPROVED (6 minor внесены). Отчёты: `docs/reviews/2026-10-03_task-2.4b-{developer,lead-injections,code-review}.md`.
- Живой стенд: процессный не поднимался; A/B плагина `scene_source` на конфиге стенда (80 кадров, p=0.25) — sha кадров и
  паспортов старый = новый. Довод «процессы/IPC не менялись» — не проверка; если владелец требует процессный стенд —
  брать `.claude/stand.lock` и предупреждать соседа f4.
- `main` не двигался. Worktree тестера `lr24b-tester` и ветка `red/layer-render-2.4b` удалены.
- agentId трека: developer `a7aa8eddb36a6a74f` (2.4a + 2.4b + правки), reviewer спеки `ad12e5fcbddf2455c`, tester 2.4b
  `addf347f17f49d021`, reviewer кода 2.4b `a884396ad986ca28a`. Developer уже ~260k — на следующей задаче лучше свежий.

## Next step

1. Владельцу: состав волны 6. Кандидаты, разблокированные 2.4: **2.5** `render_scene` (одна функция кадра; ей ждут 4.2
   и 6.2), **3.1** пресет v2 (ждал 2.4), **Ф7** источники спрайтов. Рекомендация лида — 2.5 первой: на ней стоят 4.2
   (превью = кадр сима) и 6.2 (генератор обучения).
2. Дальше — тот же порядок: спека отдельным файлом → стадия 0 → слепой tester в worktree → developer → инъекции → ревью.

## Open

- Follow-up: `ScenePreset` без каталога принимает слой `damaged` (ошибка только в `make`, было и до 2.4b).
- Follow-up: текст `TypeError` в `load_layer_sprite` называет `Services.line_sim.core.factory` (закреплён тестом 2.3).
- Follow-up: `compose_layers` без слоёв на канве — сырой `max()`.
- Follow-up: два теста `line_sim` красные с `PYTHONIOENCODING=utf-8` (и до 2.4a).
- Цикл пакетов `layer_render ↔ dataset_gen` возможен без `ImportError` (i11): сторож — сканеры границ, не чистый импорт.
- `docs/claude/OPEN_QUESTIONS.md` 168 КБ при бюджете 32 КБ — отдельной задачей.
