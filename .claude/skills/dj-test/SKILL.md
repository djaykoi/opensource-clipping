---
name: dj-test
description: Vérifier le mode DJ avant un push (Colab tire main) — premier titre forcé, fenêtres, lint, notebook.
disable-model-invocation: true
---

# Test du mode DJ avant push

Colab clone `main` à chaque lancement : rien ne part sur `main` sans ces étapes.

1. `ruff check .` — doit être propre hormis le bug connu `broll_data` (render_camera_switch.py).
2. `python tests/test_dj_first_track.py` — le premier titre est le clip n°1, reste dans sa
   plage et garde sa longueur ; les plages limites tiennent.
3. Si `clipping/dj_mode.py` a changé : comparer les clés produites par `build_clip_json`
   avec la version de `main` (`git diff main -- clipping/dj_mode.py`). Aucune clé retirée
   ni renommée.
4. Si le notebook `notebooks/DJ_Mode_Colab.ipynb` a changé : JSON valide
   (`python -c "import json;json.load(open('notebooks/DJ_Mode_Colab.ipynb'))"`), la
   cellule 3 passe toujours `--dj-include` et le garde `PREMIER_TITRE` est présent.
5. `pip install --dry-run -r requirements-dj.txt` si ce fichier a changé.
6. Si un set court est disponible localement, lancer `/dj-clips` dessus.

Résumé à KOI : ce qui passe, ce qui casse, et si le push est sûr.
