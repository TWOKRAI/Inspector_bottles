# multiprocess_prototype/docs/README.md

Прототип v3: инкрементальная проверка `multiprocess_framework` (см. `plans/prototype_v3_plan.md` в корне репозитория).

## Запуск

Из каталога текущий каталог с `PYTHONPATH`, включающим корень прототипа и `multiprocess_framework/modules`:

```bash
export PYTHONPATH="$(pwd):$(pwd)/multiprocess_framework/modules"
python -m multiprocess_prototype.main
```

Профиль **minimal** (producer + consumer):

```bash
export MULTIPROCESS_V3_PROFILE=minimal
python -m multiprocess_prototype.main
```

С GUI (PyQt):

```bash
export MULTIPROCESS_V3_WITH_GUI=1
python -m multiprocess_prototype.main
```

## Тесты

```bash

PYTHONPATH="$(pwd):$(pwd)/multiprocess_framework/modules" \
  python -m pytest multiprocess_prototype/tests/ -v --tb=short
```
