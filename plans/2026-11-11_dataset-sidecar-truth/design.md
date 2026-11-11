# design: dataset-sidecar-truth — истина сима и ответ сети в `.json` кадра

Спецификация для исполнителей и слепого тестера. Контракт и задачи — [`plan.md`](plan.md). Область плана — только
кадры сима (решение лида после ревью r1); реальные кадры — §7, задачи DEFERRED.

## 1. Факты, на которых стоит план (проверены по коду 2026-11-11, ветка от `main` 9230d43b0)

| # | Факт | Где |
|---|---|---|
| Ф1 | Сим — отдельное приложение; кадр идёт в прототип по HTTP MJPEG `127.0.0.1:8091`. По MJPEG метаданные не едут | `apps/line_sim/pipeline.yaml:6-10`, `:217-220`; `letter_robot_sim.yaml:138` |
| Ф2 | Решение 2026-09-21 п.4: поле `item["sim_truth"]` отменено, «прототип не знает про сим». Тест держит решение | `plans/line-sim/plan.md:228-231`; `Plugins/sim/scene_source/tests/test_scene_source_hazards.py:408-417` |
| Ф3 | `render()` возвращает паспорта без координат; плагин их выбрасывает. `sim.objects` — только активные объекты | `scene_compositor.py:111-145`; `scene_source/plugin.py:490`, `:1114-1123` |
| Ф4 | Сим уже сводит задание робота с объектом: `match_job(passports, JobDone(x_mm, y_mm, ecap), geometry)` — ближайший паспорт | `Services/line_sim/core/matching.py:98-120`, `:160-199`; `scene_source/plugin.py:274`, `:1046-1064` |
| Ф5 | В `recog`: `center_crop` → `pixel_to_robot` (`pick_xy` = `{x_mm, y_mm}`) → `ml_inference`. `e_capture` `pixel_to_robot` не пишет | `letter_robot_sim.yaml:249-296`; `pixel_to_robot/plugin.py:168`; `word_layout/plugin.py:239` |
| Ф6 | `ml_inference` рисует подпись в `frame` только при `draw_overlay` и непустых предсказаниях; без модели — item без рисования; в рецепте сима `draw_overlay: true` (draw-universal 3.1 ставит `false`) | `ml_inference/plugin/plugin.py:172-173`, `:202-209`; `letter_robot_sim.yaml:291` |
| Ф7 | Симметрия угла — по классу top-1 из карты модели; в предсказание не попадает; `model` в item нет | `ml_inference/engine.py:123-141`, `:161-168` |
| Ф8 | `frame_saver` пишет в `.json` только `item[sidecar_key]` + `file`/`width`/`height`/`saved_ts`; `saved_ts = time.time()` в момент записи | `frame_saver/plugin.py:241-251`, `:265-293` |
| Ф9 | Часы `timestamp` источника прототипа — `time.monotonic()`: с `time.time()` сима не сравнимы | `Plugins/sources/camera_service/plugin.py:183` |
| Ф10 | Конвенция угла сим ↔ сеть совпадает (против часовой, 0 — буква прямо): медиана Δ +2,0…+2,4°, инверсии нет; 7 из 15 дисков вне ±5° | `docs/reports/2026-11-10_word-layout_P4.md:15` |

## 2. Схема (DS-В1: журнал истины в симе + сведение офлайн)

```
сим (apps/line_sim)                       прототип (letter_robot_sim)
scene_source ── журнал JSONL ──┐          center_crop → pixel_to_robot → ml_inference → frame_saver
  header: t_wall, geometry     │                                                       │ кадр.png + кадр.json
  spawn:  passport.to_dict()   │                                                       │ (source, predictions, pick_xy, model_id)
  enc:    t_wall, encoder      │                                                       ▼
                               └────► join_frame_truth (CLI, офлайн) ──► кадр.json += truth, pred, delta, hard
```

- Прототип про сим не знает; `source` задаёт рецепт. Сим кадры не пишет: обучающий кадр — тот, что видела сеть.
- Ключ сведения — K2: `ecap` — энкодер сима, интерполированный по записям `enc` на момент `saved_ts − offset`;
  `offset` (мс, со знаком) — медиана задержки «кадр сима → запись», меряет Task 0.1, флаг `--time-offset-ms`.
  K1 (`e_capture` из item) в план не входит: вопрос 0.1 только меряет, есть ли ключ; добавить K1 — поправкой.
- `match_job` берёт ближайший паспорт: сдвиг ключа ровно на шаг (164 мм ≈ 1,6 с) даёт невязку ≈ 0 и чужую букву.
  Поэтому невязка не доказывает метку — оракул в приёмке 2.3: доля `truth.class == pred.class` среди ответивших.

## 3. Журнал истины (`scene_source`, Task 1.1b)

Конфиг: `truth_journal_dir: ""` (пусто — выключено, ноль операций с файлом на кадре), `truth_journal_enc_hz: 10.0`.
Файл `truth_<%Y%m%d_%H%M%S>_<pid>.jsonl`, создаётся в `configure()`. Одна запись — одна строка, `flush()` после каждой.

| `kind` | Когда | Поля |
|---|---|---|
| `header` | первая строка | `schema: 1`, `t_wall`, `px_per_mm`, `geometry` — dict, ушедший в `BeltGeometry.from_dict` (`plugin.py:274`), `camera_id` |
| `spawn` | на каждом `on_spawn` в `_update_truth_belt` (`plugin.py:1125-1140`) | `t_wall`, `encoder`, `passport` — `passport.to_dict()` |
| `enc` | в `produce()`, когда с прошлой `enc` прошло ≥ `1 / truth_journal_enc_hz` | `t_wall`, `encoder` |

`t_wall` — `time.time()` через шов `self._wall`. Ошибка записи — `health.report_error(throttle=30)`, кадр выдаётся
дальше. В item ничего не добавляется (Ф2).

## 4. `.json` кадра

**`frame_saver` (Task 1.1a).** Существующие ключи не меняются. Регистры: `sidecar_keys: str = ""` — ключи верхнего
уровня item через запятую, копируются под своим именем; `sidecar_source: Literal["", "synthetic", "real"] = ""` —
пишется как `source`, пусто — ключа нет. Слияние: `{**payload, **extras_без_коллизий, "source", "file", "width",
"height", "saved_ts"}`; ключ, занятый в `payload`, пропускается (одна строка `log_warning` за жизнь узла). `frame` и
значение `sidecar_key` в `sidecar_keys` — `ValueError` в `configure()`. Значения extras проходят рекурсивную
конвертацию по `dict`/`list`/`tuple`: `np.generic` → `.item()`; `ndarray` на любой глубине — ключ верхнего уровня
пропускается с предупреждением. Без неё `default=str` (`plugin.py:286`) записал бы `np.float32` строкой.

**`join_frame_truth` (Task 1.1c)** дописывает ключи; ключи `frame_saver` не трогает:

| Ключ | Тип | Смысл |
|---|---|---|
| `truth` | dict \| null | `class`, `angle_deg` (по модулю 360), `object_id`, `lateral_px`, `residual_mm`, `ecap` (int, энкодер на момент кадра), `along_mm` (со знаком: проекция `pick − объект(ecap)` на `BELT_UX/UY`, плюс — pick дальше по ходу); null — не найден |
| `pred` | dict \| null | из `predictions[0]`: `class` (= `label`), `class_id`, `confidence`, `below_threshold`, `angle_deg`, `angle_valid`, `angle_mode` (= `angle_symmetry`), `model_id` (из item); null — список пуст |
| `delta_angle_deg` | float \| null | §5 |
| `hard`, `hard_reasons` | bool, list[str] | §6 |
| `truth_join` | dict | `tool: "join_frame_truth"`, `schema: 1`, `status` (`matched` \| `no_object` \| `no_pick` \| `out_of_window` \| `ambiguous_journal`), `journal` (имя файла), `radius_mm`, `time_offset_ms`; без времени запуска — повторный прогон даёт те же байты |

**Выбор журнала.** Окно журнала — `[header.t_wall, t_wall последней enc]`. Кадр (`saved_ts − offset`) относится к
журналу, чьё окно его содержит; ни одного — `out_of_window`, больше одного — `ambiguous_journal`; в обоих случаях
`truth = null`. `object_id` сравниваются только внутри одного журнала.

**Контракт «машинная метка».** Машинная метка обучения — только `truth` от `join_frame_truth`. Инструмент открывает на
запись только `.json` с `source == "synthetic"`; у остальных байты до и после равны. `training_label(sidecar) -> dict |
None` — единственная дверь к машинной метке: `{"class", "angle_deg"}` из `truth`, если `source == "synthetic"` и
`truth_join.status == "matched"`; иначе `None`. Из `pred` не берёт никогда; `truth`, вписанный руками в `.json` с
`source: real`, — тоже `None`. Ручная разметка реальных кадров — другая дверь (§7, DEFERRED).

## 5. Разность угла

Режим — `pred.angle_mode` (Task 2.1; им сеть декодировала угол). `P = 360` для `none`, `180` для `180`; `full`,
`angle_valid = false` или нет режима — `null`. Истина приводится к тому же периоду. `d = (pred - truth) % P; if d > P/2:
d -= P` — диапазон `(-P/2, P/2]`. Флага режима в CLI нет: сведение запускается на парах, записанных после Task 2.1.

## 6. «Трудный кадр» — офлайн

`hard = True`, если истина найдена и есть причина: `no_prediction`, `class_mismatch`, `below_threshold`, `angle`
(`|delta| > --angle-thr`, умолчание 5,0°, DS-В2) — порядок в `hard_reasons` такой. Нет истины — `hard = False`.
В режиме сима узел сохраняет каждый вырез (DS-В1): истина есть только после сведения.

## 7. Реальные кадры — DEFERRED (Task 2.2, 2.4, 3.1, 3.2; отложено до решения владельца: реальные кадры)

`save_when` — путь `get_path` на том же item; `MissingField` → `save_when_missing`; провод `trigger` не годится: он
приходит отдельным item, в `stream` сохраняется последний кадр (`frame_saver/plugin.py:147-148`, `:188-193`).
`min_free_mb` — защита диска. Папки `by_pred/<буква>/<угол>` — для разбора; ручная метка — перенос в `reviewed/<буква>/`.

## 8. Ловушки

- `index_source: frame_id` при fan-out `center_crop` даёт одно имя нескольким вырезам (`frame_saver/plugin.py:213-221`) — в датасете `counter`.
- `max_days > 0` удаляет папки дней (`plugin.py:312-313`, `:334-356`) — в датасете `0`.
- `trigger`-режим сбрасывает буфер при остановке (`plugin.py:138-141`) — для датасета `stream`.
- `spawn_encoder` дробный и зависит от часов (`scene_source/DECISIONS.md:27`) — сравнивать `object_id`, не число.
