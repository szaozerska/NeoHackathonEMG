import json
import wave
import numpy as np
from spelltrain.snap_onsets import refine_snap_onsets


def write_capture(tmp_path, clicks, marks, fs=48000, seconds=6.):
    rng = np.random.default_rng(0)
    audio = rng.normal(0, 20, int(fs*seconds))
    for c in clicks:
        i = int(c*fs); audio[i:i+48] += rng.normal(0, 8000, 48)
    with wave.open(str(tmp_path/'audio.wav'), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fs)
        w.writeframes(np.clip(audio, -32768, 32767).astype(np.int16).tobytes())
    with open(tmp_path/'audio-timing.jsonl', 'w') as f:
        for frame in range(0, len(audio), 480):
            t = frame/fs
            f.write(json.dumps({'frame': frame, 'frames': 480, 'callback_capture_t': t+.03,
                                'adc_time': 100+t, 'stream_current_time': 100+t+.03})+'\n')
    (tmp_path/'metadata.json').write_text(json.dumps({'audio_reference': {'file': 'audio.wav', 'timing_file': 'audio-timing.jsonl'}}))
    (tmp_path/'guided-trials.json').write_text(json.dumps([
        {'id': 'snap-001', 'kind': 'snap', 'confirmed': True, 'reported_count': len(marks), 'marks_match_count': True,
         'action_marks': marks, 'start': .5, 'end': 5.5}]))


def snap_features(times, bursts, channels=8):
    rows = []
    for t in times:
        x = np.ones(20*channels)
        x[15*channels:16*channels] = 50. if any(abs(t-b) < .02 for b in bursts) else 1.
        rows.append({'kind': 'snap', 't': float(t), 'x': x})
    return rows


def test_marks_refine_to_click_that_emg_confirms(tmp_path):
    write_capture(tmp_path, clicks=[2.0, 4.0], marks=[2.35, 4.5])
    features = snap_features(np.arange(.5, 5.5, 1/64), bursts=[2.03, 3.98])
    refined = refine_snap_onsets(tmp_path, features)['snap-001']
    assert np.allclose(refined['onsets'], [2.0, 4.0], atol=.005)
    assert all(abs(o) <= .05 for o in refined['emg_offset'])


def test_trial_without_emg_agreement_or_click_stays_weak(tmp_path):
    write_capture(tmp_path, clicks=[2.0], marks=[2.35])
    assert refine_snap_onsets(tmp_path, snap_features(np.arange(.5, 5.5, 1/64), bursts=[1.6])) == {}
    write_capture(tmp_path, clicks=[], marks=[2.35])
    assert refine_snap_onsets(tmp_path) == {}
