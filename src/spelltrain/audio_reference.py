"""Microphone reference audio for reviewing snap timing. Never a model input."""
import json
from pathlib import Path
import queue
import threading
import wave
import numpy as np
import sounddevice

SAMPLE_RATE = 48_000
BLOCK_FRAMES = 480
AUDIO_FILE = 'audio.wav'
TIMING_FILE = 'audio-timing.jsonl'


def default_device_name(index):
    return sounddevice.query_devices(index)['name']


class AudioReference:
    """Records mono int16 WAV plus per-block host timing aligned to a capture's clock.

    Each timing row covers frames [frame, frame+frames). Its first sample was
    digitized at callback_capture_t - (stream_current_time - adc_time).
    """

    def __init__(self, directory, capture_start, clock,
                 open_stream=sounddevice.InputStream, device_name=default_device_name):
        self.capture_start = capture_start; self.clock = clock
        self.directory = Path(directory); self.closed = False
        self.frames_written = 0; self.overflows = 0; self.peak = 0
        self.blocks = queue.Queue()
        self.wav = wave.open(str(self.directory/AUDIO_FILE), 'wb')
        self.wav.setnchannels(1); self.wav.setsampwidth(2); self.wav.setframerate(SAMPLE_RATE)
        self.timing = (self.directory/TIMING_FILE).open('x', buffering=1)
        self.writer = threading.Thread(target=self._write_blocks, daemon=True)
        self.writer.start()
        self.stream = open_stream(samplerate=SAMPLE_RATE, channels=1, dtype='int16',
                                  blocksize=BLOCK_FRAMES, callback=self._on_block)
        self.device = device_name(self.stream.device)
        self.stream.start()

    def _on_block(self, indata, frames, time_info, status):
        self.blocks.put((indata.copy(), self.clock(), time_info.inputBufferAdcTime,
                         time_info.currentTime, bool(status.input_overflow)))

    def _write_blocks(self):
        while (block := self.blocks.get()) is not None:
            samples, callback_t, adc_time, current_time, overflow = block
            self.wav.writeframes(samples.tobytes())
            self.timing.write(json.dumps({
                'frame': self.frames_written, 'frames': len(samples),
                'callback_capture_t': callback_t-self.capture_start, 'adc_time': adc_time,
                'stream_current_time': current_time, 'input_overflow': overflow}, separators=(',', ':'))+'\n')
            self.frames_written += len(samples); self.overflows += overflow
            self.peak = max(self.peak, int(np.abs(samples.astype(np.int32)).max()))

    def finish(self):
        if self.closed:
            return self.info()
        self.stream.stop(); self.stream.close()
        self.blocks.put(None); self.writer.join()
        self.wav.close(); self.timing.close(); self.closed = True
        return self.info()

    def info(self):
        return {'file': AUDIO_FILE, 'timing_file': TIMING_FILE, 'sample_rate': SAMPLE_RATE, 'channels': 1,
                'sample_format': 'int16', 'device': self.device, 'frames': self.frames_written,
                'input_overflow_blocks': self.overflows, 'role': 'label_timing_reference_only_never_model_input',
                'time_basis': 'block first sample capture_t = callback_capture_t - (stream_current_time - adc_time)'}
