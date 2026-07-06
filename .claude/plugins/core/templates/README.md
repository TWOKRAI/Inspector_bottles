# Templates — File templates for new projects

These are **source templates** used by `claude-kit-project new` when bootstrapping a new project. You normally don't copy them by hand — the CLI does it for you.

## How `claude-kit-project new` uses templates

When you run:

```bash
claude-kit-project new ~/Project_code/my_new_app --name "My New App"
```

the script copies the seed and instantiates these templates with placeholder substitution:

| Template | Generated file | Placeholders substituted |
|----------|----------------|---------------------------|
| `pyproject.template.toml` | `pyproject.toml` | `{{PACKAGE}}`, `{{DESCRIPTION}}`, `{{AUTHOR}}` |
| `pre-commit-config.template.yaml` | `.pre-commit-config.yaml` | — |
| `Makefile.template` | `Makefile` | `{{PACKAGE}}` |
| `gitignore.template` | `.gitignore` | — |
| `gitattributes.template` | `.gitattributes` | — |
| `editorconfig.template` | `.editorconfig` | — |
| `env.example.template` | `.env.example` | — |
| `claude-md.template.md` | `CLAUDE.md` (root) | `{{PROJECT_NAME}}`, `{{PACKAGE}}`, `{{DESCRIPTION}}` |
| `vscode-settings.json.template` | `.vscode/settings.json` | — |
| `vscode-extensions.json.template` | `.vscode/extensions.json` | — |
| `github-workflows-ci.yml.template` | `.github/workflows/ci.yml` | `{{PACKAGE}}` |

## Toolchain assumed

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — package + venv manager
- [ruff](https://docs.astral.sh/ruff/) — lint + format
- [pyright](https://microsoft.github.io/pyright/) — static type checker
- [pytest](https://docs.pytest.org/) — testing
- [pre-commit](https://pre-commit.com/) — git hooks orchestration

## Manual override

If you want to customize before instantiating (e.g. add `httpx` to default deps), edit the `.template` file in this directory — `claude-kit-project new` will pick it up on next run.

## What is NOT here

- `sentrux-rules.template.toml` lives in [`../mcp/sentrux/`](../mcp/sentrux/) — single source of truth for sentrux config
- `claude-md.template.md` is the **root** `CLAUDE.md` template, not `.claude/CLAUDE.md` (the latter is fixed seed content)
