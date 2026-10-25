#!/usr/bin/env bash
# PreToolUse (Bash) : refuse tout lancement du mode DJ sans le premier titre forcé.
cmd=$(jq -r '.tool_input.command // empty')
case "$cmd" in
  *main.py*--dj-mode*)
    if [[ "$cmd" != *--dj-include* ]]; then
      echo "Mode DJ sans premier titre : ajoute --dj-include <début>-<fin du 1er titre> et --dj-include-label \"<nom>\". Si la fin du titre est inconnue, demande-la à KOI." >&2
      exit 2
    fi ;;
esac
exit 0
