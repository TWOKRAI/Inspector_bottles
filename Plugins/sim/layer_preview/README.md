# Plugins/sim/layer_preview — превью пресета слоёв в своём процессе

Плагин процесса `layers` приложения `apps/line_sim` (редактор слоёв, Task 1.2a, ревью S1). Одна команда —
`preset.preview`: сетка объектов пресета по seed в PNG. Своих портов данных нет (side-effect, `category: control`).

## Зачем отдельный процесс

Превью объекта по-настоящему стоит ~88 мс (8 seed по 160 px, пресет `letters_layered` на Arial 300 px, замер
ревью 1.2a). Пока оно жило в `scene_source`, эти 88 мс держали единственный поток команд процесса `camera`, и
`scene.job_done` от робота ждал столько же. В своём процессе поток сцены свободен: задержка `job_done` при
непрерывном превью — медиана 0.004 мс (замер тимлида, два потока одного процесса — верхняя оценка). Правило
владельца 2026-09-27: собирать из процессов и роутера фреймворка, а не из своих потоков в плагине.

## Команда

`preset.preview {preset?: dict, seeds?: list[int], tile_px?: int}` →
`{status: ok, png_b64, tiles: [{seed, class_name, layer_params}]}`; ошибки — `{status: error, code: invalid |
bad_request, message}`.

- Без `preset` — рендерит файл пресета из своего `preset_path`; файл перечитывается, когда меняется его `rev`
  (`recipe.service.compute_rev`), поэтому `preset.commit` через `scene_source` виден без рестарта.
- `preset` клиента: `base_dir` принудительно = каталог файла пресета; каждый путь картинки после `resolve()` обязан
  лежать в корне репозитория или в каталоге файла пресета, иначе `invalid` с одним и тем же текстом (нет оракула
  существования файла) — `Services.line_sim.core.preview.confine_preset_paths`.
- Размер ответа (L-6, крупные ответы через pipe): 8×160 ≈ 79 КБ JSON (120 КБ с конвертом роутера), ~88 мс;
  16×113 — 100–137 КБ. Спрайты 1200 px — до 1.3 с на превью (держит только поток `layers`). Замеры ревью 1.2a it.2.
- Лимиты: 1..16 seed, `tile_px` 16..256 и бюджет `len(seeds) × tile_px² ≤ 8 × 160²` — иначе `bad_request`.
- Рендер — `Services.line_sim.core.preview.render_preview_grid` (кэш фабрики — одна запись на процесс).

## Конфиг (`pipeline.yaml`)

| Ключ | Обязателен | Что |
|---|---|---|
| `preset_path` | да | тот же, что у `scene_source` (держать равными): `.yaml` пресета слоёв или каталог классов; относительный — от корня репозитория (`Services.line_sim.resolve_repo_path`) |
| `defect_probability` | нет | то же перекрытие, что у `scene_source` (`Services.line_sim.load_scene_preset`) |

## Границы

Не импортирует `Plugins.sim.scene_source` (закреплено тестом): общее правило загрузки пресета — в
`Services/line_sim/core/preset.py`. HTTP-маршрут для браузера — задача 1.2h (`pult_web`).
