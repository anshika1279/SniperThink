# Real-Time Voice Conversation Architecture

This project is a low-latency, bidirectional real-time voice AI system built from foundational primitives: FastAPI, WebSockets, WebRTC VAD, AudioWorklets, streaming STT, and token-level streaming TTS.

No managed voice orchestration platforms (LiveKit, VAPI, Pipecat, Retell, etc.) are used.

## 1. Architecture

- **Frontend (Browser)**
Uses `AudioWorkletNode` in `frontend/audio-processor.js` to capture microphone audio continuously without blocking the UI thread. Audio is converted to `Int16` PCM (16kHz) and streamed over a persistent WebSocket. Playback is chunked and interruptible.

- **Backend (FastAPI + WebSocket)**
`backend/main.py` manages each conversation session and routes incoming audio to:
1. `VADAnalyzer` (`backend/vad.py`) for turn detection (`SPEECH_START` / `SPEECH_END`).
2. `DeepgramSTT` (`backend/stt.py`) for live transcription.

- **Voice Pipeline**
After user speech ends, transcript text is sent to the LLM module (`backend/llm.py`). LLM tokens are streamed immediately into `ElevenLabsTTS` (`backend/tts.py`), and synthesized PCM audio is streamed back to the browser in real time.

## 2. LLM Provider Options

This repository currently runs on Gemini by default. Ollama is included as a documented local alternative path.

### Option A: Gemini (Cloud)

- Best for: strongest model quality and cloud-hosted inference.
- Current repository status: this is the default implementation already wired in `backend/llm.py`.
- Required env key: `GEMINI_API_KEY`.

Flow:
`Transcript -> Gemini streaming API -> token stream -> ElevenLabs TTS`

### Option B: Ollama (Local)

- Best for: local/private inference, offline-friendly development, and avoiding LLM per-token cloud cost.
- Current repository status: not implemented in `backend/llm.py` yet; add it by extending `LLMStreamer`.
- Typical local endpoint: `http://localhost:11434`.
- Example local models: `llama3.1:8b`, `qwen2.5:7b`.

Flow:
`Transcript -> Ollama local streaming API -> token stream -> ElevenLabs TTS`

To use Ollama in this project, replace or extend `LLMStreamer` in `backend/llm.py` so `generate_response()` streams from Ollama instead of Gemini while keeping the same async token-yield contract used by `main.py`.

Current behavior in code:
- `ConversationSession` always instantiates `LLMStreamer()` from `backend/llm.py`.
- `LLMStreamer` currently uses `google-genai` streaming only.

## 3. Design Decisions

- **Token-level pipeline**
LLM output is streamed token-by-token and forwarded directly to TTS to reduce first-audio latency.

- **Dual interruption path with hard teardown**
Interrupts are detected both server-side (WebRTC VAD events) and client-side (mic energy threshold while AI audio is playing). Frontend sends `{"type":"interrupt"}` immediately.

`backend/main.py` uses a shared `_teardown_pipeline()` path that:
- increments a generation counter (`gen_id`) so older pipelines self-terminate,
- disconnects ElevenLabs WebSocket immediately,
- cancels and awaits both AI and TTS receiver tasks.

This ensures stale audio is not sent after an interrupt or rapid turn switch.

- **WebRTC VAD over basic RMS-only thresholding**
`webrtcvad` improves turn-taking robustness in noisy conditions.

- **AudioWorklet over deprecated ScriptProcessorNode**
Gives stable low-latency capture and better thread separation.

## 4. Latency Considerations

Each stage is streamed continuously, not batched:

- Mic PCM chunks -> backend WebSocket
- PCM chunks -> Deepgram streaming STT
- Final transcript -> streaming LLM generation
- LLM tokens -> ElevenLabs streaming TTS
- TTS audio chunks -> browser playback queue

Additionally, interruption latency is reduced by:
- client-side early interrupt JSON event,
- server-side VAD confirmation,
- `gen_id` stale-pipeline checks before token/audio forwarding.

This overlap of network and compute stages significantly reduces perceived response latency.

## 5. Known Trade-Offs

- **No full jitter buffer implementation**
Very poor networks may introduce playback pops.

- **TTS startup floor**
ElevenLabs model behavior adds a small startup delay before first audio.

- **RAG is a PoC module**
`backend/rag.py` is keyword-based; production RAG should use vector retrieval.

- **Gemini vs Ollama trade-off**
Gemini generally gives stronger output quality and consistency; Ollama gives local control/privacy but quality and speed depend on local hardware/model.

- **Ollama requires code integration**
README documents Ollama flow, but runtime provider switching is not wired in current code yet.

## 6. No Managed Platforms

All transport, sessioning, turn-taking, interruption handling, and streaming orchestration are implemented directly in this codebase.

External services are used only for model inference.

## 7. Setup

### Common setup

1. `cd backend`
2. Create and activate a virtual environment.
3. Install dependencies:
  `pip install fastapi uvicorn websockets webrtcvad python-multipart python-dotenv google-genai deepgram-sdk`
4. Copy env template:
  Windows PowerShell: `Copy-Item .env.example .env`
  Mac/Linux: `cp .env.example .env`

### Run with Gemini (cloud, default)

Set these in `backend/.env`:

- `GEMINI_API_KEY=...`
- `DEEPGRAM_API_KEY=...`
- `ELEVENLABS_API_KEY=...`

Start server:
`uvicorn main:app --reload`

Open:
`http://localhost:8000/client/index.html`

### Run with Ollama (local LLM alternative)

1. Install Ollama and pull a model:
  - `ollama pull llama3.1:8b`
2. Start Ollama service locally.
3. Update `backend/llm.py` to stream from Ollama (manual code change; no runtime switch is implemented yet).
4. Keep using existing STT/TTS keys in `.env`:
  - `DEEPGRAM_API_KEY=...`
  - `ELEVENLABS_API_KEY=...`
5. Start server:
  - `uvicorn main:app --reload`

## 8. Future Option: Provider Switch (Not Implemented)

If you later want both options selectable at runtime, you can add:

- `LLM_PROVIDER=gemini` or `LLM_PROVIDER=ollama`
- `OLLAMA_BASE_URL=http://localhost:11434`
- `OLLAMA_MODEL=llama3.1:8b`

Then instantiate the appropriate provider in `backend/llm.py` while preserving the same async streaming interface.

Current repository behavior: Gemini path is implemented; provider switching is documentation-only at this stage.
