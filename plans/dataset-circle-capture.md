# План: Сбор датасета (детекция круга + crop) и hand-eye калибровка камера↔робот

> Slug при реализации: `dataset-circle-capture` (Часть 1) и `camera-robot-calibration` (Часть 2).
> Это два независимых модуля в одном файле. **Часть 1 не зависит от Части 2** — датасет можно собирать в пикселях сразу, калибровка обогащает систему позже (px→мм робота для будущего пикинга и точного размера crop в мм).
> Dual-save после approve: `plans/dataset-circle-capture.md` и `plans/camera-robot-calibration.md`.

## Context

Цель — **собрать датасет для обучения нейросети**: камера Hikvision снимает белые круги (⌀80–120 мм) на синем фоне; когда круг доезжает до рабочей позиции, зафиксировать центр и вырезать вокруг него квадрат, сохранив картинку. Первый этап — научиться **ловить объект** и накапливать фото (Часть 1). Параллельно нужна **калибровка камера↔робот↔энкодер** по эталону из 5 точек, чтобы связать пиксели с реальными мм робота и пробегом ленты (Часть 2).

Разведка: устройства (робот Delta `delta_universal3`, энкодер ленты, ПЧ конвейера) **уже реализованы** — робот в реальном времени читает энкодер и отдаёт координаты по запросу. Pipeline захвата на 5/6 шагов собирается готовыми плагинами; не хватает одного плагина crop (Часть 1) и калибровочного плагина-оркестратора (Часть 2).

---

# ЧАСТЬ 1 — Pipeline сбора датасета (делать первой)

## Готовые плагины (переиспользуем, не трогаем)

| Шаг | Плагин | Путь | Ключевое |
|-----|--------|------|----------|
| Камера | `hikvision` | [`Services/hikvision_camera/plugin/plugin.py`](Services/hikvision_camera/plugin/plugin.py) | `frame` (BGR), `seq_id` |
| Crop ROI | `region_split` | [`Plugins/processing/region_split/plugin.py`](Plugins/processing/region_split/plugin.py) | один регион по px `x,y,width,height` |
| Детекция кругов | `circle_detector` | [`Plugins/processing/circle_detector/plugin.py`](Plugins/processing/circle_detector/plugin.py) | `min/max_radius` (px) → `detections=[{center:[x,y],radius:r}]` |
| Линейный фильтр | `line_filter` | [`Plugins/filter/line_filter/plugin.py`](Plugins/filter/line_filter/plugin.py) | `mode=enter_zone`, трекинг центров → `filtered`+`overlay` |
| Визуализация | `overlay_draw` | `Plugins/render/overlay_draw/` | Join-рендер линии + точек |
| Сохранение | `frame_saver` | [`Plugins/io/frame_saver/plugin.py`](Plugins/io/frame_saver/plugin.py) | папки по дате, атомарная запись, `save_mode=stream` |

> Отдельного плагина `crop` нет — `region_split` режет по **статичным** px-координатам. Для шага «квадрат вокруг найденного центра» нужен **динамический** crop → пишем `center_crop`.

## Новый плагин `center_crop` (единственный недостающий кусок)
**Путь:** `Plugins/processing/center_crop/` (`plugin.py`, `registers.py`, `config.py`, `README.md`, `STATUS.md`, `tests/`). Generic, работает в пикселях (контракт-first — skill `module-contract`).

- **inputs:** `frame` (`image/bgr`), `trigger_in` (`dict` от `line_filter`, несёт `filtered`)
- **registers:** `side_px: int = 200` (сторона квадрата), `drop_partial: bool = False`, `pad_if_oob: bool = True`
- **outputs:** `frame` (вырезанный квадрат) + **sidecar-метаданные** (P3, см. ниже). **Fan-out:** один item на каждый центр из `filtered`; пустой `filtered` → 0 выходов. Прокидывает `seq_id` + суб-индекс.
- **Логика:** читает `item["filtered"]` (формат координат — проверить в `line_filter/plugin.py`, вероятно `xy`/`center`), вырезает квадрат `side_px` вокруг каждого центра из `item["frame"]` с clamp/pad.

### Топология: предпочесть одно-процессную цепочку (P2, «меньше слоёв»)
Базовый вариант — Join (как `draw` в `line_filter_inspect.yaml`): `inspector: {mode: join, inputs: [frame, overlay], primary: frame}`.
**Но Join несёт риск (P1):** требует, чтобы `line_filter` эмитил overlay **на каждый кадр** (иначе timeout → дроп). **Перед реализацией верифицировать этот инвариант.**
**Рекомендуемый вариант (fewer layers):** прокинуть `frame` сквозь `line_filter` (fix-forward: сейчас он возвращает dict без `frame`) и собрать `roi→circle_detector→line_filter→center_crop→saver` **одним синхронным процессом без Join/seq_id-корреляции** — надёжнее и проще. Решение — implementer после проверки P1.

### Sidecar-метаданные (P3 — обязательно для датасета)
Только cropped-картинка для обучения недостаточна. На каждый сохранённый кадр писать `.json` рядом: `center_px`, `radius_px`, `seq_id`, `timestamp`, `frame_id`, `encoder` (если доступен из item), `recipe`. Реализация: `center_crop` кладёт метаданные в item → лёгкий sidecar-sink или расширение `frame_saver` (проверить, поддерживает ли он sidecar; если нет — отдельный маленький sink). Без этого датасет не привязать/не разметить.

## Рецепт `multiprocess_prototype/recipes/dataset_circle_capture.yaml`
Зеркалит структуру [`line_filter_inspect.yaml`](multiprocess_prototype/recipes/line_filter_inspect.yaml):

```
camera_0 (hikvision) ─frame→ roi (region_split, 1 регион)
  roi ─region→ detector (circle_detector, min/max_radius)
    detector ─frame→ crop (center_crop, Join) и ─frame→ draw (overlay_draw, Join)
    detector ─detections→ line (line_filter, mode=enter_zone)
      line ─overlay→ crop и ─overlay→ draw
  crop ─frame→ saver (frame_saver, save_mode=stream, save_every_n=1, format=png)
  draw ─frame→ display              ← визуальный контроль/тюнинг
```

`frame_saver`: `output_dir: data/dataset/circles`, `subfolder_by_date: true`, `image_format: png`, `save_mode: stream`, `save_every_n: 1` (crop эмитится только по триггеру → сохраняется каждый пойманный объект).

## Единицы (Часть 1)
Пока калибровки (Часть 2) нет — `min/max_radius` и `side_px` подбираются **визуально в пикселях** по live-дисплею. После Части 2 размер crop в мм считается из локального масштаба гомографии (`side_px = side_mm / mm_per_pixel`), но это не блокирует сбор фото сейчас.

---

# ЧАСТЬ 2 — Hand-eye калибровка камера↔робот↔энкодер

## Что уже есть (по подтверждению владельца + разведке)
- **Координаты робота по запросу:** `DeviceHubClient(ctx).request("robot_get_telemetry", {"device_id": ...})` → `{telemetry:{x_mm,y_mm,z_mm,rz_deg,...}, encoder, free}`. Файлы: [`Plugins/hub/device_hub/client.py`](Plugins/hub/device_hub/client.py), [`Services/device_hub/drivers/robot_driver.py`](Services/device_hub/drivers/robot_driver.py), [`Services/robot_comm/core/client.py`](Services/robot_comm/core/client.py).
- **Энкодер ленты в реальном времени:** регистр `encoder` (int32 counts, 0x1112), приходит в той же телеметрии.
- **Управление лентой (ПЧ):** `vfd_run {device_id, freq_hz}`, `vfd_stop`, `vfd_set_freq` на device `kind: vfd`.
- **Универсальная адресация:** хаб `devices`, обращение по `device_id`+команда (`robot_*`/`vfd_*`) поверх `BaseDeviceDriver`/`kind` — **не привязано к Delta/Hikvision**.
- **Команды плагина из GUI:** паттерн `commands = {...}` (как `set_hough_params`), методы возвращают dict.
- **Запись в рецепт:** `update_yaml_preserving()` в [`recipes/yaml_io.py`](multiprocess_prototype/recipes/yaml_io.py) — round-trip с сохранением комментариев.

→ Нового device-кода **не требуется**. Калибровка = оркестрация существующих команд + математика + запись + GUI.

## Решения владельца
0. **Калибровка — разовая РУЧНАЯ процедура ВНЕ production-pipeline** (отдельный режим/рецепт `camera_robot_calibration`, запускается только на время калибровки; результат → `config/calibration/<camera_id>.yaml`, далее переиспользуется). НЕ часть рабочего датасет-pipeline.
1. Снятие точек: **оператор наводит инструмент робота вручную (jog)**, плагин читает `robot_get_telemetry` (x_mm,y_mm) + энкодер.
2. Масштаб энкодера: **отдельный шаг** — лента стоит в зоне робота; робот касается одной реперной точки дважды при разных значениях энкодера → `mm_per_count` + направление ленты.
3. Преобразование px→мм: **гомография** (4 угла задают, центральная точка — проверка точности).

## Новый плагин `camera_robot_calibration` (универсальный)
**Путь:** `Plugins/calibration/camera_robot/` (`plugin.py`, `registers.py`, `geometry.py` — чистая математика, `config.py`, `README.md`, `STATUS.md`, `tests/`). Категория `calibration`/`utility`. Сидит в pipeline после `circle_detector` (читает `detections`), общается с `devices` через `DeviceHubClient`. Универсален: только `device_id` робота/ПЧ + generic команды.

**Эталон:** плата из ≥5 круглых точек — 4 по углам + 1 в центре (P9: поддержать **N≥5**, напр. сетку 3×3, для least-squares и устойчивости к промаху оператора; центр — проверка точности). Центральная ставится на линию `line_filter` (забор).

> **🔴 P7 (математика, belt-компенсация — критично).** px-точки снимаются у камеры при энкодере `E0`, а мм-координаты робота — в зоне робота, куда лента увезла эталон. Поэтому `mm[i] = H(px[i]) + (E1−E0)·belt_vec`. **Нельзя** делать наивный `findHomography(px→mm)` — постоянный сдвиг ленты запечётся в H и в проде всё поедет. Правильный порядок: (1) сначала шаг энкодера → `mm_per_count`, `belt_dir`; (2) **вычесть пробег ленты** из каждой `mm[i]`, приведя к belt-fixed кадру при `E0`; (3) только потом фитить H по очищенным точкам. Это ядро Части 2 — оформить мини-ADR до кода.

> **🔴 P8 (хранилище).** Калибровка привязана к физической паре камера+робот, **не к рецепту**. Хранить в **центральном сторе** `config/calibration/<camera_id>.yaml`, рецепты ссылаются по `camera_id`. НЕ инлайнить в каждый рецепт (расползётся копиями).

> **🟠 P10 (симулятор).** Математику (P7) и оркестрацию плагина отладить против симулятора робота (`python -m Services.robot_comm.server`) **до** реального конвейера — снимает основной риск без занятого железа. Обязательный этап.

> **🟡 P12 (допущения — прописать явно):** TCP робота корректен (касание = центр точки); 4 угла не коллинеарны/обусловлены; обработка случая «детектор нашёл ≠ N кругов» (просьба перенастроить, без падения).

**Командный API (state machine визарда):**
| Команда | Действие |
|---------|----------|
| `cal_begin {camera_id, robot_id, vfd_id}` | старт сессии, сброс точек |
| `cal_capture_image` | взять кэш `detections` (ждём 5 кругов), классифицировать центр (ближайший к линии) + упорядочить 4 угла (TL/TR/BR/BL по углу), сохранить `px[5]`; записать `E0` |
| `cal_set_robot_point {index}` | оператор навёл инструмент на точку #index → читаем telemetry → `mm[index]` + энкодер |
| `cal_encoder_scale_mark {ref_index}` | зафиксировать репер R1+E1 (робот на реперной точке) |
| `cal_encoder_scale_finish {ref_index}` | после прогона ленты — повторное касание → R2+E2 → `mm_per_count=|R2−R1|/(E2−E1)`, `belt_dir=unit(R2−R1)` |
| `cal_belt_run {freq}` / `cal_belt_stop` | обёртки `vfd_run`/`vfd_stop` |
| `cal_compute` | `cv2.findHomography(px[5]→mm[5])`, reprojection error, валидация < порога |
| `cal_save` | записать блок калибровки в рецепт по `camera_id` через `update_yaml_preserving` |
| `cal_reset` | сброс |

**Потокобезопасность:** `DeviceHubClient.request` (блокирующий) — **только из worker-потока**, не из приёмного цикла/`process()`. Команды складывают действие в очередь воркера, результат публикуется в state (паттерн `_forwarder_loop` из [`Plugins/io/robot_io/plugin.py`](Plugins/io/robot_io/plugin.py)). `process()` лишь кэширует последний `item["detections"]`.

**Формат таблицы** — центральный стор `config/calibration/<camera_id>.yaml` (P8), рецепт ссылается по `camera_id`:
```yaml
camera_id: camera_0
robot_id: robot_main
transform: homography
px_to_mm: [[...],[...],[...]]       # 3×3, фит по belt-compensated точкам (P7)
encoder: {e_capture: <E0>, mm_per_count: <float>, belt_dir_mm: [dx, dy]}
reproj_error_mm: <float>
points: [{px:[x,y], mm:[X,Y], enc:E}, ... xN]   # сырьё для аудита (N≥5)
created_utc: <iso>
```

## Подзадачи Части 2 (реализовывать отдельной веткой `feat/camera-robot-calibration`)
- **2A. Математика** (`geometry.py` + тесты): шаг энкодера (`mm_per_count`/`belt_dir` из двух касаний) → **belt-компенсация точек (P7)** → гомография по N≥5 точкам (least-squares) → reprojection error → локальный `mm_per_pixel`. Чистые функции, pytest на синтетике (включая кейс с движущейся лентой). Предварить **мини-ADR на математику**.
- **2B. Плагин-оркестратор**: командный API выше, `DeviceHubClient` из воркера, кэш detections, публикация прогресса/ошибок в state.
- **2C. Запись в рецепт**: блок `calibration.<camera_id>` через `update_yaml_preserving`.
- **2C-стор. Хранилище** (P8): чтение/запись `config/calibration/<camera_id>.yaml`; рецепты ссылаются по `camera_id`.
- **2D. GUI-визард** (P11 — начать с минимума): командная панель с кнопками шагов (без красоты), по образцу device-виджетов, напр. [`.../tabs/services/vfd/controller.py`](multiprocess_prototype/frontend/widgets/tabs/services/vfd/controller.py): «Снять кадр (N точек)» → «Навести робота на точку 1..N» → «Масштаб энкодера» → «Вычислить (показать ошибку)» → «Сохранить» + кнопки ленты. Красивый UX — итерациями потом.
- **2E. Рецепт калибровки** `recipes/camera_robot_calibration.yaml`: `hikvision → region_split → circle_detector(draw=on) → camera_robot_calibration → overlay_draw → display` + `devices:` (robot + vfd).
- **2-sim. Отладка на симуляторе** (P10) — до железа.

## Открытые детали (решит implementer)
- Формат координат в `line_filter.filtered` / `circle_detector.detections` (`xy` vs `center`) — посмотреть в плагинах.
- Точная классификация «центр vs углы» при 5 кругах (центр = ближайший к линии забора; углы — по полярному углу относительно центроида).
- Порог reprojection error для «калибровка принята» (параметр register, дефолт напр. 1.0 мм).
- Семантика портов при wiring `line_filter.overlay` — повторить рабочий паттерн из `line_filter_inspect.yaml`.

---

## Verification (end-to-end)

**Часть 1:**
1. `python multiprocess_prototype/run.py dataset_circle_capture` → провести круг через зону.
2. qt-mcp smoke (память `feedback_qt_mcp_smoke_verification`): `qt_snapshot` дисплея — круги детектятся, линия рисуется, триггер срабатывает; файлы появляются в `data/dataset/circles/<YYYY-MM-DD>/`, по содержимому — квадрат `side_px` вокруг центра.
3. `pytest Plugins/processing/center_crop/tests` — зелёные (clamp/pad/drop_partial, fan-out, пустой filtered).

**Часть 2:**
1. `pytest Plugins/calibration/camera_robot/tests` — гомография/энкодер на синтетике, **в т.ч. кейс с движущейся лентой (belt-компенсация, P7)**, reprojection error.
2. **Сначала симулятор (P10):** `python -m Services.robot_comm.server` → прогнать весь визард против симулятора, проверить математику.
3. На железе: эталон N точек → визард (снять кадр → навести робота на N точек → шаг энкодера → вычислить) → reprojection error в норме → файл `config/calibration/camera_0.yaml` записан (P8).
4. Sanity: применить `px_to_mm` (+ belt-компенсацию) к центру известной точки → сравнить с реальной координатой робота.

## Refs / commit-trailers
- Часть 1: `Why:` сбор датасета; `Layer: mixed` (plugins+prototype); `Refs: plans/dataset-circle-capture.md`.
- Часть 2: `Layer: mixed`; `Refs: plans/camera-robot-calibration.md`.
- Решения: crop из ROI; триггер `enter_zone`; калибровка — гомография по 5 точкам, энкодер отдельным шагом, оператор jog'ом наводит робота.
