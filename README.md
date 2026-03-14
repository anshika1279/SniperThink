# Real-Time Voice Conversation Architecture

This project is a raw implementation of a low-latency, bidirectional real-time voice AI system built purely from foundational primitives (FastAPI, WebSockets, WebRTC VAD, AudioWorklets, streaming STT and token-level streaming TTS). 

As per the constraints, **no managed voice platforms** (like LiveKit, VAPI, Pipecat, etc.) were used to orchestrate the pipeline.

## 1. Architecture

- **Frontend (Browser):**
  Uses the modern and non-deprecated WebAudio `AudioWorkletNode` via `audio-processor.js` to continuously capture microphone data as `Float32` PCM without the main thread stuttering. It transposes the buffers into `Int16` 16kHz frames and streams them over a persistent WebSocket connection natively.
  
- **Backend (Python FastAPI):**
  A robust asynchronous WebSocket gateway that pipes incoming binary chunks simultaneously into:
  1. A `webrtcvad` (WebRTC) loop sliced into 30ms frames for precise turn-detection.
  2. A Deepgram WebSocket Streaming connection (`stt.py`) for real-time transcription.

- **The Voice Pipeline orchestration (`main.py`):**
  The user speaks. `webrtcvad` yields `SPEECH_START` and `SPEECH_END`. When speech completes, the backend triggers a Google Gemini (e.g. `gemini-2.0-flash`) streaming API request.
  As text tokens rapidly yield, they are immediately funneled into ElevenLabs `WebSockets` TTS Endpoint, which immediately returns PCM `Int16` audio chunks down the same WebSocket back to the browser.
  
## 2. Design Decisions

- **Token-Level TTS over WebSockets**: The user challenged the batch TTS approach. We've opted into an ElevenLabs pure-streaming WS implementation (`tts.py`). Token-by-token streaming is achieved by pipelining LLM tokens into the WS, reducing Time-To-First-Byte (TTFB) significantly.
- **WebRTC VAD over RMS**: VAD endpoint detection utilizes `webrtcvad` giving high-quality, aggressive silence gap evaluation avoiding false detections on background noise.
- **AudioWorklets over ScriptProcessorNode**: Implemented proper Web Audio context processor yielding a true 16kHz reliable sample stream avoiding WebAPI deprecations.

## 3. Latency Considerations

- **Streaming Every Step**: The system incurs practically zero batching.
    - User audio chunks → STT WebSocket streams.
    - Interim partials / final STT → LLM generation.
    - LLM Token chunks → TTS WebSocket Text Streaming.
    - TTS Audio WebSocket Chunks → Browser Playback Buffer.
  This allows overlapping network I/O bounds rather than sequential request bounds, cutting total theoretical latency from ~2-3 seconds down to under ~500-800ms.

## 4. Known Trade-Offs

- **No Dedicated Jitter Buffer**: The frontend simply plays chunks with a minimal delay `0.05` offset. In a heavily congested network, playback might pop or crack if frames arrive late. A professional WebRTC architecture provides explicit packet jitter buffering.
- **VAD Turn Interruption Delay**: While `SPEECH_START` instantly sends a `clear` command to the UI, there's inherently a round-trip delay from the STT understanding the interruption vs. dropping current processing. It stops the LLM/TTS immediately from consuming more credits upon detection.

## 5. No Managed Platforms
This system does not rely on any managed voice orchestration
platforms such as LiveKit, Retell, VAPI, Pipecat, or similar.

All core real-time voice infrastructure — including WebSocket
transport, session management, turn-taking logic, audio
streaming, pipeline orchestration, and interruption handling —
is implemented manually.

External APIs (Deepgram, Google Gemini, ElevenLabs) are used only
for model inference (STT/LLM/TTS).

## Setup Instructions

1. `cd backend`
2. Duplicate `.env.example` (or set up `.env`) with:
    - `GEMINI_API_KEY=`
    - `DEEPGRAM_API_KEY=`
    - `ELEVENLABS_API_KEY=`
3. Run `python -m venv venv`
4. Source `venv/bin/activate` or `venv\Scripts\activate` on Windows
5. `pip install fastapi uvicorn websockets webrtcvad python-multipart python-dotenv google-genai deepgram-sdk elevenlabs`
6. `uvicorn main:app --reload`
7. Open your browser to `http://localhost:8000/client/index.html`
