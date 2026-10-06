---
name: feedback-git-main-merge-hook-traps
description: "Единый формат merge-коммита (merge: суть + Why/Layer/Refs, решение владельца 2026-10-03); git/hook грабли (traps) при merge в main: git merge -F - не читает stdin, protect-branch блокирует commit на main, git add на удалённом пути фаталит"
mechanism: [git, hooks]
metadata:
  node_type: memory
  type: feedback
  originSessionId: d875e08d-a524-4e41-9207-8671a6945b06
  modified: 2026-10-04T06:59:54.182Z
---

Набор воспроизведённых грабель git-workflow этого проекта (2026-07-09, Pre-Ф5 hardening). Тратил на них итерации — держать в голове.

## Грабли и обходы

1. **`git merge -F -` НЕ читает stdin** (в отличие от `git commit -F -`) → `error: could not read file '-'`. Используй `git merge --no-ff <branch> -m "..." -m "..."` (каждый `-m` = абзац) ИЛИ `-F <реальный файл>`.

2. **protect-branch hook блокирует `git commit` на main, оценивая ТЕКУЩУЮ ветку ДО выполнения.** Compound-команда, которая сначала `git checkout -b feat/x`, а потом `git commit`, всё равно блокируется целиком (хук видит `git commit` + текущую main). → **Разбивай на отдельные вызовы Bash:** (1) `checkout -b`; (2) отдельно `git commit` (ветка уже не main). `git merge` на main НЕ блокируется (нет `git commit` в строке) — так и вливаем в main.

3. **`git add <removed-dir> <other-files>` фаталит на удалённом пути** (`pathspec did not match`) и НЕ стейджит НИЧЕГО из списка → правки молча повисают (у меня чистка STATUS/CONTEXT не попала в kill-коммит). → Не мешай `git rm`-удалённые пути с новыми в одном `git add`; **после commit проверяй `git show --stat`**, что все файлы вошли.

4. **scratchpad-файл сообщения может исчезнуть между вызовами Bash** (`could not read file`). Для merge-message — либо `-m`-флаги, либо писать файл и merge в ОДНОМ вызове.

5. **`echo "rc=$?"` после `cmd | tail` даёт exit `tail`, не команды.** Для проверки реального кода — `cmd; echo $?` без пайпа, либо `${PIPESTATUS[0]}`.

**Why:** каждая из этих грабель стоила отдельной итерации/отладки; они системные (хук + git-семантика), повторятся в любой сессии с merge в main.

**How to apply:** merge в main = `git merge --no-ff <branch> -m ... -m ...` отдельным вызовом; коммит на защищённую ветку — только через отдельную feature-ветку двумя вызовами Bash (checkout, затем commit); после kill-коммитов сверяй `git show --stat`. Связано: [[feedback_commit_takes_the_whole_index]] (trailers Why/Layer строго однострочные — та же семья hook-грабель).

**Открытый вопрос (нужно решать):** protect-branch стоило бы дополнить исключением для merge/cherry-pick, чтобы docs/handoff на main не требовали ветку-обёртку (ранее правку хука блокировал auto-классификатор как self-modification — обсудить с владельцем вне auto-режима).

6. **Слияние с `--no-commit` (нужно для `--sync-order`) завершается без строки `git commit`** (проверено 2026-10-04,
   `14aa47ab6`): `git merge --no-ff --no-commit <ветка>` → `--sync-order` → `git add plans/queue/ORDER.md` →
   ОДНИМ вызовом Bash записать сообщение в `$(git rev-parse --git-dir)/MERGE_MSG` и `GIT_EDITOR=true git merge --continue`.
   Хук блокирует вызов целиком, поэтому heredoc в заблокированной команде с `git commit` не выполняется вовсе —
   файл сообщения не появляется, а слияние так и висит подготовленным (это не потеря, просто повторить).

## Единый формат коммита слияния (решение владельца 2026-10-03)

Владелец: «нужен единый формат у всех». Каждый merge-коммит — в `main` и синхронизация `main` → ветка — пишется так:
`merge: <что вошло>` (синхронизация: `merge: main (<sha>) в <ветка> — <зачем>`), затем `Why:`, `Layer:`, `Refs:` (если из
плана), `Co-Authored-By:`. Делать `git merge --no-ff <ветка> -F <файл>`; при конфликте — `git commit -F <тот же файл>`.
Сообщение git по умолчанию («Merge branch …») не оставлять. Хук сейчас merge-коммиты НЕ проверяет
(`validate_commit.py` `SKIP_PREFIXES`, `COMMIT_GUIDE.md:225`) — это не нарушение «правила», а разнобой: 2 из 13 слияний
в `main` (608d609c6, 48a753eb4). Проверено: git 2.50 вызывает `commit-msg` на `git merge`, отказ хука → «Not committing
merge» — значит, формат можно закрепить хуком. Предложение (хук + обе копии `validate_commit` + COMMIT_GUIDE) отправлено
соседям 5a и f4 2026-10-03; кто делает — по их ответу.

**Why:** `git log --first-parent main` — журнал изменений; «Merge branch 'red/deps-31'» не говорит, что вошло.
**How to apply:** любой свой merge — в этом формате, включая синхронизацию трека с `main`; пока хук не закреплён, чужой
merge по умолчанию — сказать соседу числом, без переписывания истории `main`.
