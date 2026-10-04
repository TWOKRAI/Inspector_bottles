cd /d/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/atlas
EX=(':!plans' ':!docs/sessions' ':!docs/handoffs' ':!docs/reviews' ':!docs/claude/memory/_archive' ':!graphify-out' ':!docs/audits' ':!workspace' ':!.claude/plugins' ':!.claude/agent-memory' ':!*/tests/*' ':!*DECISIONS.md' ':!docs/notes' ':!.claude/.delivery-manifest.json' ':!.claude/settings.local.json')
t(){ id="$1"; pat="$2"; echo "== $id"; git grep -nIoE "$pat" -- . "${EX[@]}" | cut -c1-170; echo "files: $(git grep -lIE "$pat" -- . "${EX[@]}" | grep -c .)"; }
t D1 '(Всего модулей[^0-9]{0,60}|модулей[ :—-]{1,4}|\()?(25|27) модул[а-я]*|Карта \(?(25|27) модул'
t D2 'Layer:?`?[^|]{0,50}(обязател|mandatory|required)|(обязател|mandatory|required)[^|]{0,50}Layer:?'
t D3 'dual-write|autoMemoryDirectory|Canonical path:?\*?\*?'
t D4 'docs/claude/DECISIONS/|docs/decisions/[^ ]{0,20}|modules/X/DECISIONS\.md'
t D5 'workspace/plans|apps/\{app\}/plans|apps/\*/plans|plans/<slug>\.md|plans/<slug>/plan\.md'
t D6 'PySide6 ?(>=|==|~=)? ?6\.1[0-9]|torch ?(>=|==)? ?2\.[0-9]+|PyTorch 2\.[0-9]+'
t D7 'handoff-parallel-start'
t D10 'get_indexing_status|Сверка свежести|qex freshness|check_qex_freshness'
