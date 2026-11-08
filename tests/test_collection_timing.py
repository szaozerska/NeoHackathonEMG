import json
import os
from types import SimpleNamespace
import time
import wave
import numpy as np
from spelltrain.audio_reference import AudioReference, AUDIO_FILE, TIMING_FILE, BLOCK_FRAMES, SAMPLE_RATE
from spelltrain.terminal_marks import space_presses_until


def test_only_space_keys_become_marks_before_deadline():
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b'a  x')
    announced = []
    presses = space_presses_until(read_fd, time.monotonic()+.1, time.monotonic, announced.append)
    os.close(read_fd); os.close(write_fd)
    assert len(presses) == 2 and announced == presses


class FakeStream:
    def __init__(self, samplerate, channels, dtype, blocksize, callback):
        self.callback = callback; self.device = 3; self.started = False; self.closed = False
        assert (samplerate, channels, dtype, blocksize) == (SAMPLE_RATE, 1, 'int16', BLOCK_FRAMES)
        FakeStream.last = self

    def start(self): self.started = True
    def stop(self): pass
    def close(self): self.closed = True


def test_audio_blocks_are_saved_with_capture_aligned_timing(tmp_path):
    clock = iter([10.5, 10.51])
    audio = AudioReference(tmp_path, capture_start=10., clock=lambda: next(clock),
                           open_stream=FakeStream, device_name=lambda index: f'mic-{index}')
    stream = FakeStream.last
    assert stream.started and audio.device == 'mic-3'
    for adc, overflow, value in ((100.40, False, 7), (100.41, True, -9)):
        block = np.full((BLOCK_FRAMES, 1), value, dtype=np.int16)
        stream.callback(block, BLOCK_FRAMES, SimpleNamespace(inputBufferAdcTime=adc, currentTime=adc+.02),
                        SimpleNamespace(input_overflow=overflow))
    info = audio.finish()
    assert stream.closed and info['frames'] == 2*BLOCK_FRAMES and info['input_overflow_blocks'] == 1
    assert audio.peak == 9
    with wave.open(str(tmp_path/AUDIO_FILE)) as saved:
        assert (saved.getnframes(), saved.getframerate(), saved.getsampwidth()) == (2*BLOCK_FRAMES, SAMPLE_RATE, 2)
    rows = [json.loads(line) for line in (tmp_path/TIMING_FILE).read_text().splitlines()]
    assert [r['frame'] for r in rows] == [0, BLOCK_FRAMES]
    assert np.isclose(rows[0]['callback_capture_t'], .5) and rows[1]['input_overflow']
    assert audio.finish() == info
