# multiprocess_prototype_v3/docs/README.md

Прототип v3: инкрементальная проверка `multiprocess_framework` (см. `plans/prototype_v3_plan.md` в корне репозитория).

## Запуск

Из каталога `Inspector_prototype` с `PYTHONPATH`, включающим корень прототипа и `multiprocess_framework/modules`:

```bash
export PYTHONPATH="$(pwd):$(pwd)/multiprocess_framework/modules"
python -m multiprocess_prototype_v3.main
```

Профиль **minimal** (producer + consumer):

```bash
export MULTIPROCESS_V3_PROFILE=minimal
python -m multiprocess_prototype_v3.main
```

С GUI (PyQt):

```bash
export MULTIPROCESS_V3_WITH_GUI=1
python -m multiprocess_prototype_v3.main
```

## Тесты

```bash
cd Inspector_prototype
PYTHONPATH="$(pwd):$(pwd)/multiprocess_framework/modules" \
  python -m pytest multiprocess_prototype_v3/tests/ -v --tb=short
```
