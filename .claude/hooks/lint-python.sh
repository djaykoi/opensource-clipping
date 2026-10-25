#!/usr/bin/env bash
# PostToolUse (Edit|Write) : erreurs réelles sur le fichier Python modifié.
# Config ruff dans pyproject.toml (syntaxe, noms indéfinis ; pas de règles de style).
f=$(jq -r '.tool_input.file_path // empty')
[[ "$f" == *.py && -f "$f" ]] || exit 0
out=$( { python3 -m py_compile "$f" && { ! command -v ruff >/dev/null || ruff check --quiet "$f"; }; } 2>&1 )
if [[ $? -ne 0 ]]; then
  echo "$out" >&2
  exit 2   # renvoyé à Claude pour correction immédiate
fi
exit 0
