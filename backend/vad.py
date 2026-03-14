import webrtcvad

class VADAnalyzer:
    def __init__(self, sample_rate=16000, aggressiveness=3, padding_ms=300, silence_ms=500):
        self.sample_rate = sample_rate
        self.vad = webrtcvad.Vad(aggressiveness)
        # WebRTC VAD supports 10, 20, or 30 ms frames
        self.frame_duration_ms = 30
        self.frame_size_bytes = int(self.sample_rate * (self.frame_duration_ms / 1000.0) * 2) # 16bit = 2 bytes
        self.buffer = bytearray()
        
        self.voiced_frames = 0
        self.silence_frames = 0
        
        self.triggered = False
        self.silence_threshold = silence_ms // self.frame_duration_ms
        self.speech_start_threshold = padding_ms // self.frame_duration_ms

    def process_chunk(self, chunk: bytes):
        """Processes an arbitrary sized PCM chunk, returning events.
        Events can be 'SPEECH_START' or 'SPEECH_END'."""
        self.buffer.extend(chunk)
        events = []
        
        while len(self.buffer) >= self.frame_size_bytes:
            frame = bytes(self.buffer[:self.frame_size_bytes])
            self.buffer = self.buffer[self.frame_size_bytes:]
            
            is_speech = self.vad.is_speech(frame, self.sample_rate)
            
            if is_speech:
                self.voiced_frames += 1
                self.silence_frames = 0
                if not self.triggered and self.voiced_frames > self.speech_start_threshold:
                    self.triggered = True
                    events.append("SPEECH_START")
            else:
                self.silence_frames += 1
                self.voiced_frames = 0
                if self.triggered and self.silence_frames > self.silence_threshold:
                    self.triggered = False
                    events.append("SPEECH_END")
                    
        return events
