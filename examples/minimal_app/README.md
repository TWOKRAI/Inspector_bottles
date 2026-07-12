# minimal_app — референс-приложение на фреймворке (Ф5.11)

Второй потребитель фреймворка (после `multiprocess_prototype`) и **forcing function**
против Inspector-специфики в «универсальном» `app_module`. Приложение = данные +
декларации + ~3 строки bootstrap; ни камеры, ни GUI, ни прототипа.

```
minimal_app/
  app.yaml                       # манифест: name/version + pipeline + discovery-пути
  pipeline.yaml                  # плоская топология: 1 процесс на базовом GenericProcess
  plugins/tick_source/plugin.py  # тривиальный tick-генератор (worker LOOP)
  services/echo_service/service.yaml  # маркер сервиса (авто-скан находит по нему)
  run.py                         # run_app(app.yaml)
```

## Запуск

```bash
python examples/minimal_app/run.py
```

Стартует один headless-процесс `ticker`, логирующий tick каждую секунду. Остановка —
Ctrl+C (штатный shutdown лончера).

## Что доказывает

- «Рыба» бутится **на framework-дефолтах** (`GenericProcess` + `ProcessManagerProcess`),
  без импортов прототипа;
- авто-скан `app_module.discover` находит **И плагин** (`plugin.py`), **И сервис**
  (маркер `service.yaml`) из папок, объявленных в `app.yaml`;
- баннер старта — из `manifest.name`.

Финализация + CI-smoke (headless boot через BackendHarness) + sentrux-инвариант
«examples не импортирует multiprocess_prototype» — Ф5.13.
