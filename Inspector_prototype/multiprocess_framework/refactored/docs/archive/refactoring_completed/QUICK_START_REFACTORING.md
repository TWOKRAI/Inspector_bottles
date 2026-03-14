# Быстрый Старт: Рефакторинг Модуля

## 🚀 За 5 Минут

### 1. Настрой Git Workflow

```bash
# Создай develop ветку (если еще нет)
git checkout main
git checkout -b develop
git push -u origin develop
```

### 2. Создай Ветку для Модуля

```bash
# Выбери модуль для рефакторинга (например, config_module)
git checkout develop
git pull origin develop
git checkout -b feature/refactor-config-module
git push -u origin feature/refactor-config-module
```

### 3. Рефактори Модуль

Следуй инструкциям из `REFACTORING_GUIDE.md`:
1. Изучи модуль
2. Составь план
3. Упрости структуру
4. Стандартизируй код
5. Улучши документацию

### 4. Коммить Изменения

```bash
# После каждого изменения
git add .
git commit -m "refactor(config): описание изменений"

# Запушь изменения
git push origin feature/refactor-config-module
```

### 5. Заверши Рефакторинг

```bash
# Убедись что тесты проходят
pytest modules/config_module/tests/ -v
pytest tests/ -v

# Смержи в develop
git checkout develop
git merge feature/refactor-config-module
git push origin develop

# Удали feature ветку
git branch -d feature/refactor-config-module
git push origin --delete feature/refactor-config-module
```

## 📋 Чеклист

- [ ] Создал develop ветку
- [ ] Создал feature ветку для модуля
- [ ] Изучил модуль
- [ ] Составил план рефакторинга
- [ ] Упростил структуру
- [ ] Стандартизировал код
- [ ] Улучшил документацию
- [ ] Все тесты проходят
- [ ] Смержил в develop
- [ ] Удалил feature ветку

## 🎯 Следующие Шаги

1. Выбери следующий модуль
2. Повтори процесс
3. После нескольких модулей - смержи develop в main

## 📚 Дополнительно

- [GIT_WORKFLOW.md](GIT_WORKFLOW.md) - подробное руководство по git workflow
- [REFACTORING_GUIDE.md](REFACTORING_GUIDE.md) - подробное руководство по рефакторингу
- [REFACTORING_PLAN.md](REFACTORING_PLAN.md) - план рефакторинга по модулям

