---
name: dj-clips
description: Découper un set Hello World Mix en clips 9:16 avec le mode DJ, le premier titre du set toujours forcé en clip n°1.
disable-model-invocation: true
argument-hint: <fichier ou lien du set> <fin du 1er titre, ex. 6:00> "<nom du 1er titre>" [nb clips]
---

# Clips d'un set — premier titre obligatoire

Arguments : `$ARGUMENTS`

1. **Premier titre.** Il faut la fin du premier titre (ex. `6:00`) et son nom.
   S'ils manquent dans les arguments, les demander et s'arrêter là. Ne jamais lancer sans :
   le premier titre est toujours le clip n°1 (règle de KOI).
2. **Source.** Fichier local → `--source local`. Lien YouTube → `--source youtube`.
3. **Lancer** (titre et numéro du mix à demander s'ils ne se déduisent pas du nom du fichier) :

   ```bash
   python main.py --url "<set>" --source <local|youtube> --dj-mode --clips <N, défaut 8> \
     --dj-include 0:00-<fin du 1er titre> --dj-include-label "<nom du 1er titre>" \
     --dj-title "Hello World Mix <n°>" --dj-hashtags "#afrohouse #djset #helloworldmix" \
     --ratio 9:16 --transition mire
   ```

4. **Vérifier** dans `outputs/gemini_response.json` :
   - le clip `rank` 1 a `dj_forced: true` et son label est le nom du titre ;
   - `start_time` et `end_time` du clip 1 sont dans la plage du premier titre ;
   - autant de `highlight_rank_N_ready.mp4` que de clips demandés.
5. **Bip de la mire ≤ −15 dB** sur le clip 1 :
   `ffmpeg -i outputs/highlight_rank_1_ready.mp4 -ss 3 -t 1 -af volumedetect -f null - 2>&1 | grep max_volume`
6. **Rendu à KOI** : la liste des clips (rang, type, plage, titre) et la courbe
   `outputs/dj_energy.png` (rose = premier titre). Ne rien publier :
   `run_upload.py` et `run_fb_upload.py` seulement sur demande explicite.
