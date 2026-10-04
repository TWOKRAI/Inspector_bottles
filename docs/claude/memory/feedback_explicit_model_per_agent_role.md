---
name: explicit-model-per-agent-role
description: "Owner rule — always pass `model` explicitly when launching agents; reviewer and teamlead on opus, developer and tester on sonnet, super-reviewer (cto) on fable; также: Исполнители: Sonnet 5 — дефолт (near-Opus, ~2.5x дешевле), Opus 4.8 — только верхний край (конкурентность/длинные автономные заходы); Fable — план/ревью-свод/merge; брифы под Sonnet 5 — с явным охватом"
merged_from: [feedback_model_split_impl_vs_review]
metadata:
  type: feedback
---

Правило перенесено в `.claude/skills/project-rules/SKILL.md` §5 (2026-10-04). Ниже — доказательная база урока.

When launching an agent with the Agent tool, pass `model` explicitly. Mapping (owner, 2026-10-02): `reviewer` = opus, `teamlead` = opus, `developer` / `tester` / `debugger` = sonnet, super-reviewer (`cto`) = fable.

**Why:** the reviewer was launched without `model` during the prompt-audit review. Its frontmatter says `opus`, but the journal (`data/team-journal.jsonl`) does not record the model, so Opus could not be confirmed. The owner wanted the review on Opus.

**How to apply:** pass `model: "opus"` / `"sonnet"` / `"fable"` on every Agent call, and state the model in the brief. Do not rely on the frontmatter default alone. The cto (Fable) is the "super-reviewer": once per phase or disputed decision, never per task.

Related: [[always-latest-models]]

## Слито из feedback_model_split_impl_vs_review (_archive/feedback_model_split_impl_vs_review.md)

Правило владельца (2026-07-12, уточнено 2026-07-13): агенты-исполнители запускать с model override, НЕ на дефолтном Fable. **Sonnet 5 — законный дефолт** (официально «near-Opus quality» на кодинге/агентной работе, цена $3/$15 против $5/$25 у Opus 4.8); **Opus 4.8 — только верхний край**: конкурентность, протоколы владения, длинные автономные вскрытия (Ф7: G.3/G.4). Fable (main loop) — декомпозиция, брифы, свод ревью, merge.

**Why:** Fable-агенты жгут лимит сессии; Sonnet 5 подтвердил класс на G.6 (добротный код, честный самоотчёт) — его промахи были по ОХВАТУ, не по строкам: модель документированно исполняет буквально и не обобщает инструкцию с одного элемента на другие.

**How to apply:** `model: "sonnet"` — дефолт исполнителя (S/M-задачи, тесты, docs, фиксы); `model: "opus"` — конкурентность/cross-layer вскрытия; брифы под Sonnet 5 писать с ЯВНЫМ охватом («проверь все места, где item пересобирается», не «добавь поле»); финдеры/верификаторы ревью — Sonnet. См. [[review-economy-tiers]], [[formal-review-before-merge]], [[worktree-stale-base]].
