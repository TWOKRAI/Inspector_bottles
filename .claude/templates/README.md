# Templates — Готовые шаблоны для нового проекта

Минимальные стартовые версии всех конфигов. Скопировать в корень нового проекта, адаптировать
под свой стек, удалить ненужное.

## Файлы

| Шаблон | Куда копировать | Адаптировать |
|--------|-----------------|--------------|
| [`pyproject.template.toml`](pyproject.template.toml) | `pyproject.toml` в корень | name, dependencies, testpaths |
| [`pre-commit-config.template.yaml`](pre-commit-config.template.yaml) | `.pre-commit-config.yaml` в корень | `entry: mypy <package>` |
| [`Makefile.template`](Makefile.template) | `Makefile` в корень | переменные FRAMEWORK/PROTOTYPE |
| [`gitignore.template`](gitignore.template) | `.gitignore` в корень | под свой стек |
| [`sentrux-rules.template.toml`](sentrux-rules.template.toml) | `.sentrux/rules.toml` | `[[layers]]`, `[[boundaries]]` |
| [`claude-md.template.md`](claude-md.template.md) | `CLAUDE.md` в корень | секции Проект, Архитектура, Стек |

## Workflow

```bash
# 1. Скопировать всё разом
cd /path/to/new-project
cp .claude/templates/pyproject.template.toml ./pyproject.toml
cp .claude/templates/pre-commit-config.template.yaml ./.pre-commit-config.yaml
cp .claude/templates/Makefile.template ./Makefile
cp .claude/templates/gitignore.template ./.gitignore
cp .claude/templates/claude-md.template.md ./CLAUDE.md
mkdir -p .sentrux && cp .claude/templates/sentrux-rules.template.toml ./.sentrux/rules.toml

# 2. Адаптировать под проект (см. секции "Адаптировать" в каждом файле)

# 3. Установить
uv sync --group dev --group diagrams
uv run pre-commit install
uv run pre-commit install --hook-type pre-push
```

См. [`../BOOTSTRAP.md`](../BOOTSTRAP.md) для полного гайда.
