"""Synthetic wiring fixtures, never evidence of real recognition performance."""
from pathlib import Path
import json
import uuid
import numpy as np
from .common import write_json


def make_session(directory, seed=1):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(seed)
    fs, duration = 2048, 100.
    t = np.arange(int(duration*fs))/fs
    ann = []
    x = rng.normal(0, 10, (len(t), 8))
    open_gain = np.array([110, 70, 20, 35, 90, 20, 30, 65])
    fist_gain = np.array([20, 35, 110, 90, 25, 100, 80, 30])
    def interval(label, a, b, trial):
        ann.append({"id": uuid.uuid4().hex, "label": label, "start": a, "end": b,
                    "trial_id": trial, "verified": True, "notes": "SYNTHETIC wiring fixture"})
    def event(label, stamp, trial):
        interval(label, stamp, stamp, trial)
    def state(label, a, b, trial):
        interval(label, a, b, trial)
        ix = (t >= a) & (t <= b)
        if label != "none":
            gain = open_gain if label == "open" else fist_gain
            x[ix] += rng.normal(size=(ix.sum(), 8))*gain*rng.uniform(.9, 1.1)
    for rep in range(3):
        for k, label in enumerate(("none", "open", "fist")):
            a = rep*12 + k*4 + .5
            state(label, a, a+3, f"state-{rep}-{label}")
    for k in range(8):
        a, trial = 37+k*2, f"snap-{k}"
        interval("hard_negative", a, a+1.8, trial)
        stamp = a+.9
        event("snap", stamp, trial)
        ix = (t >= stamp) & (t < stamp+.05)
        burst = np.exp(-(t[ix]-stamp)*35)[:,None]
        x[ix] += burst*rng.normal(size=(ix.sum(), 8))*np.array([700, 300, 900, 100, 500, 100, 60, 300])
    # Paired Quest trajectories and muscle-state intervals for complete actions.
    for rep in range(3):
        a = 56+rep*4
        state("fist", a+.6, a+2.8, f"sword-{rep}")
        event("sword_cast", a+1.1, f"sword-{rep}")
        state("open", a+2.8, a+3.2, f"sword-{rep}")
        event("sword_dismiss", a+2.9, f"sword-{rep}")
        a = 69+rep*3
        state("open", a, a+2.5, f"shield-{rep}")
        event("shield_boost", a+1.1, f"shield-{rep}")
        a = 79+rep*4
        interval("hard_negative", a, a+3.5, f"fireball-{rep}")
        event("snap", a+.5, f"fireball-{rep}")
        event("fireball_spawn", a+.58, f"fireball-{rep}")
        event("fireball_throw", a+1.8, f"fireball-{rep}")
        ix = (t >= a+.5) & (t < a+.55)
        x[ix] += np.exp(-(t[ix]-a-.5)*35)[:,None]*rng.normal(size=(ix.sum(),8))*np.array([700,300,900,100,500,100,60,300])
    interval("hard_negative", 0, 99.9, "whole-session-snap-negatives")
    interval("hip_calibration", 54, 55.5, "hip")
    interval("background", 93, 99.5, "background")
    state("none", 93, 99.5, "background")
    chest = np.array([0., 1.4, 0.])
    def position(stamp):
        p = np.array([.2, -.1, .3])
        if 54 <= stamp < 55.6:
            p = np.array([-.23,-.38,0])
        for rep in range(3):
            a = 56+rep*4
            if a <= stamp <= a+2.8:
                phase = np.clip((stamp-a-.8)/.8, 0, 1)
                p = np.array([-.23, -.38, 0]) + phase*np.array([.6,.75,.1])
            a = 69+rep*3
            if a <= stamp < a+2.5:
                phase = np.clip((stamp-a-1)/.25, 0, 1)
                p = np.array([.2, -.1, .2 + .5*phase**2])
            a = 79+rep*4
            if a <= stamp < a+3.5:
                phase = np.clip((stamp-a-1.65)/.3, 0, 1)
                p = np.array([.2, -.1 + .1*phase, .2+.7*phase**2])
        return (chest+p).tolist()
    records = []
    raw = np.clip(np.rint(32768+x), 0, 65535).astype(int)
    for i in range(0, len(t), 16):
        end = float(t[min(i+15,len(t)-1)])
        records.append({"kind": "emg", "t": end, "received": end+.002, "samples": raw[i:i+16].tolist(),
                        "source_seq": i//16, "gap": False, "timing": "synthetic"})
    for seq, stamp in enumerate(np.arange(0,duration,1/60)):
        pose = {"hand": {"pos": position(stamp), "rot": [1,0,0,0], "palm_normal": [0,0,1], "valid": not (36 <= stamp < 53.5), "confidence": 1},
                "chest": {"pos": chest.tolist(), "rot": [1,0,0,0], "valid": True, "confidence": 1},
                "opponent_direction": [0,0,1], "frame_id": "synthetic"}
        records.append({"kind": "pose", "t": float(stamp), "received": float(stamp+.002), "seq": seq, "timing": "synthetic", "pose": pose})
    records.sort(key=lambda r:r["received"])
    with (directory/"streams.jsonl").open("w") as stream:
        for row in records:
            stream.write(json.dumps(row,separators=(",", ":"))+"\n")
    write_json(directory/"metadata.json", {"schema":1,"id":directory.name,"subject":"synthetic-player", "side":"right",
                                          "synthetic":True,"origin_monotonic":0,"time_basis":"synthetic seconds"})
    write_json(directory/"annotations.json", ann)
    return directory
