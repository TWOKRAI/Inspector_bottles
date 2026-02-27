# Git Workflow для Рефакторинга

## 🌳 Стратегия Веток

### Рекомендуемая Структура Веток

```
main (production)
  └── develop (development)
      ├── feature/refactor-config-module
      ├── feature/refactor-command-module
      ├── feature/refactor-base-manager
      └── ...
```

### Описание Веток

1. **main** - стабильная версия, рабочая версия кода
2. **develop** - ветка разработки, куда мержатся все изменения
3. **feature/refactor-<module>** - ветки для рефакторинга отдельных модулей

## 📋 Пошаговая Инструкция

### Шаг 1: Создание Ветки Разработки

```bash
# Убедись что ты на main и все закоммичено
git checkout main
git status

# Создай ветку develop из main
git checkout -b develop

# Запушь develop в удаленный репозиторий
git push -u origin develop
```

### Шаг 2: Настройка Защиты Веток (Опционально)

Если используешь GitHub/GitLab, настрой защиту веток:
- **main** - только через Pull Request
- **develop** - можно пушить напрямую, но лучше через PR

### Шаг 3: Рефакторинг Модуля

#### 3.1 Создание Ветки для Модуля

```bash
# Переключись на develop
git checkout develop

# Обнови develop (если были изменения)
git pull origin develop

# Создай ветку для рефакторинга модуля
git checkout -b feature/refactor-config-module

# Запушь ветку
git push -u origin feature/refactor-config-module
```

#### 3.2 Работа над Рефакторингом

```bash
# Делай изменения
# ...

# Коммить часто, маленькими коммитами
git add modules/config_module/
git commit -m "refactor(config): упростил структуру модуля"

git add modules/config_module/tests/
git commit -m "test(config): добавил тесты для новой структуры"

git add modules/config_module/README.md
git commit -m "docs(config): обновил документацию"
```

#### 3.3 Завершение Рефакторинга

```bash
# Убедись что все тесты проходят
pytest modules/config_module/tests/ -v

# Проверь что ничего не сломалось
pytest tests/ -v

# Обнови документацию если нужно
# ...

# Создай финальный коммит
git add .
git commit -m "refactor(config): завершил рефакторинг модуля

Изменения:
- Упростил структуру модуля
- Стандартизировал код
- Улучшил документацию
- Добавил тесты

Все тесты проходят ✅"

# Запушь изменения
git push origin feature/refactor-config-module
```

#### 3.4 Слияние в Develop

```bash
# Переключись на develop
git checkout develop

# Обнови develop
git pull origin develop

# Смержи feature ветку
git merge feature/refactor-config-module

# Или через rebase (если предпочитаешь)
# git rebase develop feature/refactor-config-module
# git checkout develop
# git merge feature/refactor-config-module

# Запушь develop
git push origin develop

# Удали локальную feature ветку (опционально)
git branch -d feature/refactor-config-module

# Удали удаленную feature ветку (опционально)
git push origin --delete feature/refactor-config-module
```

### Шаг 4: Периодическое Слияние Develop в Main

После завершения рефакторинга нескольких модулей:

```bash
# Переключись на main
git checkout main

# Обнови main
git pull origin main

# Смержи develop в main
git merge develop

# Или создай Pull Request для review (рекомендуется)

# Запушь main
git push origin main

# Вернись на develop
git checkout develop
```

## 🔄 Альтернативный Подход: Чистая Develop Ветка

Если хочешь начать с чистой develop ветки:

### Вариант 1: Создать Develop из Текущего Main

```bash
# Создай develop из текущего main
git checkout main
git checkout -b develop
git push -u origin develop
```

**Плюсы:**
- Сохраняется вся история
- Можно вернуться к старому коду
- Просто и безопасно

**Минусы:**
- Develop содержит весь старый код

### Вариант 2: Создать Чистую Develop (НЕ РЕКОМЕНДУЕТСЯ)

```bash
# Создай пустую ветку (НЕ ДЕЛАЙ ЭТОГО!)
git checkout --orphan develop
git rm -rf .
# ... создай новый код
```

**Плюсы:**
- Чистая ветка

**Минусы:**
- Теряется вся история
- Сложно отследить изменения
- Очень рискованно

## ✅ Рекомендуемый Workflow

### Для Рефакторинга Одного Модуля

```bash
# 1. Создай ветку из develop
git checkout develop
git pull origin develop
git checkout -b feature/refactor-config-module

# 2. Рефактори модуль
# ... делай изменения ...

# 3. Коммить часто
git add .
git commit -m "refactor(config): описание изменений"

# 4. Заверши рефакторинг
# ... убедись что тесты проходят ...

# 5. Смержи в develop
git checkout develop
git merge feature/refactor-config-module
git push origin develop

# 6. Удали feature ветку
git branch -d feature/refactor-config-module
git push origin --delete feature/refactor-config-module
```

### Для Рефакторинга Нескольких Модулей

```bash
# Рефактори модули один за другим
# После каждого модуля мержи в develop

# После завершения нескольких модулей:
git checkout main
git merge develop
git push origin main
```

## 🛡️ Защита от Ошибок

### Перед Слиянием

1. **Проверь что все тесты проходят:**
   ```bash
   pytest tests/ -v
   ```

2. **Проверь что нет конфликтов:**
   ```bash
   git fetch origin
   git merge origin/develop --no-commit --no-ff
   # Если есть конфликты, разреши их
   git merge --abort  # Отмени если нужно
   ```

3. **Проверь изменения:**
   ```bash
   git diff develop..feature/refactor-config-module
   ```

### Если Что-то Пошло Не Так

1. **Откати изменения в feature ветке:**
   ```bash
   git checkout feature/refactor-config-module
   git reset --hard HEAD~1  # Откати последний коммит
   ```

2. **Откати merge:**
   ```bash
   git checkout develop
   git merge --abort  # Если merge еще не завершен
   git reset --hard origin/develop  # Если merge завершен
   ```

3. **Вернись к предыдущему состоянию:**
   ```bash
   git reflog  # Найди нужный коммит
   git reset --hard <commit-hash>
   ```

## 📝 Шаблон Коммитов

### Для Рефакторинга

```
refactor(<module>): краткое описание

Детальное описание изменений:
- Что изменил
- Почему изменил
- Что улучшилось

Изменения:
- Упростил структуру модуля
- Стандартизировал код
- Улучшил документацию
- Добавил тесты

Тесты: ✅ Все проходят
```

### Примеры

```bash
git commit -m "refactor(config): упростил структуру модуля

- Объединил похожие файлы
- Удалил ненужные уровни вложенности
- Улучшил именование

Тесты: ✅ Все проходят"
```

## 🎯 Рекомендации

### Что Делать

1. ✅ Создавай отдельную ветку для каждого модуля
2. ✅ Коммить часто, маленькими коммитами
3. ✅ Тестируй после каждого изменения
4. ✅ Мержи в develop после завершения модуля
5. ✅ Периодически мержи develop в main

### Чего НЕ Делать

1. ❌ Не рефактори несколько модулей в одной ветке
2. ❌ Не делай большие коммиты
3. ❌ Не мержи в main без тестирования
4. ❌ Не удаляй main или develop ветки
5. ❌ Не форсируй push в main

## 📊 Визуализация Workflow

```
main:     A---B---C---D---E (стабильные версии)
           \         /   /
develop:   F---G---H---I---J (разработка)
              \   /   \
feature:       K---L   M---N (рефакторинг модулей)
```

## ✅ Итог

**Рекомендуемый подход:**

1. **Оставь main как есть** - это стабильная версия
2. **Создай develop** - ветка для разработки
3. **Для каждого модуля** - создавай `feature/refactor-<module>` ветку
4. **Мержи в develop** - после завершения рефакторинга модуля
5. **Периодически мержи develop в main** - после завершения нескольких модулей

**Не создавай новую main ветку!** Используй develop для разработки, main для стабильных версий.

