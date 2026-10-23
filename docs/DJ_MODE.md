# 🎧 Mode DJ — clips à partir d'un DJ set

Le pipeline d'origine choisit les moments en lisant la parole (Whisper + Gemini). Sur un DJ set, il n'y a pas de discours : le mode DJ remplace cette étape par une **analyse audio** du set. Tout le reste du pipeline (recadrage 9:16 avec suivi du visage, hook, watermark, miniatures, uploaders) reste identique.

Aucune clé API n'est nécessaire.

## Démarrage rapide (Colab)

Ouvre [`notebooks/DJ_Mode_Colab.ipynb`](../notebooks/DJ_Mode_Colab.ipynb) dans Google Colab, règle le lien du set et le titre, puis exécute les cellules.

## En ligne de commande

```bash
# Depuis YouTube
python main.py --url "https://www.youtube.com/watch?v=..." --dj-mode \
  --clips 8 --dj-title "Hello World Mix 9" --dj-hashtags "#afrohouse #djset #helloworldmix"

# Depuis un fichier local (ou Google Drive monté dans Colab)
python main.py --url "/chemin/vers/set.mp4" --source local --dj-mode --clips 8
```

## Comment les moments sont choisis

1. **Analyse du son** : énergie des basses, des médiums et des aigus, et attaques (onsets), calculées par blocs pour tenir en mémoire même sur un set de 2 h.
2. **Tempo** détecté automatiquement (100-140 BPM), ou forcé avec `--dj-bpm`.
3. **Drops** : endroits où les basses reviennent fort après un breakdown (comparaison du niveau des basses sur 4 mesures avant et après), sur une section qui sonne fort par rapport au reste du set.
4. **Calage précis** : chaque drop est recalé sur le kick le plus fort à ± une demi-temps.
5. **Fenêtre en mesures entières** : 8 mesures de montée avant le drop, 16 mesures après (réglable).
6. **Complément** : s'il y a moins de drops que de clips demandés, les clips restants sont pris sur les passages les plus énergiques (« peaks »).

Structure d'un clip : **hook de 3 s sur le drop → transition glitch → montée → drop → pleine énergie**.

## Options

| Option | Défaut | Rôle |
| --- | --- | --- |
| `--dj-mode` | off | Active la sélection audio. Coupe aussi sous-titres, B-roll, musique de fond et voice-over. |
| `--source local` | — | Utilise un fichier vidéo local au lieu d'un téléchargement. |
| `--dj-pre-bars` | `8` | Mesures de montée gardées avant le drop. |
| `--dj-post-bars` | `16` | Mesures gardées après le drop. |
| `--dj-min-gap` | `90` | Écart minimum (s) entre deux moments choisis. |
| `--dj-min-rise` | `6.0` | Remontée minimale des basses (dB) pour compter comme drop. Baisse à 4 si le set a des breakdowns légers. |
| `--dj-bpm` | auto | Force le tempo. |
| `--dj-title` | `DJ Set` | Titre des clips, miniatures et métadonnées. |
| `--dj-hashtags` | `#djset #house #dj` | Hashtags ajoutés à chaque clip. |
| `--hook-duration` | `3` | Durée du hook (s) en début de clip. `--no-hook` pour le retirer. |

## Fichiers produits (`outputs/`)

| Fichier | Contenu |
| --- | --- |
| `highlight_rank_N_ready.mp4` | Clip final. |
| `thumbnail_rank_N.jpg` | Miniature avec le titre. |
| `dj_energy.png` | Courbe des basses du set avec les moments choisis (orange = drop, vert = peak). |
| `dj_analysis.json` | Tempo, durée, moments détectés. |
| `gemini_response.json` | Sélection utilisée pour le rendu. Modifiable à la main, puis relancer avec `--load-gemini-json` pour ne refaire que le rendu. |

## Limites connues

- Le suivi du visage fonctionne si le DJ est visible et éclairé. Tête baissée sur les platines ou lumière stroboscopique : le cadrage revient au centre.
- Les transitions entre deux morceaux peuvent ressembler à un drop. Vérifie `dj_energy.png` et ajuste à la main si besoin.
- Les morceaux d'autres artistes présents dans le set peuvent être coupés en son ou réclamés par les plateformes.
