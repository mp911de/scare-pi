"""One never-closing ALSA stream: silence between sounds, so the MAX98357A never clicks.

Sounds are 44.1 kHz stereo 16-bit wav files, decoded once into memory by Sound.load.
A pump thread feeds aplay's stdin; a blocking pipe write paces it. Playing a sound
replaces whatever is playing. aplay's buffer is the latency: roughly 0.1 s.
"""
import subprocess
import threading
import wave

RATE, CHANNELS, WIDTH = 44100, 2, 2
FRAME = CHANNELS * WIDTH
CHUNK_FRAMES = 1024


def load(path):
    with wave.open(str(path), 'rb') as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, CHANNELS, WIDTH):
            raise ValueError(f'{path}: need {RATE} Hz, {CHANNELS} channels, {WIDTH * 8} bit')
        return w.readframes(w.getnframes())


class Mixer:
    def __init__(self, device):
        self.process = subprocess.Popen(
            ['aplay', '-q', '-D', device, '-t', 'raw', '-f', 'S16_LE', '-r', str(RATE),
             '-c', str(CHANNELS), '--buffer-size', str(4 * CHUNK_FRAMES)],
            stdin=subprocess.PIPE, start_new_session=True)  # Ctrl+C reaches us, not aplay
        self.lock = threading.Lock()
        self.pending = b''
        threading.Thread(target=self.pump, daemon=True).start()

    def play(self, pcm):
        with self.lock:
            self.pending = pcm

    def busy(self):
        return bool(self.pending)

    def pump(self):
        size = CHUNK_FRAMES * FRAME
        while True:
            with self.lock:
                out, self.pending = self.pending[:size], self.pending[size:]
            try:
                self.process.stdin.write(out + bytes(size - len(out)))
            except (BrokenPipeError, ValueError):
                return

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=2)
