# opensource-clipping — fork de KOI (D Jay Koi)

Fork utilisé surtout pour le **mode DJ** : découper les sets « Hello World Mix »
en clips 9:16 (drops détectés à l'audio, sans Whisper ni Gemini).
Réponses et messages en français, directs et concis.

## Règles non négociables

1. **Le premier titre du set est toujours le clip n°1.**
   Chaque lancement en mode DJ passe `--dj-include <début>-<fin du 1er titre>`
   (ex. `0:00-6:00`) et `--dj-include-label "<nom du titre>"`.
   Le clip forcé reste entièrement dans cette plage (voir `detect_moments` dans
   `clipping/dj_mode.py`). Si la fin du premier titre est inconnue, demander à KOI ;
   ne jamais lancer sans.
2. **FX jamais au-dessus de −15 dB** (bip de la mire : `--mire-beep-db`, plafonné à −15).
3. **Colab tire `main` directement** (`notebooks/DJ_Mode_Colab.ipynb`, cellule 1).
   Un commit cassé sur `main` casse le prochain clipping : tester avant de pousser.
4. **Contrat JSON** : `dj_mode.build_clip_json` produit la même forme que la réponse
   LLM (`outputs/gemini_response.json`). Ne pas renommer ses clés (`title_inggris`,
   `hastag`, `alasan`… sont attendues telles quelles par le rendu, les uploaders et
   `--load-gemini-json`).
5. **Pas de publication sans accord** : `run_upload.py` / `run_fb_upload.py`
   publient sur YouTube / Facebook. Ne pas toucher à `upload_safety.json`, `.env`,
   `credentials.json`, `youtube_token.json`.

## Commandes

```bash
pip install -r requirements-dj.txt          # dépendances légères du mode DJ
python main.py --url set.mp4 --source local --dj-mode --clips 8 \
  --dj-include 0:00-6:00 --dj-include-label "Nom du titre" \
  --dj-title "Hello World Mix 9" --dj-hashtags "#afrohouse #djset #helloworldmix"
ruff check .                                 # erreurs réelles seulement (config dans pyproject.toml)
```

Sorties dans `outputs/` : `highlight_rank_N_ready.mp4`, `dj_energy.png`
(rose = premier titre forcé), `dj_analysis.json`, `gemini_response.json`.

## Repères

- `clipping/dj_mode.py` : analyse audio, drops, fenêtres en mesures entières.
- `clipping/config.py` : options CLI (`--dj-*`).
- `clipping/studio/` : rendu ffmpeg (recadrage, hook, mire, miniatures).
- Pas de suite de tests : utiliser `/dj-test` avant chaque push touchant le mode DJ.
- Bug connu hors mode DJ : `broll_data` indéfini dans `render_camera_switch.py`.
