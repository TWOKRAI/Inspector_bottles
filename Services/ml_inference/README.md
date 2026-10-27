# ml_inference — инференс нейросетей

Сервис инференса для pipeline: на вход BGR-кадр, на выходе классы + confidence.
Старт — классификация (MobileNetV3), архитектура универсальная (задел под детекцию).

## Идея: data-driven + pluggable

- **Model registry + sidecar** — рядом с весами лежит `<basename>.yaml` с описанием
  препроцессинга (input_size, layout, цветопорядок, normalize, labels, backend).
  Добавить модель = положить веса + sidecar в `data/models/`, код не трогаем.
- **Backend-абстракция** (`BaseInferenceBackend`) — ONNX Runtime (основной) и torch
  (опц.) за единым интерфейсом. Задел под TensorRT/OpenVINO.

## Структура

```
core/      — препроцессинг/постобработка + ModelRegistry (без ML-либ: numpy+opencv)
backends/  — ONNXRuntimeBackend (осн.), TorchBackend (TorchScript, опц.)
engine.py  — InferenceEngine: каталог + backend + pre/post, кэш модели, warmup
plugin/    — MLInferencePlugin (тонкий): кадр → engine → predictions (+ overlay)
```

## Установка зависимостей

```bash
pip install '.[ml]'        # onnxruntime + onnx (основной backend)
pip install '.[ml-torch]'  # torch + torchvision (опц., только TorchScript)
```

Graceful degradation: сервис импортируется без ML-библиотек; инференс отключается
с понятной ошибкой, если backend-библиотека не установлена.

## Использование в pipeline

Нода `ml_inference` (category=processing). Инспектор:
- **Модель** — динамический выпадающий список из `data/models` (custom widget `model_picker`);
- **Устройство** — cpu | cuda;
- **Порог уверенности**, **Top-K**, **Рисовать результат**.

Выходные порты: `frame` (кадр, опц. overlay) + `predictions` (`list[dict]`:
`class_id`, `label`, `confidence`, `below_threshold`).

### «Подпись всегда» и `below_threshold` (Task 0.3, letters-retrain)

Плагин НЕ отсекает предсказания ниже порога: движок зовётся с `threshold=0.0`, `predictions`
содержит 1..`top_k` элементов (топ-1 есть всегда, если модель отработала), у каждого
`below_threshold = (confidence < confidence_threshold)` — строгое `<`, `confidence == порог`
НЕ ниже. Угол считается для топ-1 и ниже порога. `InferenceEngine.predict` и
`classify_postprocess` не менялись (`holdout_eval` по-прежнему получает отсечение по своему `threshold`).

- Register `last_below_threshold` (readonly): флаг топ-1. `True` и при отсутствии предсказания
  (ошибка инференса, смена модели) — fail-safe «не доверять»; `last_label`/`last_confidence` —
  топ-1 всегда, и ниже порога.
- Overlay ниже порога: оранжевый цвет и суффикс «<порог» (выше порога — зелёный, как раньше).
- Каждый кадр на входе распознаётся; отбор кадров — отдельный фильтр в рецепте (C-40).
- **Безопасность:** робот не действует ниже порога. `ml_inference` лишь помечает; страж на
  стороне потребителя — `word_layout` отказывается от предсказания с `below_threshold=True`
  (двойная проверка, см. его README). Новый потребитель `predictions` обязан проверять флаг.

Команды (live): `set_model`, `set_threshold`, `reload_model`.

### Проверка ассетов модели (C-55b)

`ModelRegistry.diagnose(model_id) -> ModelDiagnosis` проверяет одну выбранную модель, без кэша
и без побочных эффектов. Выбор файла весов тот же, что у `scan()` (общий `_weight_files`:
при `m1.onnx` + `m1.pth` берётся последний в порядке `sorted`, т.е. `m1.pth`). Плагин зовёт
проверку при каждой загрузке модели: старт процесса, `set_model`, `reload_model`.

`ModelDiagnosis`: `severity` (`error` | `warning` | `info`), `message`, `path`, `spec`. Порядок проверок:

1. `model_id == ""` — **warning** «модель не выбрана», `path` = каталог моделей.
2. id вне белого списка (`\w(?:[\w.\- ]*\w)?`, без `..`) — **error**, `path = None`. Сырой id в текст
   не попадает. Шаблон — копия `_NAME_RE` из `modules/recipe/service.py` (импортировать нельзя).
3. Каталога моделей нет — **error**.
4. Нет весов (`.onnx` | `.pt` | `.pth`) — **error**, `path = <каталог>/<id>`.
5. Нет sidecar — **error**, `path` = sidecar.
6. Sidecar не читается — **error**; в текст идёт только имя типа исключения, не `str(exc)`.
7. `weights:` из sidecar указывает на отсутствующий файл — **error**.
8. `labels:` задан, а файла нет, он пуст или из одних пробелов — **error**.
9. Иначе — **info** «модель готова», `spec` заполнен.

Куда идёт каждый уровень:

| уровень | действие плагина |
|---|---|
| error | модель выгружается (pass-through), регистр `last_error` = текст, `ctx.health.report_error(ModelAssetError)`, health процесса `degraded` с причиной `ml_inference: <текст>` |
| warning | модель выгружается, `ctx.log_warning`; health не трогается (пустая модель — штатный pass-through) |
| info | модель грузится, `ctx.log_info` |

**Старт системы не блокируется:** исключение из `configure` / команд не выходит. Деградацию health
плагин снимает (`set_status("ok")`) только свою — если сам ставил её и статус всё ещё `degraded`.
Чужую деградацию (другой плагин, breaker) не снимает. Гейту готовности мало `health.status`: он
должен читать и регистр `last_error`.

**Сужение (п. 8):** раньше модель с `labels:`, указывающим на отсутствующий или пустой файл,
грузилась и подписывала классы `class_<id>`. Теперь это error, health `degraded`, pass-through:
в тракте робота метка `class_3` вместо буквы кладёт диск не в ту ячейку молча.

**Обход C-66 (временный).** Breaker `HealthState` забирает владение `DEGRADED` и при закрытии
зовёт `ok(None)` — деградация из-за ассетов пропадала сама. Поэтому `_publish_state` (не чаще раза
в секунду, из `process`) ставит её заново, если `_asset_degraded` и статус не `degraded`
(комментарий `# Обход C-66` в `plugin.py`). Снять после исправления владения `degraded` в health
(C-66). Пока кадров нет, `process` не зовётся, и между закрытием breaker и следующим кадром статус
показывает `ok`.

## Формат моделей

См. [`data/models/README.md`](../../data/models/README.md).

## Тесты

```bash
pytest Services/ml_inference/tests/        # core/engine/plugin (dummy ONNX, без реальных весов)
pytest multiprocess_prototype/frontend/forms/tests/test_model_picker.py  # widget
```
