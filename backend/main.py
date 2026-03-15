import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from uvicorn import run

from vad import VADAnalyzer
from stt import DeepgramSTT
from llm import LLMStreamer
from tts import ElevenLabsTTS

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the static frontend
app.mount("/client", StaticFiles(directory="../frontend"), name="frontend")

class ConversationSession:
    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.vad = VADAnalyzer()
        self.stt = DeepgramSTT()
        self.llm = LLMStreamer()
        self.tts = ElevenLabsTTS()
        
        self.context = []
        self.user_is_speaking = False
        self.ai_task_group = None
        self.tts_recv_task = None  # tracked separately so interrupt_ai() can cancel it
        self.accumulated_transcript = ""

    async def start(self):
        await self.ws.accept()
        stt_online = await self.stt.connect()
        tts_online = await self.tts.connect()
        
        if not stt_online or not tts_online:
            await self.ws.close()
            return
            
        asyncio.create_task(self.stt_listener())
        
        try:
            while True:
                data = await self.ws.receive_bytes()
                await self.handle_audio(data)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if self.ai_task_group:
                self.ai_task_group.cancel()
            await self.stt.disconnect()
            await self.tts.disconnect()

    async def handle_audio(self, pcm_chunk: bytes):
        # 1. Dispatch to VAD
        events = self.vad.process_chunk(pcm_chunk)
        
        # 2. Dispatch to STT
        await self.stt.send_audio(pcm_chunk)
        
        # 3. Handle Events
        for event in events:
            print(f"[VAD] Event: {event}")
            if event == "SPEECH_START":
                self.user_is_speaking = True
                await self.interrupt_ai()
            
            elif event == "SPEECH_END":
                self.user_is_speaking = False
                await self.trigger_ai_response()

    async def stt_listener(self):
        """Constantly listens to the Deepgram WebSocket for complete sentences"""
        while True:
            try:
                text = await self.stt.get_transcript()
                self.accumulated_transcript += " " + text

                # If SPEECH_END already fired before this transcript arrived,
                # trigger AI now (fixes the VAD/STT race condition).
                if not self.user_is_speaking:
                    await self.trigger_ai_response()
            except Exception as e:
                print(f"[STT Listener] Error: {e}")
                break
                
    async def interrupt_ai(self):
        # Cancel the LLM/TTS pipeline task
        if self.ai_task_group and not self.ai_task_group.done():
            self.ai_task_group.cancel()

        # CRITICAL: tts_recv_task is an independent asyncio task — cancelling
        # ai_task_group does NOT stop it. Cancel explicitly so old audio stops.
        if self.tts_recv_task and not self.tts_recv_task.done():
            self.tts_recv_task.cancel()
            self.tts_recv_task = None

        try:
            await self.ws.send_text(json.dumps({"type": "clear"}))
            await self.ws.send_text(json.dumps({"type": "status", "status": "User speaking..."}))
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def trigger_ai_response(self):
        if not self.accumulated_transcript.strip():
            return
            
        user_text = self.accumulated_transcript.strip()
        print(f"[MAIN] Triggering AI with text: {user_text}")
        self.accumulated_transcript = ""
        
        try:
            await self.ws.send_text(json.dumps({
                "type": "transcript",
                "speaker": "user",
                "text": user_text
            }))
            
            await self.ws.send_text(json.dumps({"type": "status", "status": "AI thinking..."}))
        except (WebSocketDisconnect, RuntimeError):
            return # Socket probably closed
        
        # Spawn generating response
        if self.ai_task_group:
            self.ai_task_group.cancel()
        
        self.ai_task_group = asyncio.create_task(self.run_ai_pipeline(user_text))

    async def run_ai_pipeline(self, user_text: str):
        try:
            # ElevenLabs closes the WS after isFinal each turn — must reconnect
            await self.tts.disconnect()
            tts_online = await self.tts.connect()
            if not tts_online:
                print("[TTS] Failed to reconnect — skipping audio for this turn.")

            ai_text_full = ""
            
            # Send context to LLM
            stream_gen = self.llm.generate_response(user_text, self.context)
            
            # Sub-task to read from TTS and send down WS
            async def tts_receiver():
                async for audio_chunk in self.tts.receive_audio():
                    try:
                        await self.ws.send_bytes(audio_chunk)
                    except Exception:
                        break

            self.tts_recv_task = asyncio.create_task(tts_receiver())
            
            # Stream tokens from LLM directly into TTS WebSocket
            print("[LLM] Starting generation...")
            async for chunk in stream_gen:
                print(f"[LLM] Token: {chunk}")
                ai_text_full += chunk
                await self.tts.stream_text(chunk)
                
            print(f"[LLM] Finished. Full text: {ai_text_full}")
            # Signal end of text to TTS
            await self.tts.flush()
            
            # Wait for all audio to be received and forwarded (with safety timeout)
            try:
                await asyncio.wait_for(self.tts_recv_task, timeout=20.0)
            except asyncio.TimeoutError:
                print("[TTS] Receiver timed out after 20s — skipping remaining audio")
                self.tts_recv_task.cancel()
            
            self.context.append({"role": "user", "content": user_text})
            self.context.append({"role": "assistant", "content": ai_text_full})
            
            try:
                await self.ws.send_text(json.dumps({
                    "type": "transcript",
                    "speaker": "ai",
                    "text": ai_text_full
                }))
                
                await self.ws.send_text(json.dumps({"type": "status", "status": "Ready"}))
            except (WebSocketDisconnect, RuntimeError):
                pass
            
        except asyncio.CancelledError:
            # Cleanly stop TTS streaming if interrupted
            await self.tts.disconnect()
            await self.tts.connect() # Re-establish for next turn
        except Exception as e:
            print(f"Pipeline Error: {e}")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session = ConversationSession(websocket)
    await session.start()

if __name__ == "__main__":
    run("main:app", host="0.0.0.0", port=8000, reload=True)
