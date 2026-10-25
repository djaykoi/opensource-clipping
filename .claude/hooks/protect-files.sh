#!/usr/bin/env bash
# PreToolUse (Edit|Write) : secrets et limites de publication intouchables.
f=$(jq -r '.tool_input.file_path // empty')
case "$f" in
  *.env|*/credentials.json|*/youtube_token.json|*/upload_safety.json|*/.credentials/*)
    echo "Fichier protégé : $f (secrets ou limites d'upload). Modifie-le toi-même si besoin." >&2
    exit 2 ;;
esac
exit 0
