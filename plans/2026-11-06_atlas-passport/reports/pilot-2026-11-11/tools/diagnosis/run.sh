#!/bin/bash
# usage: run.sh <args...> ; prints exit code, stdout line count, stderr, first N lines
cd /private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/atlas-src
O=/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/inv/last.out
E=/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/inv/last.err
python pilot_atlas.py "$@" > $O 2> $E
echo "exit=$? stdout_lines=$(wc -l < $O) stdout_chars=$(wc -c < $O) stderr_lines=$(wc -l < $E)"
echo "--- stderr:"; head -${ERRN:-8} $E
echo "--- stdout head:"; head -${N:-15} $O
