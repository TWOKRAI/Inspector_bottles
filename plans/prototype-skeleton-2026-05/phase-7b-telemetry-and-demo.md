# Phase 7b — Wire telemetry + end-to-end демо

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/pipeline-telemetry-and-demo`
> **Дней**: 4-5
> **Зависимости**: Phase 7a
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-7b-telemetry-and-demo.md, plans/prototype-skeleton-2026-05/plan.md`
> **Парная фаза**: [phase-7a-display-node-and-io.md](phase-7a-display-node-and-io.md)

## Цель

Достроить телеметрию edges (раздельные slow/fast таймеры), создать плагин `blur`, собрать рабочий end-to-end демо `demo_webcam_split_merge.yaml`.

## Реальная фундация

- **Унаследованные идеи** из удалённого Constructor (через `git show 9885bb88:`):
  - Раздельная wire-телеметрия: `WireStatus` (slow ~2с) и `WireMetrics` (fast ~1с) — два независимых таймера.
- Готовые плагины: `capture`, `resize`, `region_split`, `grayscale`, `color_mask`, `negative`, `flip`, `stitcher`, `render_overlay`. Плагин `blur` — **создать** (~50 строк, тривиальный — OpenCV GaussianBlur).
- DisplayNodeItem, target_process binding, `pipeline/io.py` — готовы в Phase 7a.

## Новое

### 1. Wire-телеметрия

- `WireMetricsModel` (по чертежу удалённого, переписан под QGraphicsScene) — два сигнала `statuses_changed` (slow), `metrics_changed` (fast).
- `WireMetricsBadge` (новый, на нативном QGraphicsItem) — overlay на midpoint edge'а с текстом «30fps | 5ms | 50%».
- Опционально (если время): `ShmDashboardPanel` сбоку как сводная таблица.

### 2. Плагин blur

- `Plugins/processing/blur/` — ~50 строк, OpenCV GaussianBlur. Параметры: `kernel_size`, `sigma`.

### 3. Готовый шаблон-демо — `multiprocess_prototype/recipes/demo_webcam_split_merge.yaml`

```yaml
version: 2
name: demo_webcam_split_merge
description: webcam → split ROI → parallel processing → InspectorManager merge → display
blueprint:
  processes:
    - name: capture_proc
      plugins:
        - capture:
            camera_id: webcam0
        - resize:
            width: 1280
            height: 720
        - region_split:
            rois:
              - {name: left, target: roi_a_proc.process_workers, total_regions: 2}
              - {name: right, target: roi_b_proc.process_workers, total_regions: 2}
    - name: roi_a_proc
      plugins: [grayscale, color_mask]
    - name: roi_b_proc
      plugins: [negative, blur]
    - name: merge_proc
      plugins: [stitcher, render_overlay]  # stitcher через InspectorManager fan-in
  wires:
    - capture_proc.region_split.region -> roi_a_proc.grayscale.frame
    - capture_proc.region_split.region -> roi_b_proc.negative.frame
    - roi_a_proc.color_mask.frame -> merge_proc.stitcher.region
    - roi_b_proc.blur.frame -> merge_proc.stitcher.region
  active_services: [webcam_camera]
display_bindings:
  - source: merge_proc.render_overlay.frame
    display: main_output
  - source: capture_proc.resize.frame
    display: debug_input  # промежуточный для отладки
```

**Важно**: region_split проставляет каждому item `target` и `total_regions`. Router отправляет item в соответствующий процесс. InspectorManager в merge_proc буферизует по `seq_id`, ждёт обе ROI, передаёт коллекцию stitcher'у. Это **существующий паттерн**, не multi-port.

### 4. Кнопка «Запустить активный рецепт»

- В PipelineTab/RecipesTab — `SystemLauncher.launch_blueprint(recipe.blueprint)`.
- Если уже запущено — `ProcessManager.replace_blueprint(new)`.

## Acceptance

- Выбрали `demo_webcam_split_merge` активным → запустили → главное окно показывает кадр с двумя обработанными ROI на местах, отладочное окно — кадр после resize.
- WireMetricsBadge на каждом активном edge показывают fps/latency/buffer_fill.
- 10-15 unit-тестов: wire telemetry (statuses_changed, metrics_changed), плагин blur, кнопка «Запустить».
- Integration-тест: загрузка демо-рецепта, проверка что blueprint валидируется и процессы стартуют (без реальной камеры — с mock-сервисом).
