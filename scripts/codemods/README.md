# scripts/codemods — кодмоды на ast-grep

Разовые правки «одно правило на сотню файлов». Правила в [`rules/`](rules/), конфиг —
[`sgconfig.yml`](sgconfig.yml).

Правило = один файл. ast-grep допускает несколько документов в одном YAML, но
pre-commit-хук `check-yaml` — нет; разводить их по файлам дешевле, чем ослаблять хук.

## Установка ast-grep

Бинаря в проекте нет и в зависимости он не добавлен: кодмод — разовая операция, а не
часть сборки. Ставит владелец, одной из команд:

```bash
uv tool install ast-grep-cli      # предпочтительно: не трогает .venv проекта
# либо
npm i -g @ast-grep/cli
```

Проверка: `ast-grep --version`.

## std_logger_migration — Ф6.2

Переводит голый `logging.getLogger(__name__)` на вид `get_std_logger(__name__)`
(конвенция Ф6.0, решение Р-А — обоснование в
[`logger_module/README.md`](../../multiprocess_framework/modules/logger_module/README.md)).

```bash
# 1. Вхолостую: только отчёт, ни один файл не тронут
ast-grep scan -c scripts/codemods/sgconfig.yml

# 2. Диф без записи (глазами по выборке, не по всем 107 файлам)
ast-grep scan -c scripts/codemods/sgconfig.yml --json=compact | head

# 3. Применить
ast-grep scan -c scripts/codemods/sgconfig.yml -U
```

### Что правило НЕ делает — и почему это не забыто

1. **Не переименовывает переменную.** 12 файлов держат `_logger` вместо `logger`;
   переименование потянуло бы все точки использования ради стиля. Переписывается
   только правая часть присваивания.
2. **Не удаляет `import logging`.** В части файлов он нужен и дальше (уровни,
   `logging.handlers`). Осиротевшие импорты снимаются после кодмода:
   ```bash
   ruff check --select F401 --fix multiprocess_prototype multiprocess_framework Services Plugins
   ruff format <затронутые файлы>
   ```
3. **Не берёт алиасные импорты.** Три точки в двух файлах написаны через алиас
   (`_logging` / `_log`) внутри `try/except` на импорте:
   `multiprocess_prototype/domain/__init__.py:145,154` и
   `multiprocess_prototype/frontend/app.py:640`. Расширять правило вариантами алиаса
   ради трёх точек — дороже, чем поправить руками; но забыть их нельзя, поэтому они
   названы здесь и проверяются приёмкой 6.2 (`grep getLogger(__name__)` = 0 вне
   whitelist).

4. **Не видит `import logging` внутри функции.** Правило `std-logger-import`
   вставляет импорт рядом с МОДУЛЬНЫМ `import logging`. Где его нет, вызов
   окажется переписан, а импорта вида не будет — `NameError` в рантайме,
   невидимый в диффе. Такие файлы перечислены поимённо в
   [`WHITELIST_6_5.md`](WHITELIST_6_5.md); правятся руками до прогона приёмки.

### Whitelist — директориями, где можно

`tests/` — директорией: stdlib-логгер там предмет теста. Исключения-по-устройству
(`_fallback.py`, `observable_mixin.py`, `config_module/`) — поимённо, с причиной у
каждой строки прямо в правиле; свалки из whitelist не делать (условие приёмки 6.5).
