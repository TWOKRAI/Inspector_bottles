# Фаза 4 — эффекты в симе + поля в пульте

Родитель: [plan.md](plan.md). Итог фазы — то, что владелец назвал «модернизировать шумом, светом и т.п.»: шум, блик,
яркость/контраст, гамма, размытие, виньетка, цветовая температура (весь реестр `EFFECTS` из 3.3) включаются на кадре
сима и на отдельном слое объекта — из конфига и из пульта; генератор обучения читает тот же блок конфига.

Порядок исполнения — как в [phase-1.md](phase-1.md). Новых эффектов фаза не изобретает: «свет» = `glare`, `vignette`,
`brightness_contrast`, `gamma`, `color_temperature`. Новый эффект, если понадобится, — функция + строка в `EFFECTS` (README 3.3).

---

### Task 4.1 — эффекты сцены `scene_effects` в `scene_source` и в `SimCropGenerator`

- **Статус:** [PENDING] (зависит от 2.2, 3.3) · **Level:** Middle+ (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (новый ключ конфига плагина и поле `SimCropConfig`)
- **CHAIN:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** список эффектов на весь кадр после композиции объектов — в сим-кадре и в обучающем вырезе, один YAML-блок.

**Files:**
1. `Services/layer_render/effects.py` — `effects_from_config(items) -> list[EffectSpec]` (один парсер для обоих)
2. `Plugins/sim/scene_source/plugin.py` — ключ `scene_effects`, свой поток `np.random.default_rng([seed, 1])`, применение в `produce()` после `render()`
3. `Services/line_sim/core/sim_crop.py` — поле `scene_effects` (вместо `augment` 2.2; `augment` остаётся, переводится `augment_config_to_effects`; оба сразу → `ValueError`)
4. `apps/line_sim/pipeline.yaml` — закомментированный пример блока
5. `Plugins/sim/scene_source/README.md`
- тесты: `Plugins/sim/scene_source/tests/test_scene_effects_*.py`, `Services/line_sim/tests/test_sim_crop_effects.py`

**DESIGN:** схема блока
```yaml
scene_effects:            # по порядку, сверху вниз
  - {name: noise, prob: 1.0, std: [2, 6]}
  - {name: glare, prob: 0.3, radius_frac: [0.1, 0.3], intensity: [0.2, 0.5]}
```
Параметры — те же имена и диапазоны, что поля `AugmentConfig` соответствующего эффекта. Поток эффектов сцены отдельный
от потока спавна: включение/выключение эффектов не сдвигает объекты на ленте. Эффекты — в RGB-кадре до перевода в BGR.

**Acceptance:**
- [ ] Без ключа: `test_acceptance_lateral_offset_plugin.py:492-493` — зелёный без правки; поток `self._rng` после 12 кадров — тот же.
- [ ] С `scene_effects: [noise]`: паспорта 12 кадров побайтно равны прогону без эффектов (объекты не сдвинулись), кадры — отличаются.
- [ ] Один и тот же блок в `scene_source` и в `SimCropConfig` разбирается в равные списки `EffectSpec`.
- [ ] Кривой элемент (нет `name`, неизвестное имя, `prob` вне [0,1]) → `ValueError` в `configure()` с индексом элемента.
- [ ] Замер: медиана `produce()` на 1440×1080 без эффектов и с `[noise, gaussian_blur]`, 200 кадров — оба числа в отчёте;
      если с эффектами медиана > 1/fps стенда — это находка для лида, не «оптимизация по ходу».

**Out of scope:** пульт (4.4), запись в YAML из пульта, эффекты на ветке `_background_only_frame`.

---

### Task 4.2 — эффекты «материала» слоя `LayerSpec.effects`

- **Статус:** [PENDING] (зависит от 3.2, 3.3) · **Level:** Senior (Opus 5.5) · **Assignee:** tester → teamlead → инъекции лида → reviewer
- **Module contract:** public-api-change (новое необязательное поле `LayerSpec`)
- **CHAIN:** `tester`(RED) → `teamlead`(GREEN) → `reviewer`

**Goal:** у слоя объекта — свой список эффектов (шум/зерно краски, блик плёнки, размытие края), разыгрывается один раз
при создании объекта из sub-rng слоя; альфа слоя не меняется.

**Files:**
1. `Services/layer_render/layers.py` — поле `effects: list[EffectSpec] = []`, применение в `compose_layers` после трансформа слоя
2. `Services/layer_render/effects.py` — `apply_effects_rgba(sprite, specs, rng)`: эффекты по RGB, альфа нетронута
3. `Services/line_sim/presets/README.md` — поле и пример
- тесты: `Services/layer_render/tests/test_layer_effects_*.py`

**DESIGN:** розыгрыш эффектов слоя идёт из `sub` этого слоя **после** всех нынешних розыгрышей слоя
(`augment`/`defect`) — пустой список = ноль розыгрышей, и соседние слои не сдвигаются (каждый на своём `rng.spawn`).
YAML без ключа `effects` и `to_dict` без пустого `effects` — пресеты на диске и `preset.commit` пульта не меняются.

**Acceptance:**
- [ ] `test_hazards_1_3h_layout.py:40-44` (15 отпечатков) — зелёный без правки.
- [ ] Слой с `effects: [noise prob 1]`: альфа итогового RGBA побайтно равна альфе без эффекта; RGB отличается только там, где альфа слоя > 0.
- [ ] Эффект на слое 1 из 3 не меняет `layer_params` слоёв 0 и 2 (тот же seed).
- [ ] `ScenePreset` YAML round-trip с `effects` — равен; без `effects` — словарь без ключа `effects`.
- [ ] `render()` объекта на 10 кадрах — один и тот же массив (эффекты не разыгрываются на кадре).

**Out of scope:** редактор (4.3), эффекты на слоях фона.

---

### Task 4.3 — поля эффектов слоя в редакторе пресета `pult_web` + каталог эффектов

- **Статус:** [PENDING] (зависит от 4.2) · **Level:** Middle+ (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (новая команда `layer_preview`)
- **CHAIN:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** в свойствах слоя редактора — список эффектов: добавить (выпадающий список имён), параметры-диапазоны,
вероятность, удалить, порядок; сетка образцов превью показывает эффект без запуска стенда.

**Files:**
1. `Services/layer_render/effects.py` — `EFFECT_PARAMS: dict[str, dict]` (имя → параметры по умолчанию; поля строятся из данных)
2. `Plugins/sim/layer_preview/plugin.py` — команда `effects.catalog` → `{name: params}`
3. `Plugins/sim/pult_web/plugin.py` — поля эффектов в свойствах слоя (HTML/JS), правка уходит существующим `preset.commit`
4. `Plugins/sim/layer_preview/README.md`, `Plugins/sim/pult_web/README.md`
- тесты: `Plugins/sim/layer_preview/tests/test_effects_catalog.py`, `Plugins/sim/pult_web/tests/test_layer_effects_fields.py`

**Acceptance:**
- [ ] `effects.catalog` отдаёт все имена `EFFECTS`; каждый набор параметров проходит `EffectSpec` без правок.
- [ ] Тест на настоящих объектах (не фейк): правка эффекта в пульте → `preset.commit` → YAML на диске содержит `effects` →
      `preset.preview` возвращает образцы, отличные от прогона без эффекта.
- [ ] Перемещение слоя мышью (`offset_px`, `pult_web/plugin.py:1126-1183`) после добавления эффекта — работает как до задачи.

**Out of scope:** эффекты сцены (4.4), новые эффекты.

---

### Task 4.4 — панель эффектов сцены в `pult_web` (живьём, командой)

- **Статус:** [PENDING] (зависит от 4.1; решение О-2) · **Level:** Middle+ (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (команды `scene.effects.get` / `scene.effects.set` у `scene_source`)
- **CHAIN:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** оператор включает и крутит эффекты кадра сима из пульта, видит результат на живом кадре.

**Files:**
1. `Plugins/sim/scene_source/plugin.py` — команды через очередь управления (`_control`, тот же приём, что pause/flow — Task 6.1)
2. `Plugins/sim/pult_web/plugin.py` — панель «Эффекты кадра» (поля из `effects.catalog` 4.3)
3. `Plugins/sim/scene_source/README.md`, `Plugins/sim/pult_web/README.md`
- тесты: `Plugins/sim/scene_source/tests/test_scene_effects_commands.py`

**DESIGN:** по умолчанию (О-2) — только живьём: перезапуск возвращает `scene_effects` из `pipeline.yaml`. `set` проверяет
список тем же `effects_from_config` и отвечает `{ok: false, error}` без применения на кривом списке.

**Acceptance:**
- [ ] `scene.effects.set([noise])` → следующий кадр отличается, паспорта — нет; `scene.effects.get` возвращает установленное.
- [ ] Кривой список → `{ok: false}` с текстом ошибки, кадр без изменений.
- [ ] Очередь управления не растёт без предела (лимит `_CONTROL_MAXLEN` сохраняется).
- [ ] Живой стенд (лид): включить шум из пульта — видно на кадре; выключить — кадр как до включения.

**Out of scope:** запись в `pipeline.yaml` (О-2), эффекты фона.
