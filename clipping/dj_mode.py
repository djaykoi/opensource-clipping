"""
clipping.dj_mode — Audio-driven moment detection for DJ sets.

Replaces the Whisper + LLM selection step when the source is a DJ set or any
continuous music content, where there is no speech to analyse.

How it works
------------
1. The audio track is decoded once (mono, 11 kHz) and split into three bands
   (low / mid / high) plus a spectral-flux onset curve, computed in chunks so a
   2-hour set stays well under 1 GB of RAM.
2. Tempo is estimated from the onset curve (autocorrelation, 100-140 BPM).
3. A "drop" is where the low band comes back hard after a breakdown:
   score = (bass level over the next N bars) - (bass level over the previous
   N bars), weighted by how loud the section after the drop is compared with
   the rest of the set.
4. Each drop is snapped to the strongest bass onset within half a beat, and
   the clip window is built in whole bars around it: build-up before, full
   energy after. The 3-second hook teaser is the drop itself.
5. If a set has fewer clear drops than requested, the remaining clips are
   filled with the highest-energy passages ("peak" moments).

The output uses the same JSON shape as the LLM response, so the rest of the
pipeline (framing, hook, watermark, thumbnails, uploaders) works unchanged,
and the saved ``gemini_response.json`` can be edited by hand and re-rendered
with ``--load-gemini-json``.
"""

from __future__ import annotations

import json
import os
import subprocess

import numpy as np

SR = 11025          # analysis sample rate
N_FFT = 2048        # ~186 ms window
HOP = 512           # ~46 ms hop
CHUNK_FRAMES = 4096 # frames per FFT chunk (~3 min of audio)

BANDS = {
    "low": (30.0, 150.0),
    "mid": (150.0, 2000.0),
    "high": (2000.0, 5500.0),
}


# ==============================================================================
# AUDIO DECODING & FEATURES
# ==============================================================================

def _decode_audio(video_path: str, sr: int = SR) -> np.ndarray:
    """Decode the audio track to a mono float32 array with ffmpeg."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", video_path, "-vn", "-ac", "1", "-ar", str(sr),
        "-f", "f32le", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "❌ [DJ Mode] Impossible de décoder l'audio : "
            + proc.stderr.decode(errors="ignore")[-500:]
        )
    audio = np.frombuffer(proc.stdout, dtype=np.float32)
    if audio.size < sr * 10:
        raise RuntimeError("❌ [DJ Mode] Piste audio trop courte ou vide (< 10 s).")
    return audio


def compute_features(audio: np.ndarray, sr: int = SR) -> dict:
    """Band energies (dB) and onset strength per frame, computed chunk by chunk."""
    n_frames = 1 + max(0, (audio.size - N_FFT) // HOP)
    freqs = np.fft.rfftfreq(N_FFT, d=1.0 / sr)
    window = np.hanning(N_FFT).astype(np.float32)
    band_idx = {
        name: (freqs >= lo) & (freqs < hi) for name, (lo, hi) in BANDS.items()
    }
    low_flux_idx = (freqs >= 30.0) & (freqs < 150.0)

    out = {name: np.empty(n_frames, dtype=np.float32) for name in BANDS}
    flux = np.zeros(n_frames, dtype=np.float32)
    low_flux = np.zeros(n_frames, dtype=np.float32)

    prev_log = None
    for start in range(0, n_frames, CHUNK_FRAMES):
        stop = min(n_frames, start + CHUNK_FRAMES)
        idx = (np.arange(start, stop)[:, None] * HOP) + np.arange(N_FFT)[None, :]
        frames = audio[idx] * window
        mag = np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)
        power = mag ** 2
        for name, mask in band_idx.items():
            out[name][start:stop] = 10.0 * np.log10(power[:, mask].mean(axis=1) + 1e-10)

        log_mag = np.log1p(mag)
        if prev_log is None:
            diff = np.vstack([np.zeros_like(log_mag[:1]), np.diff(log_mag, axis=0)])
        else:
            diff = np.diff(np.vstack([prev_log, log_mag]), axis=0)
        pos = np.maximum(diff, 0.0)
        flux[start:stop] = pos.sum(axis=1)
        low_flux[start:stop] = pos[:, low_flux_idx].sum(axis=1)
        prev_log = log_mag[-1:]

    fps = sr / HOP
    times = (np.arange(n_frames) * HOP + N_FFT / 2) / sr
    return {
        "times": times,
        "fps": fps,
        "duration": audio.size / sr,
        "flux": flux,
        "low_flux": low_flux,
        **out,
    }


def _smooth(x: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n))
    if n == 1:
        return x.astype(np.float64)
    kernel = np.ones(n) / n
    pad = n // 2
    xp = np.pad(x.astype(np.float64), (pad, n - 1 - pad), mode="edge")
    return np.convolve(xp, kernel, mode="valid")


def _rolling_median(x: np.ndarray, n: int, step: int) -> np.ndarray:
    """Coarse rolling median evaluated every *step* frames, then interpolated."""
    n = max(1, int(n))
    centers = np.arange(0, x.size, max(1, step))
    vals = np.empty(centers.size)
    for i, c in enumerate(centers):
        lo = max(0, c - n // 2)
        hi = min(x.size, c + n // 2 + 1)
        vals[i] = np.median(x[lo:hi])
    return np.interp(np.arange(x.size), centers, vals)


def estimate_bpm(flux: np.ndarray, fps: float, bpm_min=100.0, bpm_max=140.0) -> float:
    """Tempo from the autocorrelation of the onset curve, over several windows."""
    win = int(60 * fps)
    if flux.size < win:
        win = flux.size
    starts = np.linspace(0, max(0, flux.size - win), num=min(12, max(1, flux.size // win)))
    lag_min = int(np.floor(60.0 * fps / bpm_max))
    lag_max = int(np.ceil(60.0 * fps / bpm_min))
    estimates = []
    for s in starts.astype(int):
        seg = flux[s:s + win].astype(np.float64)
        seg = seg - seg.mean()
        if not np.any(seg):
            continue
        f = np.fft.rfft(seg, n=2 * seg.size)
        ac = np.fft.irfft(f * np.conj(f))[: seg.size]
        if ac[0] <= 0:
            continue
        ac /= ac[0]
        lags = np.arange(lag_min, min(lag_max + 1, ac.size))
        if lags.size == 0:
            continue
        # Reward lags whose double (one bar of 2 beats) also correlates.
        score = ac[lags] + 0.5 * ac[np.minimum(lags * 2, ac.size - 1)]
        best = lags[np.argmax(score)]
        # Parabolic refinement
        if 1 <= best < ac.size - 1:
            a, b, c = ac[best - 1], ac[best], ac[best + 1]
            denom = a - 2 * b + c
            off = 0.5 * (a - c) / denom if denom != 0 else 0.0
        else:
            off = 0.0
        estimates.append(60.0 * fps / (best + off))
    if not estimates:
        return 124.0
    return float(np.median(estimates))


# ==============================================================================
# MOMENT DETECTION
# ==============================================================================

def _pick_peaks(score: np.ndarray, min_dist: int, threshold: float, max_n: int) -> list[int]:
    """Greedy non-maximum suppression: highest scores first, min distance apart."""
    order = np.argsort(score)[::-1]
    taken: list[int] = []
    for i in order:
        if score[i] < threshold or len(taken) >= max_n:
            break
        if all(abs(int(i) - t) >= min_dist for t in taken):
            taken.append(int(i))
    return taken


def detect_moments(
    feats: dict,
    n_clips: int,
    bpm: float,
    pre_bars: int = 8,
    post_bars: int = 16,
    min_gap: float = 90.0,
    min_rise_db: float = 6.0,
    skip_edges: float = 20.0,
    include_ranges: list[tuple[float, float]] | None = None,
) -> tuple[list[dict], dict]:
    """Return a list of moments (drops first, then peaks) and debug curves."""
    fps = feats["fps"]
    times = feats["times"]
    duration = feats["duration"]
    beat = 60.0 / bpm
    bar = 4 * beat

    low = _smooth(feats["low"], fps * 1.0)
    full = _smooth(
        10 * np.log10(
            10 ** (feats["low"] / 10) + 10 ** (feats["mid"] / 10) + 10 ** (feats["high"] / 10)
        ),
        fps * 1.0,
    )

    # Bass before / after each frame over a 4-bar window (fast rolling median).
    w = int(round(4 * bar * fps))
    step = max(1, int(fps / 4))
    med = _rolling_median(low, w, step)
    shift = w // 2
    before = np.concatenate([np.full(shift, med[0]), med[:-shift]]) if shift else med
    after = np.concatenate([med[shift:], np.full(shift, med[-1])]) if shift else med
    rise = after - before

    global_ref = np.percentile(low, 60)
    loudness_after = after - global_ref
    drop_score = rise + 0.5 * np.clip(loudness_after, -12, 6)

    edge = int(skip_edges * fps)
    valid = np.ones_like(drop_score, dtype=bool)
    valid[:edge] = False
    valid[max(0, drop_score.size - edge):] = False
    # A drop must land on a loud section and come from a real dip.
    valid &= loudness_after > -3.0
    valid &= rise >= min_rise_db
    drop_score_masked = np.where(valid, drop_score, -np.inf)

    min_dist = int(min_gap * fps)
    half_beat = int(0.5 * beat * fps)
    # The 4-bar medians only place a drop within ±2 bars. Refine with a 1-bar
    # before/after contrast on the raw bass curve, then snap to the kick onset.
    raw_low = feats["low"].astype(np.float64)
    csum = np.concatenate([[0.0], np.cumsum(raw_low)])
    one_bar = max(1, int(round(bar * fps)))

    def _refine(i: int) -> int:
        lo = max(one_bar, i - 2 * one_bar)
        hi = min(raw_low.size - one_bar, i + 2 * one_bar)
        if hi > lo:
            cand = np.arange(lo, hi)
            after_1 = (csum[cand + one_bar] - csum[cand]) / one_bar
            before_1 = (csum[cand] - csum[cand - one_bar]) / one_bar
            i = int(cand[np.argmax(after_1 - before_1)])
        lo = max(0, i - half_beat)
        hi = min(feats["low_flux"].size, i + half_beat + 1)
        return lo + int(np.argmax(feats["low_flux"][lo:hi]))

    moments: list[dict] = []

    # Forced moments: the best drop inside each requested time range, whatever
    # its strength (e.g. the artist's own track at the start of the set).
    for rs, re_ in include_ranges or []:
        a = max(0, int(rs * fps))
        b = min(drop_score.size, int(re_ * fps))
        if b - a < one_bar:
            continue
        seg = drop_score[a:b].copy()
        seg_valid = loudness_after[a:b] > -6.0
        # Keep room for the build-up when the range starts at 0.
        seg_valid[: max(0, int(pre_bars * bar * fps) - a)] = False
        if not seg_valid.any():
            seg_valid[:] = True
        i = a + int(np.argmax(np.where(seg_valid, seg, -np.inf)))
        kind = "drop" if rise[i] >= 2.0 else "peak"
        j = _refine(i) if kind == "drop" else i
        j = min(max(j, a), b - 1)  # refinement must not leave the range
        moments.append({
            "kind": kind,
            "anchor": float(times[j]),
            "score": float(drop_score[i]),
            "rise_db": float(rise[i]),
            "forced": True,
            "range": [float(rs), float(re_)],
        })
        drop_score_masked[max(0, j - min_dist):j + min_dist] = -np.inf

    drop_idx = _pick_peaks(
        drop_score_masked, min_dist, threshold=min_rise_db,
        max_n=max(0, n_clips - len(moments)),
    )
    for i in drop_idx:
        j = _refine(i)
        moments.append({
            "kind": "drop",
            "anchor": float(times[j]),
            "score": float(drop_score[i]),
            "rise_db": float(rise[i]),
        })

    # Fill with energy peaks if the set has fewer drops than requested.
    if len(moments) < n_clips:
        energy = _smooth(full, fps * 16 * beat) + 0.002 * _smooth(feats["flux"], fps * 8)
        taken = [int(m["anchor"] * fps) for m in moments]
        mask = np.ones_like(energy, dtype=bool)
        mask[:edge] = False
        mask[max(0, energy.size - edge):] = False
        for t in taken:
            mask[max(0, t - min_dist):t + min_dist] = False
        energy_masked = np.where(mask, energy, -np.inf)
        extra = _pick_peaks(
            energy_masked, min_dist, threshold=-np.inf, max_n=n_clips - len(moments)
        )
        for i in extra:
            # Center the window on the peak: anchor = peak - post window / 2
            lo = max(0, i - half_beat)
            hi = min(feats["low_flux"].size, i + half_beat + 1)
            j = lo + int(np.argmax(feats["low_flux"][lo:hi]))
            moments.append({
                "kind": "peak",
                "anchor": float(times[j]),
                "score": float(energy[i] - np.median(energy)),
                "rise_db": float(rise[i]),
            })

    # Build bar-aligned windows.
    for m in moments:
        a = m["anchor"]
        if m["kind"] == "drop":
            start = a - pre_bars * bar
            end = a + post_bars * bar
        else:
            half = (pre_bars + post_bars) * bar / 2
            start = a - half
            end = a + half
        # Clamp while keeping whole bars when possible. A forced clip stays
        # inside its own range, so the artist's track never bleeds into the
        # next one.
        lo, hi = 0.0, duration
        if m.get("forced"):
            lo = max(lo, m["range"][0])
            hi = min(hi, m["range"][1])
            # Slide the window back inside the range first (keeps the clip
            # length: more build-up instead of a shorter clip).
            while end > hi and start - bar >= lo:
                start -= bar
                end -= bar
            while start < lo and end + bar <= hi:
                start += bar
                end += bar
        while start < lo and start + bar < end:
            start += bar
        while end > hi and end - bar > start:
            end -= bar
        start, end = max(lo, start), min(hi, end)
        end = max(end, start + min(bar, hi - start))
        if not (start <= m["anchor"] < end):  # keep the hook inside the clip
            m["anchor"] = max(start, end - bar)
        m["start_time"] = round(start, 3)
        m["end_time"] = round(end, 3)

    debug = {
        "times": times,
        "low": low,
        "rise": rise,
        "drop_score": drop_score,
        "bar": bar,
    }
    return moments, debug


# ==============================================================================
# OUTPUT
# ==============================================================================

def _parse_tc(text: str) -> float:
    """'1:23:45', '12:30', '90' -> seconds."""
    parts = [float(p) for p in str(text).strip().split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def parse_ranges(specs, duration: float) -> list[tuple[float, float]]:
    """Parse ['0:00-6:00', '24:00'] into (start, end) seconds.

    A single timecode means a 3-minute window starting there.
    """
    out = []
    for spec in specs or []:
        spec = str(spec).strip()
        if not spec:
            continue
        if "-" in spec:
            a, b = spec.split("-", 1)
            s, e = _parse_tc(a), _parse_tc(b)
        else:
            s = _parse_tc(spec)
            e = s + 180.0
        s, e = max(0.0, s), min(duration, e)
        if e > s:
            out.append((s, e))
    return out


def _fmt_tc(t: float) -> str:
    t = int(round(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_clip_json(moments: list[dict], cfg, bpm: float) -> list[dict]:
    """Convert moments to the clip schema used by the render pipeline."""
    title = (getattr(cfg, "dj_title", None) or "DJ Set").strip()
    hashtags = (getattr(cfg, "dj_hashtags", None) or "#djset #house #dj").strip()
    hook_dur = float(getattr(cfg, "durasi_hook", 3))

    # Rank by score inside each kind, drops before peaks.
    forced = [m for m in moments if m.get("forced")]
    rest = [m for m in moments if not m.get("forced")]
    drops = sorted([m for m in rest if m["kind"] == "drop"], key=lambda m: -m["score"])
    peaks = sorted([m for m in rest if m["kind"] == "peak"], key=lambda m: -m["score"])
    ordered = forced + drops + peaks

    clips = []
    for rank, m in enumerate(ordered, start=1):
        label = "Drop" if m["kind"] == "drop" else "Peak"
        if m.get("forced"):
            label = getattr(cfg, "dj_include_label", None) or label
        name = f"{title} — {label} {rank}"
        tc = _fmt_tc(m["anchor"])
        hook_start = m["anchor"]
        hook_end = min(m["end_time"], hook_start + hook_dur)
        desc_ctx = (
            f"{label} at {tc} in the full set ({bpm:.0f} BPM). "
            f"Full mix on the channel."
        )
        clips.append({
            "rank": rank,
            "viral_score": round(max(0.0, min(100.0, 50 + 5 * m["score"])), 1),
            "start_time": m["start_time"],
            "end_time": m["end_time"],
            "hook": {"text": "", "start_time": hook_start, "end_time": hook_end},
            "hook_start_time": hook_start,
            "hook_end_time": hook_end,
            "thumbnail_text": (getattr(cfg, "dj_thumb_text", None) or "HELLO WORLD MIX"),
            "title_inggris": name,
            "title_indonesia": name,
            "description_hook": name,
            "description_context": desc_ctx,
            "hastag": hashtags,
            "keyword_tags": [title, "dj set", "dj mix", "house music", "live mix"],
            "tiktok_caption": name,
            "tiktok_title_id": name,
            "tiktok_caption_id": name,
            "alasan": (
                f"[DJ Mode] {m['kind']} @ {tc} — bass rise {m['rise_db']:+.1f} dB, "
                f"score {m['score']:.2f}"
            ),
            "dj_kind": m["kind"],
            "dj_forced": bool(m.get("forced")),
            "dj_anchor_time": round(m["anchor"], 3),
            "broll_list": [],
            "typography_plan": [],
        })
    return clips


def save_energy_plot(debug: dict, moments: list[dict], duration: float, path: str) -> None:
    """Draw a simple energy overview PNG with the selected moments (OpenCV only)."""
    try:
        import cv2
    except ImportError:
        return
    W, H = 1600, 420
    img = np.full((H, W, 3), 24, dtype=np.uint8)
    t = debug["times"]
    low = debug["low"]
    x = (t / max(duration, 1e-6) * (W - 1)).astype(int)
    lo, hi = np.percentile(low, 2), np.percentile(low, 99.5)
    y = (H - 40 - (np.clip(low, lo, hi) - lo) / max(hi - lo, 1e-6) * (H - 80)).astype(int)
    step = max(1, x.size // (W * 2))
    pts = np.stack([x[::step], y[::step]], axis=1).reshape(-1, 1, 2)
    cv2.polylines(img, [pts], False, (180, 180, 180), 1, cv2.LINE_AA)

    # Same order as build_clip_json, so the numbers match the clip ranks.
    rest = [m for m in moments if not m.get("forced")]
    for rank, m in enumerate(
        [m for m in moments if m.get("forced")]
        + sorted([m for m in rest if m["kind"] == "drop"], key=lambda m: -m["score"])
        + sorted([m for m in rest if m["kind"] == "peak"], key=lambda m: -m["score"]),
        start=1,
    ):
        if m.get("forced"):
            color = (255, 120, 220)
        else:
            color = (60, 200, 255) if m["kind"] == "drop" else (120, 220, 120)
        xs = int(m["start_time"] / duration * (W - 1))
        xe = int(m["end_time"] / duration * (W - 1))
        xa = int(m["anchor"] / duration * (W - 1))
        overlay = img.copy()
        cv2.rectangle(overlay, (xs, 20), (xe, H - 30), color, -1)
        img = cv2.addWeighted(overlay, 0.18, img, 0.82, 0)
        cv2.line(img, (xa, 20), (xa, H - 30), color, 2)
        cv2.putText(img, str(rank), (xa + 4, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    for k in range(0, int(duration) + 1, 300):
        xk = int(k / duration * (W - 1))
        cv2.putText(img, _fmt_tc(k), (xk + 2, H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (140, 140, 140), 1)
    cv2.putText(img, "bass energy  |  pink = forced (first track)  orange = drop  green = peak", (10, 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.imwrite(path, img)


def find_moments(cfg) -> list[dict]:
    """Full DJ-mode selection step. Returns the clip list for the renderer."""
    print("\n🎧 [DJ Mode] Analyse audio du set (pas de Whisper / IA)...")
    audio = _decode_audio(cfg.file_video_asli)
    feats = compute_features(audio)
    del audio

    bpm_arg = getattr(cfg, "dj_bpm", None)
    bpm = float(bpm_arg) if bpm_arg else estimate_bpm(feats["flux"], feats["fps"])
    print(f"   🥁 Tempo : {bpm:.1f} BPM | Durée : {_fmt_tc(feats['duration'])}")

    moments, debug = detect_moments(
        feats,
        n_clips=cfg.jumlah_clip,
        bpm=bpm,
        pre_bars=getattr(cfg, "dj_pre_bars", 8),
        post_bars=getattr(cfg, "dj_post_bars", 16),
        min_gap=getattr(cfg, "dj_min_gap", 90.0),
        min_rise_db=getattr(cfg, "dj_min_rise", 6.0),
        include_ranges=parse_ranges(getattr(cfg, "dj_include", None), feats["duration"]),
    )
    clips = build_clip_json(moments, cfg, bpm)

    n_drop = sum(1 for c in clips if c["dj_kind"] == "drop")
    print(f"   ✅ {n_drop} drop(s) + {len(clips) - n_drop} peak(s) sélectionnés :")
    for c in clips:
        print(
            f"      #{c['rank']:<2} {('forcé' if c['dj_forced'] else c['dj_kind']):<5} @ {_fmt_tc(c['dj_anchor_time']):>8}  "
            f"[{_fmt_tc(c['start_time'])} → {_fmt_tc(c['end_time'])}]  {c['alasan'].split('— ')[-1]}"
        )

    analysis_path = os.path.join(cfg.outputs_dir, "dj_analysis.json")
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "bpm": round(bpm, 2),
                "duration": round(feats["duration"], 2),
                "bar_seconds": round(debug["bar"], 4),
                "moments": moments,
            },
            f, indent=2,
        )
    plot_path = os.path.join(cfg.outputs_dir, "dj_energy.png")
    save_energy_plot(debug, moments, feats["duration"], plot_path)
    print(f"   💾 Analyse : {analysis_path}")
    print(f"   🖼️ Courbe  : {plot_path}")
    return clips
