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

### 4.1 `frame_saver` (Task 1.1a)

Существующие ключи не меняются. Регистры: `sidecar_keys: str = ""` — ключи верхнего
уровня item через запятую, копируются под своим именем; `sidecar_source: Literal["", "synthetic", "real"] = ""` —
пишется как `source`, пусто — ключа нет. Слияние: `{**payload, **extras_без_коллизий, "source", "file", "width",
"height", "saved_ts"}`; ключ, занятый в `payload`, пропускается (одна строка `log_warning` за жизнь узла). `frame` и
значение `sidecar_key` в `sidecar_keys` — `ValueError` в `configure()`. Значения extras проходят рекурсивную
конвертацию по `dict`/`list`/`tuple`: `np.generic` → `.item()`; `ndarray` на любой глубине — ключ верхнего уровня
пропускается с предупреждением. Без неё `default=str` (`plugin.py:286`) записал бы `np.float32` строкой.

### 4.2 Ключи `join_frame_truth` (Task 1.1c)

`join_frame_truth` дописывает ключи; ключи `frame_saver` не трогает:

| Ключ | Тип | Смысл |
|---|---|---|
| `truth` | dict \| null | `class`, `angle_deg` (по модулю 360), `object_id`, `lateral_px`, `residual_mm`, `ecap` (int, энкодер на момент кадра), `along_mm` (со знаком: проекция `pick − объект(ecap)` на `BELT_UX/UY`, плюс — pick дальше по ходу); null — не найден |
| `pred` | dict \| null | из `predictions[0]`: `class` (= `label`), `class_id`, `confidence`, `below_threshold`, `angle_deg`, `angle_valid`, `angle_mode` (= `angle_symmetry`), `model_id` (из item); null — список пуст |
| `delta_angle_deg` | float \| null | §5 |
| `hard`, `hard_reasons` | bool, list[str] | §6 |
| `truth_join` | dict | `tool: "join_frame_truth"`, `schema: 1`, `status` (`matched` \| `no_object` \| `no_pick` \| `out_of_window` \| `ambiguous_journal`), `journal` (basename файла; `null`, если журнал не выбран: `no_pick`, `out_of_window`, `ambiguous_journal`), `radius_mm`, `time_offset_ms`, `angle_thr` (три флага прогона: по `.json` видно, чем посчитаны `truth` и `hard`); без времени запуска — повторный прогон с теми же флагами даёт те же байты |

### 4.3 Выбор и чтение журнала

**Выбор журнала.** Окно журнала — `[t_wall первой enc, t_wall последней enc]`, границы включены. `header.t_wall` в окно
не входит: между `header` (`Plugins/sim/scene_source/plugin.py:1177-1195`) и первой `enc` (пишется только при
`_world_ready`, `:1232-1233`) лежит время запуска мира, интерполировать там нечем. Кадр (`t = saved_ts − offset/1000`)
относится к журналу, чьё окно его содержит; ни одного (в том числе `t` в `[header.t_wall, первая enc)`) —
`out_of_window`, больше одного — `ambiguous_journal`; в обоих случаях `truth = null`. Журнал без `header`, без `enc`
или с одной `enc` — окно пусто: ни один кадр в него не попадает (`IndexError` исключён). `object_id` сравниваются только
внутри одного журнала.

**Чтение журнала** (`load_journal`; ничего из списка не бросает исключение). `Journal` — frozen dataclass: `name: str`
(basename файла), `header: dict | None`, `passports: dict[str, ObjectPassport]` (по `object_id`), `enc: tuple[tuple[float,
float], ...]` (`(t_wall, encoder)`), `t_from`, `t_to: float | None` (`t_wall` первой и последней `enc`; `None` — окно
пусто).
- Побеждает первый `header` (режим `"a"` даёт повторные, `plugin.py:1183`); следующие игнорируются. `header` без
  `px_per_mm > 0` или с `geometry`, которую не принимает `BeltGeometry.from_dict`, — как отсутствующий.
- `spawn` с `encoder: null`, без `passport` или с паспортом, который не разобрал `ObjectPassport.from_dict`
  (`spawn_encoder: null` даёт `TypeError`), — пропуск, не считается. Повтор `object_id` в файле — остаётся первый.
- `enc` с нечисловым или неконечным `t_wall`/`encoder` — пропуск. `t_wall` меньше последнего принятого (скачок часов) —
  пропуск, остаётся более ранняя; равный — заменяет предыдущую (остаётся последняя).
- Оборванная последняя строка и нечитаемая строка посередине — игнорируются. Если что-то пропущено, одна строка
  предупреждения в stderr на журнал.

### 4.4 Сведение кадра

`join_sidecar` — только для `source == "synthetic"`:
1. Проверки по порядку. `saved_ts` не конечное число (в том числе `bool`, строка, нет ключа) — `error`. `pick_xy` нет или
   `null` — `no_pick` (журнал не выбирается). `pick_xy` не dict, нет `x_mm`/`y_mm` или они не конечные числа — `error`.
   `predictions` нет/`null`/`[]` — `pred = null`; не список или `predictions[0]` не dict — `error`.
2. `t = saved_ts − time_offset_ms / 1000`; `pick_journal` — `out_of_window` / `ambiguous_journal`.
3. `ecap` — линейная интерполяция по двум соседним `enc` журнала на `t`, затем `int(round(...))` (встроенный `round`);
   дальше везде только это целое.
4. `match_job(journal.passports.values(), JobDone(index=-1, x_mm, y_mm, ecap=ecap, t=t), BeltGeometry.from_dict(header
   ["geometry"]), match_radius_mm=radius_mm, px_per_mm=header["px_per_mm"])` — `Services/line_sim/core/matching.py:160`.
   Все паспорта идут как `active` (`removed` пуст, `dup` недостижим). `matched` — невязка строго меньше радиуса
   (`matching.py:196`).
5. `matched` → `truth`: `class` = `class_name`; `angle_deg` = `passport.angle_deg % 360.0`, и если результат ≥ 360.0
   (`(-1e-17) % 360.0 == 360.0`) — `0.0`; `ecap`; `along_mm` — проекция `pick − object_robot_xy(passport.spawn_encoder,
   ecap, geometry, lateral_px=passport.lateral_px, px_per_mm=header["px_per_mm"])` на `(BELT_UX, BELT_UY)` —
   `Services/line_sim/core/belt.py:10`; без `lateral_px`/`px_per_mm` проекция разошлась бы с невязкой `match_job`.
6. `pred`: восемь ключей всегда — `class`, `class_id`, `confidence`, `below_threshold`, `angle_deg`, `angle_valid`,
   `angle_mode`, `model_id`; отсутствующее в `predictions[0]` (модель без головы угла) — `null`; `model_id` — из
   `sidecar["model_id"]`, нет — `null`. `pred` не зависит от `status`. `angle_valid` не `true` — `delta_angle_deg = null`.
7. Нет истины (`truth = null`): `delta_angle_deg = null`, `hard = false`, `hard_reasons = []`.

### 4.5 CLI и итоговая строка

**CLI** (`main`). Флаги: `--frames DIR`, `--journal FILE` (обязательный, повторяемый), `--radius-mm` (> 0),
`--time-offset-ms` (конечное), `--angle-thr` (> 0, умолчание 5.0). Нарушение или нечитаемый `--journal` — код 2 до первой
записи.
- Обход: `DIR` рекурсивно, `*.json` в порядке сортировки пути. Пара = `.json` + `parent / data["file"]` существует; нет
  картинки (или `file` не строка) — пропуск, в `N` не считается. `.json`, который не разобрать как dict, — `error`, в `N`
  считается. `source != "synthetic"` — в `N` считается, на запись не открывается, байты равны.
- Для `synthetic` все шесть ключей (`truth`, `pred`, `delta_angle_deg`, `hard`, `hard_reasons`, `truth_join`)
  пересчитываются с нуля, а не дополняются: повтор с другими флагами не оставляет старую машинную метку (радиус 20 → 5:
  `matched` → `truth: null`, `hard: false`, `hard_reasons: []`). Остальные ключи файла не трогаются.
- Запись: `json.dumps(..., ensure_ascii=False, indent=2)` как в `frame_saver` (`Plugins/io/frame_saver/plugin.py:366`); tmp
  `<имя>.json.<pid>.tmp` (суффикс `.tmp`: обход не примет его за вход, два CLI не делят имя), `replace`, при сбое
  `unlink(missing_ok=True)`. `frame_saver` при входе в папку удаляет все `*.tmp` (`:389`, `:406-412`) — CLI на живом
  каталоге может потерять tmp: это `error` файла, прежний `.json` цел. Потеря обновления при живой перезаписи того же
  имени возможна только при `index_source: frame_id` (§8) — принято.
- Ошибка файла (`error`): любое исключение разбора, `ValueError` из `match_job`/`object_robot_xy` (`radius <= 0`,
  `lateral_px != 0` без `frame_down`), `OSError` записи. Одна строка в stderr, файл не тронут, счёт `E`; остальные файлы
  идут дальше. Статус `error` в `.json` не пишется. Код выхода 1, если `E > 0`, иначе 0.

**Итоговая строка** — одна строка в stdout, порядок и слова фиксированы:
`пар N, synthetic S, matched M, no_object O, no_pick P, out_of_window W, ambiguous A, error E, hard H, медиана |Δ| D°, медиана along_mm L мм, предложение --time-offset-ms X`.
Счётчики — целые; `S = M + O + P + W + A` (`E` в `S` не входит); `H` — файлы прогона с `hard = true`. `D`, `L`, `X` — одна
цифра после точки (`2.0`, `-1.7`, `103.8`; `-0.0` печатается `0.0`). `D` — медиана `|delta_angle_deg|` по файлам, где
дельта не `null`; `L` — медиана `along_mm` по `matched`; медиана чётного ряда — среднее двух средних. Нет значения —
токен `n/a` без единицы: `медиана |Δ| n/a`, `медиана along_mm n/a`, `предложение --time-offset-ms n/a`.
`X = offset − L / v × 1000` (мм / (мм/с) → с → мс); `v` журнала = `(enc[-1] − enc[0]) × FACTOR_MM / (t_to − t_from)`
(`FACTOR_MM` — `Services/line_sim/core/belt.py:10`), `v` для `X` — среднее по журналам (по одному разу), которые
использовали `matched`-файлы. `v <= 0` или `M == 0` — `L` и `X` — `n/a`, без исключения. `X` — **диагностика**, не
поправка: в нём смешаны задержка и постоянный сдвиг вдоль хода (~1,7 мм по 0.1, на ленте 20 мм/с это ~84 мс).

### 4.6 Тесты автора (hazards, Task 1.1c)

Файл `Services/line_sim/tests/test_join_frame_truth_hazards.py`; на каждый пункт — тест с литералами:
- сбой `replace` (подмена) — прежний `.json` цел, `<имя>.json.<pid>.tmp` удалён, `E = 1`;
- одинаковый `object_id` в двух журналах не путается (`truth_join.journal`, `truth.class` разные);
- журнал с двумя `header`, `spawn` без `encoder`/`passport`, `spawn_encoder: null`, немонотонными и равными `t_wall`,
  оборванной последней строкой и мусором посередине — без исключения, по правилам §4.3;
- журнал без `header`, без `enc`, с одной `enc` — все кадры `out_of_window`, без `IndexError`;
- `v == 0` (две `enc` с равным `encoder`) и `M == 0` — `n/a`, без исключения и без `median([])`;
- `error` (§4.5): нет/нечисловой `saved_ts`, `pick_xy` не dict, битый JSON, `ValueError` из `match_job`
  (`lateral_px != 0` без `frame_down`) — байты файла целы, соседний файл обработан, код выхода 1;
- argparse: радиус ≤ 0, offset `nan`/`inf`, `--angle-thr` ≤ 0 — код 2, ни одной записи;
- повтор с другими флагами (радиус 20 → 5; `--angle-thr` 5 → 20): `truth: null`, `hard: false`, `hard_reasons: []`,
  `truth_join` с новыми значениями флагов — старая метка не переживает;
- `truth.angle_deg`: `-1e-17` → `0.0`; `360.0` → `0.0`; `-30.0` → `330.0`; `390.0` → `30.0`;
- `lateral_px != 0` при `frame_down` в `geometry`: `matched`, `along_mm` верен (`px_per_mm` и `lateral_px` переданы).

### 4.7 Машинная метка

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
