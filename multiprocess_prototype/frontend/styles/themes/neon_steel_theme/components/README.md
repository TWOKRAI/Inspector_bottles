# Компонентные стили

Монолитный `main.qss` разбит на модульные файлы для удобства поддержки.

## Структура

```
components/
  primitives/    ← универсальные Qt-виджеты (фреймворк)
    buttons.qss, tabs.qss, combobox.qss, ...
  domains/       ← доменные стили прототипа
    recipes.qss, inspector.qss, pipeline.qss, ...
```

### primitives/

Стили стандартных Qt-виджетов. Используются любым приложением на фреймворке.
В будущем (Этап B) переедят в `frontend_module/components/styles/`.

### domains/

Стили, специфичные для текущего приложения (inspector_bottles).
Другие приложения на фреймворке их не подключают.

## Как добавить новый компонентный файл

1. Создать `.qss` файл в `primitives/` или `domains/`
2. Добавить заголовок: `/* === filename.qss — описание === */`
3. Добавить путь в `PRIMITIVE_STYLE_FILES` или `DOMAIN_STYLE_FILES`
   в `style_manifest.py`
4. **Порядок файлов = каскад** — добавлять в позицию, соответствующую
   желаемому приоритету (позже = выше приоритет)

## Сборка

Файлы собираются в один QSS через `style_manifest.py`:
- `base.qss` → глобальные правила (QWidget, QLabel, QToolTip)
- `PRIMITIVE_STYLE_FILES` → универсальные виджеты в порядке каскада
- `DOMAIN_STYLE_FILES` → доменные стили (после primitives)

## Порядок файлов важен!

Qt QSS не поддерживает CSS-scoping. Порядок в манифесте определяет каскад:
правила из файлов, идущих позже, переопределяют более ранние.

## Путь миграции в Этап B

1. `primitives/` → `frontend_module/components/styles/` (mv файлов)
2. Добавится `ComponentStyleRegistry` для регистрации примитивов
3. `domains/` остаётся в прототипе
4. `style_manifest.py` сохраняется для domain-стилей
