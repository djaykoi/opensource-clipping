"""Mode DJ : le premier titre forcé est le clip n°1 et ne déborde jamais.

Set synthétique de 14 min à 124 BPM. Le premier titre (0:00-6:00) a son drop à
5:40, juste avant la fin du titre, et il est plus calme que la suite : sans
forçage il ne serait jamais choisi, et une fenêtre naïve déborderait sur le
titre suivant.

    python tests/test_dj_first_track.py      # ou : pytest tests/
"""

import os
import sys
import types

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipping import dj_mode as dj  # noqa: E402

BPM = 124.0
FIRST_TRACK = "0:00-6:00"


def _synthetic_set(duration=14 * 60):
    sr, beat = dj.SR, 60 / BPM
    t = np.arange(int(duration * sr)) / sr
    rng = np.random.default_rng(0)
    breakdown = ((t >= 310) & (t < 340)) | ((t >= 480) & (t < 510)) | ((t >= 660) & (t < 690))
    phase = (t % beat) / beat
    kick = np.sin(2 * np.pi * 55 * t) * np.exp(-phase * 12) * ~breakdown
    gain = np.where(t < 360, 0.6, 1.0)  # premier titre plus calme que la suite
    hats = 0.05 * rng.standard_normal(t.size) * (((t % (beat / 2)) / (beat / 2)) < 0.1)
    pad = 0.05 * np.sin(2 * np.pi * 440 * t)
    return (gain * kick + hats + pad).astype(np.float32)


_FEATS = None


def _features():
    global _FEATS
    if _FEATS is None:
        _FEATS = dj.compute_features(_synthetic_set())
    return _FEATS


def _detect(specs, n_clips=4):
    feats = _features()
    return dj.detect_moments(
        feats, n_clips=n_clips, bpm=BPM, pre_bars=8, post_bars=16, min_gap=90,
        min_rise_db=6.0, include_ranges=dj.parse_ranges(specs, feats["duration"]),
    )


def test_first_track_is_clip_one_and_stays_inside():
    moments, _ = _detect([FIRST_TRACK])
    cfg = types.SimpleNamespace(dj_title="Hello World Mix", dj_include_label="Premier titre",
                                durasi_hook=3)
    clips = dj.build_clip_json(moments, cfg, BPM)
    c1 = clips[0]
    assert c1["rank"] == 1 and c1["dj_forced"]
    assert "Premier titre" in c1["title_inggris"]
    assert 0 <= c1["start_time"] <= c1["dj_anchor_time"] < c1["end_time"] <= 360
    assert c1["hook_start_time"] < c1["end_time"]
    assert sum(c["dj_forced"] for c in clips) == 1


def test_forced_window_keeps_full_length():
    moments, debug = _detect([FIRST_TRACK])
    m = next(m for m in moments if m.get("forced"))
    assert m["end_time"] - m["start_time"] >= 23 * debug["bar"]  # 24 mesures, ±1


def test_edge_ranges_stay_inside():
    for specs in (["0:00-0:40"], ["5:30-6:00"], [FIRST_TRACK, "8:00-9:00"]):
        moments, _ = _detect(specs, n_clips=3)
        for m in (m for m in moments if m.get("forced")):
            rs, re_ = m["range"]
            assert rs <= m["start_time"] <= m["anchor"] < m["end_time"] <= re_ + 1e-6, (specs, m)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"✅ {name}")
