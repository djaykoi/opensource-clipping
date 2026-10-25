---
name: release
description: Publier une nouvelle version du fork — bump synchronisé, CHANGELOG, tests, commit.
disable-model-invocation: true
argument-hint: <patch|minor|major>
---

# Release

1. Lancer `/dj-test`. S'arrêter si quelque chose casse.
2. Nouvelle version (`$ARGUMENTS`, défaut `patch`) à partir de `version` dans
   `pyproject.toml`. Mettre la même dans `web/dashboard/package.json`.
3. Ajouter en tête de `CHANGELOG.md` une entrée datée, en français, à partir de
   `git log <dernier tag ou dernier bump>..HEAD --oneline` : changements visibles par
   l'utilisateur, pas le détail technique.
4. Commit `release: vX.Y.Z` et tag `vX.Y.Z`. Montrer le diff à KOI avant `git push`.
