# План: Калибровка камера↔робот (Часть 2) — px → реальные мм робота

> Slug: `camera-robot-calibration`. Ветка: `feat/camera-robot-calibration`.
> Часть 1 (сбор датасета) закрыта. Это **независимый** модуль, обогащающий систему: связать пиксель с камеры с реальными мм-координатами робота для будущего пикинга объектов с движущейся ленты.

## Context

Объекты (круги ⌀80–120 мм) едут по ленте: камера снимает их в своей зоне, лента увозит в зону робота, робот пикает. Чтобы робот знал реальную мм-координату детектированного объекта, нужна **разовая ручная калибровка**: по эталонной плате с 5 красными точками построить преобразование «пиксель → мм робота» (гомография) + «дрейф объекта по ленте» (вектор ленты по энкодеру). Результат — переиспользуемый файл `config/calibration/<camera_id>.yaml`. Калибровка **вне** production-pipeline (отдельный рецепт/режим).

Разведка подтвердила: вся device-инфраструктура готова (робот отдаёт `x_mm,y_mm,z_mm,rz_deg,encoder` по `robot_get_telemetry`; лента — `vfd_run/stop/set_freq`; симулятор `python -m Services.robot_comm.server`). **Нового device-кода не нужно** — калибровка = математика + плагин-оркестратор + рецепт + UI поверх существующих команд. Калибровочного кода ещё нет — пишем с нуля.

## Решения владельца (зафиксированы)

1. **Лента разносит зоны** — камера снимает плату при энкодере E0, лента увозит в досягаемость робота. → **обязательна belt-компенсация (P7)**.
2. **Модель — только гомография** (`cv2.findHomography`), без интринсиков/undistort. FOV узкий, плата заполняет кадр.
3. **Эталон — 5 точек** (4 угла + 1 центр), красные на белом. 4 угла задают H, центр — независимая проверка точности (reprojection error).
4. **UI — под-вкладка «Калибровка» внутри Robot** (Services → Robot → QTabWidget), не отдельный сервис.
5. **Масштаб ленты — переиспользовать 1 из 5 точек** (6 касаний всего): 5 точек по разу (гомография) + 1 повторное касание одной точки после прогона ленты (вектор ленты).

## Процедура и математика (P7 — ядро, провалидирована)

Два **ортогональных** измерения:
- **Статика (гомография):** где объект в кадре относительно осей робота.
- **Динамика (вектор ленты):** как объект дрейфует по ленте до момента захвата роботом.

Шаги:
1. **px-замер (зона камеры):** `circle_detector` находит 5 красных точек → `px[5]`; фиксируем `E0`. `order_points`: центр = ближайший к центроиду, 4 угла сортируются по полярному углу (TL/TR/BR/BL).
2. **мм-замер (зона робота):** лента увезла плату; оператор jog'ом наводит инструмент на каждую из 5 точек **по разу** → `mm[i]=(x_mm,y_mm)`, `enc_i`.
3. **масштаб ленты (1 повторное касание):** гоним ленту → повторно касаемся **одной** из 5 точек (`ref_index`) → `R2@E_b`; как `R1@E_a` берём уже снятые `mm[ref], enc_ref` → `mm_per_count=|R2−R1|/(E_b−E_a)`, `belt_dir=unit(R2−R1)`.
4. **belt-компенсация:** `mm_fixed[i] = mm[i] − (enc_i − E0)·mm_per_count·belt_dir` — приводим каждую точку к робот-мировой позиции на момент захвата E0.
5. **гомография:** `H = findHomography(px[4 угла] → mm_fixed[4 угла])` (точное решение); reproj error по центру (5-я точка) — главная проверка; валидация `center < reproj_threshold_mm`.
6. **прод-формула:** объект в `px` при энкодере `E_cap` → `target_mm = H(px) + (E_pick − E_cap)·mm_per_count·belt_dir`.

**Инвариант:** H маппит «пиксель объекта в момент захвата» → «робот-мм в тот же момент»; далее проброс belt-вектором до энкодера пикинга. Знаки в шагах 4 и 6 противоположны и согласованы (H живёт в СК момента E0/E_cap).

## Структура (новый плагин, contract-first — скилл `module-contract`)

```
Plugins/calibration/__init__.py
Plugins/calibration/camera_robot/
  __init__.py, config.py, plugin.py, registers.py
  geometry.py     # ЧИСТАЯ математика P7 (numpy/cv2, без ctx/I/O)
  store.py        # чтение/запись config/calibration/<camera_id>.yaml
  README.md, STATUS.md, tests/{test_geometry, test_store, test_plugin}.py
```
Категория `calibration` (новая, `@register_plugin` принимает свободную строку). Образцы: `Plugins/processing/center_crop/` (скелет), `Plugins/filter/line_filter/geometry.py` (чистый geometry+pytest), `Plugins/io/robot_io/plugin.py` (потоковая модель).

## Фазы

### Ф1 — `geometry.py` + pytest (приоритет №1, полностью оффлайн)
Чистые функции: `belt_vector(r1,r2,enc_a,enc_b)→(mm_per_count, belt_dir)`; `compensate(mm,enc_i,enc0,mm_per_count,belt_dir)→mm_fixed`; `order_points(px[5])→(4 угла, центр)`; `fit_homography(px_corners,mm_fixed_corners)→H(3×3)`; `apply_homography(H,px)→mm`; `reprojection_error(H,px,mm_fixed)→{per_point, center, mean, max}`; `project_to_pick(...)→target_mm`.
H по **4 углам** (точное), центр — только для reproj (независимая проверка).
**pytest на синтетике:** (1) round-trip H_true без ленты; (2) **движущаяся лента** — разные `enc_i`, проверить что `compensate`+`fit_homography` восстанавливают H_true (доказывает знак компенсации); (3) `belt_vector` на известных значениях; (4) `project_to_pick`; (5) вырожденные: `enc_a==enc_b`→ValueError, `|R2−R1|≈0`→ValueError, коллинеарные углы→ValueError, ≠5 точек→ValueError, `w≈0`→ValueError; (6) `order_points` стабилен при перемешанном входе.

### Ф2 — `store.py` (параллельно Ф1)
`calibration_path(camera_id)`, `save_calibration(camera_id, payload)` (через `update_yaml_preserving` из `multiprocess_prototype/recipes/yaml_io.py`, round-trip ruamel), `load_calibration(camera_id)→dict|None` (прод-чтение), `validate_payload(payload)→list[str]`. Путь `config/calibration/<camera_id>.yaml`, `mkdir(parents=True)` при записи. Формат: `camera_id, robot_id, transform=homography, px_to_mm(3×3), encoder{e_capture, mm_per_count, belt_dir_mm}, reproj_error_mm{center,mean,max}, points[{px,mm,enc,role}×5], created_utc`.

### Ф3 — Плагин `camera_robot_calibration`
**registers:** `robot_id, vfd_id, camera_id` (дефолты, переопределяются в `cal_begin`), `expected_points=5`, `reproj_threshold_mm=2.0` (заглушка, тюнится на железе), `point_match_dist_px=20`.
**Порты:** in `detections`(от circle_detector), `frame`, `mask`(opt); out `frame`(pass-through), `overlay`(найденные точки + **номера** — критично для соответствия px[i]↔mm[i]). Детекцию красных делает связка `hsv_mask→circle_detector` в рецепте; плагин только кэширует `detections`.
**Потоковая модель (паттерн `robot_io`, потокобезопасность критична):**
- `process(items)` (приёмный поток): кэширует `_last_detections`/`_last_frame` под `_lock`, пробрасывает кадр + рисует overlay. НЕ блокирует.
- Командные методы (IPC-поток): **НЕ** зовут блокирующий `DeviceHubClient.request` напрямую — кладут действие в `_action_queue` + ack `{"status":"accepted"}`.
- LOOP-worker `_calibration_worker` (`ctx.worker_manager.create_worker`, `ExecutionMode.LOOP`): забирает действие → блокирующий `client.request(...)` → обновляет состояние под `_lock` → публикует прогресс `ctx.state_proxy.set("calibration.state.<camera_id>.progress", {...})`.
- `start()`: создать `DeviceHubClient(ctx)` + worker.
**commands:** `cal_begin{camera_id,robot_id,vfd_id}` | `cal_capture_image` (telemetry→E0, snapshot detections, `order_points`→px[5]+роли; **ошибка если ≠5**: `{status:error, found:N, expected:5}` — не падаем) | `cal_set_robot_point{index}` (telemetry→mm[index],enc_i) ×5 | `cal_belt_run{freq}` / `cal_belt_stop` | `cal_encoder_scale{ref_index}` (повторное касание→R2,E_b; R1/E_a = сохранённые mm[ref]/enc → `belt_vector`) | `cal_compute` (`compensate`→`fit_homography`→`reprojection_error`→валидация порога) | `cal_save` (`store.save_calibration`, отказ если compute не прошёл) | `cal_reset`.
Каждая команда проверяет предусловие фазы (нельзя `cal_compute` до сбора всех точек) → иначе `{status:error}`.
**test_plugin.py:** мок `DeviceHubClient` (telemetry с управляемым encoder) → полный визард на синтетике → H восстановлена, reproj<порог, save вызван; тест «≠5 кругов»→error; тест предусловий; тест `enc_a==enc_b`→error.

### Ф4 — Рецепт `recipes/camera_robot_calibration.yaml`
Топология: `camera_0[hikvision] → roi[roi_crop] → color[color_convert] → mask[hsv_mask красный] → detector[circle_detector input_key=mask] → cal[camera_robot_calibration] → draw[overlay_draw] → display "main"` + `maskview[mask_to_frame] → display "mask"`. Процессы `gui`(protected)+`devices`(device_hub, protected). `devices:` блок (robot_main + vfd_belt) скопировать из `robot_demo.yaml` (для симулятора — host/port 127.0.0.1:5021). Образец топологии — `dataset_circle_capture.yaml`.
**Красная маска (wrap-around H 0..10 ∪ 170..179):** `hsv_mask` сейчас один Hue-диапазон. **Фикс плагина (fix-forward):** соглашение `h_min > h_max` ⇒ wrap (две `inRange` + OR), +тест wrap, не ломая одно-диапазонные рецепты (`h_min≤h_max` = старое поведение). Затрагивает `Plugins/processing/hsv_mask/{plugin.py,registers.py}`.
**`color_convert(mode)`:** включить узел (дефолт `none`); если на дисплее "mask" красное не ловится из-за BGR/RGB-свопа — оператор переключает на `bgr2rgb` (дешёвая страховка).

### Ф5 — Отладка на симуляторе (до железа, обязательно)
`python -m Services.robot_comm.server --host 127.0.0.1 --port 5021` (энкодер растёт ~7/тик); рецепт на 127.0.0.1:5021; smoke без Hikvision (`CapturePlugin`); прогон визарда end-to-end → проверить потоковую модель (нет дедлоков command↔worker), публикацию прогресса в state, формат стора. **Цель — снять риск без железа.**

### Ф6 — UI под-вкладка «Калибровка» в Robot
Рефактор `multiprocess_prototype/frontend/widgets/tabs/services/robot/section.py::_make_device_page` (~стр.126): `inner_widget` страницы устройства = `QTabWidget` с вкладками «Ручное управление» (текущий `RobotControlWidget`) + «Калибровка» (новый виджет). Шапка conn/CRUD общая.
Новые файлы по образцу `vfd/` (MVC): `robot/calibration/{widget,presenter,controller}.py` + tests. Виджет — кнопки шагов (без красоты): «Снять кадр (5 точек)» → «найдено N/5» → «Навести робота на точку 1..5» (подсветка текущей по номеру) → «Прогон ленты + повторное касание (масштаб)» → «Вычислить» (показать reproj center/mean/max + pass/fail) → «Сохранить» (активна при pass) → «Сброс».
**Target команд:** калибровочный плагин в процессе рецепта (напр. `cal`), НЕ в `devices`. Presenter шлёт `cal_*` через `CommandSender.request_command(<процесс с плагином>, cmd, payload)`; `target_process` резолвить из активного рецепта (найти процесс с плагином `camera_robot_calibration`), не хардкодить. Прогресс — `bind_fanout("calibration.state.<camera_id>.progress", cb)`.

### Ф7 — Железо (последняя)
Реальный робот/плата/Hikvision. Тюнинг hsv_mask/circle_detector по дисплею "mask"; подбор `reproj_threshold_mm`; сквозная проверка прод-формулы (`project_to_pick` → робот пикает известную точку).

## Зависимости фаз
`Ф1∥Ф2 → Ф3 → Ф4(+hsv_mask wrap-fix) → Ф5 → Ф6 → Ф7`. Ф6 можно начинать после Ф3 (контракт команд зафиксирован), интегрировать после Ф5. **Приоритет: Ф1→Ф5 (математика+симулятор) полностью до железа.**

## Открытые риски / решения implementer
1. **Порог reproj** — 2.0 мм заглушка, тюн на железе (register-поле).
2. **Соответствие px[i]↔mm[i]** — UI ОБЯЗАН рисовать номера точек overlay'ем; оператор наводит робота строго по номерам (иначе H = мусор при near-zero reproj из-за симметрии).
3. **СК** — H и belt_dir обе в мм-СК робота (telemetry x/y); Z игнорируется (плоскость ленты).
4. **Потокобезопасность** — главный риск дедлока: команды только enqueue+ack, блокирующий IPC только в LOOP-worker, shared-состояние под `_lock`.
5. **int32 wrap энкодера** — для симулятора неактуально; на железе `(enc_i−E0)` с учётом возможного wrap (низкий приоритет).
6. **overlay без join** — плагин несёт frame+overlay в одном item; проверить, что `overlay_draw` рисует из того же item (иначе добавить `inspector: join` в узел draw, как в `dataset_circle_capture.yaml`).
7. **VFD реверс** — лента всегда вперёд, параметр реверса опустить.

## Verification (end-to-end)
1. `pytest Plugins/calibration/camera_robot/tests` — geometry (вкл. движущуюся ленту/belt-компенсацию), store, plugin (мок-визард, ≠5 кругов, предусловия). Зелёные.
2. **Симулятор (до железа):** `python -m Services.robot_comm.server` → рецепт → визард end-to-end → `config/calibration/cam0.yaml` записан, reproj в норме.
3. qt-mcp smoke под-вкладки (`QT_MCP_PROBE=1`, память `feedback_qt_mcp_always_probe`/`feedback_qt_mcp_smoke_verification`).
4. **Железо:** эталон 5 точек → визард (снять → навести 5 точек → масштаб ленты 1 касанием → вычислить → сохранить) → reproj < порога → sanity: `project_to_pick` известной точки совпал с реальной координатой робота.

## Refs / commit-trailers
`Layer: mixed` (plugins+prototype, +фикс framework hsv_mask); `Refs: plans/camera-robot-calibration.md`; `Why:` калибровка px→мм робота для пикинга с движущейся ленты. Решения: гомография по 4 углам (центр=проверка); энкодер отдельным шагом (6 касаний, 1 переиспользованная точка); оператор jog'ом; стор по camera_id; фикс hsv_mask wrap-around (fix-forward).
