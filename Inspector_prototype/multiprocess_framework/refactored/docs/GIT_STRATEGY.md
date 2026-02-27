# Стратегия Git для Рефакторинга

## 📊 Текущая Ситуация

У тебя есть ветки:
- `master` - старая основная ветка
- `new_architecture` - новая архитектура
- `new_work` - новая работа
- `refactor/multiprocess_framework` - текущая ветка (рефакторинг)

## 🎯 Рекомендуемая Стратегия

### Вариант 1: Использовать Текущую Ветку как Develop (Рекомендуется)

Если `refactor/multiprocess_framework` содержит актуальный код:

```bash
# 1. Переименуй текущую ветку в develop
git branch -m refactor/multiprocess_framework develop

# 2. Запушь develop
git push origin develop
git push origin --delete refactor/multiprocess_framework

# 3. Создай feature ветки для каждого модуля
git checkout develop
git checkout -b feature/refactor-config-module
```

**Плюсы:**
- Используешь текущий код
- Не нужно создавать новую ветку
- Просто и быстро

### Вариант 2: Создать Develop из Master

Если хочешь начать с чистого master:

```bash
# 1. Переключись на master
git checkout master

# 2. Создай develop из master
git checkout -b develop

# 3. Смержи изменения из текущей ветки (если нужно)
git merge refactor/multiprocess_framework

# 4. Запушь develop
git push -u origin develop
```

**Плюсы:**
- Чистый старт
- Сохраняется история
- Можно выбрать что мержить

### Вариант 3: Использовать Master как Main (Простой)

Если master содержит рабочий код:

```bash
# 1. Переименуй master в main (если нужно)
git branch -m master main
git push origin main
git push origin --delete master

# 2. Создай develop из main
git checkout -b develop
git push -u origin develop

# 3. Смержи текущую ветку в develop (если нужно)
git merge refactor/multiprocess_framework

# 4. Создай feature ветки для модулей
git checkout -b feature/refactor-config-module
```

## 🔄 Рекомендуемый Workflow

### Структура Веток

```
main (бывший master) - стабильная версия
  └── develop - разработка
      ├── feature/refactor-config-module
      ├── feature/refactor-command-module
      └── ...
```

### Процесс Работы

1. **Начни с develop:**
   ```bash
   # Создай develop из текущей ветки или master
   git checkout refactor/multiprocess_framework  # или master
   git checkout -b develop
   git push -u origin develop
   ```

2. **Для каждого модуля:**
   ```bash
   git checkout develop
   git checkout -b feature/refactor-config-module
   # ... рефактори модуль ...
   git add .
   git commit -m "refactor(config): описание"
   git push origin feature/refactor-config-module
   ```

3. **После завершения модуля:**
   ```bash
   git checkout develop
   git merge feature/refactor-config-module
   git push origin develop
   git branch -d feature/refactor-config-module
   ```

4. **Периодически мержи develop в main:**
   ```bash
   git checkout main
   git merge develop
   git push origin main
   ```

## ✅ Быстрая Настройка

### Если Используешь Текущую Ветку

```bash
# 1. Переименуй текущую ветку в develop
git branch -m develop

# 2. Запушь develop
git push -u origin develop
git push origin --delete refactor/multiprocess_framework

# 3. Готово! Теперь создавай feature ветки
git checkout -b feature/refactor-config-module
```

### Если Начинаешь с Master

```bash
# 1. Переключись на master
git checkout master

# 2. Создай develop
git checkout -b develop

# 3. Смержи текущую ветку (если нужно)
git merge refactor/multiprocess_framework

# 4. Запушь develop
git push -u origin develop

# 5. Готово!
```

## 🎯 Моя Рекомендация

**Используй Вариант 1** - переименуй текущую ветку в develop:

```bash
# Это самый простой и быстрый способ
git branch -m develop
git push -u origin develop
git push origin --delete refactor/multiprocess_framework
```

**Почему:**
- Используешь текущий код
- Не нужно ничего мержить
- Просто и быстро
- Можно сразу начинать рефакторинг модулей

## 📝 Что Делать Дальше

После создания develop:

1. **Выбери первый модуль** (например, config_module)
2. **Создай feature ветку:**
   ```bash
   git checkout develop
   git checkout -b feature/refactor-config-module
   ```
3. **Рефактори модуль** (следуй REFACTORING_GUIDE.md)
4. **Мержи в develop** после завершения
5. **Повтори для следующего модуля**

## ⚠️ Важные Замечания

1. **Не удаляй master/main** - это твоя стабильная версия
2. **Не рефактори несколько модулей в одной ветке** - создавай отдельную ветку для каждого
3. **Коммить часто** - маленькие коммиты легче откатить
4. **Тестируй после каждого изменения** - не ломай то, что работает
5. **Мержи develop в main периодически** - после завершения нескольких модулей

## 📚 Дополнительно

- [GIT_WORKFLOW.md](GIT_WORKFLOW.md) - подробное руководство
- [QUICK_START_REFACTORING.md](QUICK_START_REFACTORING.md) - быстрый старт
- [REFACTORING_GUIDE.md](REFACTORING_GUIDE.md) - руководство по рефакторингу

