"""Refine participant action marks to the audible snap transient.

The collector records the microphone as a label-timing reference only. A
spacebar mark lags the snap by a human reaction delay (~0.2-0.8 s), so each
mark is moved back to the sharpest 2-8 kHz transient shortly before it. A
trial is used only when every mark finds a clear, isolated transient and the
EMG burst agrees; otherwise it stays a weak count bag.
"""
from pathlib import Path
import wave
import numpy as np
from scipy.signal import butter, sosfiltfilt
from .common import read_json, json_lines

SEARCH_BEFORE, SEARCH_AFTER = .8, .05
MIN_SNR, MIN_PEAK_RATIO, ISOLATION = 10., 3., .1
EMG_AGREEMENT = .15


def audio_envelope(directory):
    directory = Path(directory)
    reference = read_json(directory/'metadata.json').get('audio_reference')
    if not reference or not (directory/reference['file']).exists():
        return None
    with wave.open(str(directory/reference['file'])) as w:
        fs = w.getframerate()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    blocks = list(json_lines(directory/reference['timing_file']))
    frames = np.array([b['frame'] for b in blocks], dtype=float)
    starts = np.array([b['callback_capture_t']-(b['stream_current_time']-b['adc_time']) for b in blocks])
    # Block timestamps jitter with callback scheduling; the ADC clock itself is linear.
    clock = np.polyfit(frames, starts, 1)
    band = sosfiltfilt(butter(4, [2000, 8000], fs=fs, btype='bandpass', output='sos'), audio)
    window = int(fs*.002)
    envelope = np.sqrt(np.convolve(band*band, np.ones(window)/window, 'same'))
    return np.polyval(clock, np.arange(len(audio))), envelope


def emg_burst_times(features):
    """Last-quarter RMS of each snap window (sum over channels), at the window end time."""
    snaps = [f for f in features if f['kind'] == 'snap']
    channels = len(snaps[0]['x'])//4//5 if snaps else 0
    last = 3*5*channels
    return (np.array([f['t'] for f in snaps]),
            np.array([f['x'][last:last+channels].sum() for f in snaps]))


def refine_snap_onsets(directory, features=None):
    """{trial_id: {'onsets': [...], 'snr': [...], 'peak_ratio': [...], 'emg_offset': [...]}} for trusted trials."""
    directory = Path(directory)
    loaded = audio_envelope(directory)
    if loaded is None:
        return {}
    times, envelope = loaded
    emg = emg_burst_times(features) if features is not None else None
    refined = {}
    for trial in read_json(directory/'guided-trials.json'):
        marks = trial.get('action_marks') or []
        if (trial['kind'] != 'snap' or not trial['confirmed'] or not trial.get('marks_match_count')
                or len(marks) != trial['reported_count'] or not marks):
            continue
        inside = (times >= trial['start']) & (times <= trial['end'])
        background = float(np.median(envelope[inside])) if inside.any() else 0.
        result = {'onsets': [], 'snr': [], 'peak_ratio': [], 'emg_offset': []}
        previous = trial['start']
        for mark in sorted(marks):
            search = (times >= max(mark-SEARCH_BEFORE, previous)) & (times <= mark+SEARCH_AFTER)
            if not search.any() or background <= 0:
                break
            t, e = times[search], envelope[search]
            peak = int(np.argmax(e)); onset = float(t[peak])
            far = np.abs(t-onset) > ISOLATION
            ratio = float(e[peak]/max(e[far].max(), 1e-9)) if far.any() else float('inf')
            snr = float(e[peak]/background)
            offset = None
            if emg is not None:
                near = (emg[0] > onset-SEARCH_BEFORE/2) & (emg[0] < onset+SEARCH_BEFORE/2)
                if not near.any():
                    break
                offset = float(emg[0][near][np.argmax(emg[1][near])]-onset)
            if snr < MIN_SNR or ratio < MIN_PEAK_RATIO or (offset is not None and abs(offset) > EMG_AGREEMENT):
                break
            result['onsets'].append(onset); result['snr'].append(snr)
            result['peak_ratio'].append(ratio); result['emg_offset'].append(offset)
            previous = onset+ISOLATION
        if len(result['onsets']) == len(marks):
            refined[trial['id']] = result
    return refined
