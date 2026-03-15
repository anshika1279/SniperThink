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
        self.ai_task = None
        self.tts_recv_task = None
        self.accumulated_transcript = ""

        # Every pipeline is tagged with the gen_id current at its creation.
        # Incrementing gen_id instantly marks all older pipelines as stale so
        # they self-terminate on their next iteration check — no waiting for
        # asyncio task cancellation to propagate through the event loop.
        self.gen_id = 0

    # ------------------------------------------------------------------ #
    #  Session lifecycle                                                    #
    # ------------------------------------------------------------------ #

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
                # Must use receive() (not receive_bytes()) so we can handle
                # BOTH binary audio frames AND the text-based interrupt signal
                # that the frontend sends when it detects voice while AI plays.
                message = await self.ws.receive()
                if "bytes" in message and message["bytes"]:
                    await self.handle_audio(message["bytes"])
                elif "text" in message and message["text"]:
                    try:
                        data = json.loads(message["text"])
                        if data.get("type") == "interrupt":
                            print("[MAIN] Frontend interrupt received")
                            await self.interrupt_ai()
                    except json.JSONDecodeError:
                        pass
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if self.ai_task:
                self.ai_task.cancel()
            if self.tts_recv_task:
                self.tts_recv_task.cancel()
            await self.stt.disconnect()
            await self.tts.disconnect()

    # ------------------------------------------------------------------ #
    #  Audio routing                                                        #
    # ------------------------------------------------------------------ #

    async def handle_audio(self, pcm_chunk: bytes):
        events = self.vad.process_chunk(pcm_chunk)
        await self.stt.send_audio(pcm_chunk)

        for event in events:
            print(f"[VAD] Event: {event}")
            if event == "SPEECH_START":
                self.user_is_speaking = True
                await self.interrupt_ai()
            elif event == "SPEECH_END":
                self.user_is_speaking = False
                await self.trigger_ai_response()

    async def stt_listener(self):
        """Constantly listens to the Deepgram WebSocket for complete sentences."""
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

    # ------------------------------------------------------------------ #
    #  Core: shared pipeline teardown                                       #
    # ------------------------------------------------------------------ #

    async def _teardown_pipeline(self):
        """
        Fully stops any running AI pipeline and prepares a clean slate.

        Called by BOTH interrupt_ai() and trigger_ai_response() so that
        every new pipeline — whether from a hard interrupt or a normal new
        turn — always gets a UNIQUE gen_id.

        Three layers:
        1. Increment gen_id  — running pipelines see they're stale at their
           next gen_id check and self-exit without waiting for cancellation.
        2. Disconnect TTS    — closes the ElevenLabs WS immediately so the
           tts_recv_task's receive_audio() loop ends at its next iteration.
        3. Cancel + await   — ensures both tasks are truly finished before
           we return, so the caller always starts with a clean slate.
        """
        self.gen_id += 1
        print(f"[MAIN] Teardown — gen_id now {self.gen_id}")

        # Layer 2: kill the ElevenLabs stream immediately
        await self.tts.disconnect()

        # Layer 3: cancel both tasks and wait for them to actually finish
        tasks = [t for t in (self.ai_task, self.tts_recv_task) if t and not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            # return_exceptions=True prevents CancelledError from propagating here
            await asyncio.gather(*tasks, return_exceptions=True)

        self.ai_task = None
        self.tts_recv_task = None

    # ------------------------------------------------------------------ #
    #  Turn control                                                         #
    # ------------------------------------------------------------------ #

    async def interrupt_ai(self):
        """Hard interrupt: wipe transcript, kill pipeline, tell frontend to mute."""
        # Wipe transcript so pre-interrupt Deepgram results don't contaminate
        # the next turn. Without this, old speech bleeds into the new context.
        self.accumulated_transcript = ""

        await self._teardown_pipeline()

        try:
            await self.ws.send_text(json.dumps({"type": "clear"}))
            await self.ws.send_text(json.dumps({"type": "status", "status": "User speaking..."}))
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def trigger_ai_response(self):
        """Start a fresh AI pipeline for the latest transcript."""
        if not self.accumulated_transcript.strip():
            return

        user_text = self.accumulated_transcript.strip()
        self.accumulated_transcript = ""

        # Kill any running pipeline (handles normal turn-switch AND the rapid
        # double-trigger from SPEECH_END + late STT transcript arriving together).
        # _teardown_pipeline increments gen_id so the new pipeline is always unique.
        await self._teardown_pipeline()
        my_gen_id = self.gen_id  # snapshot AFTER increment

        print(f"[MAIN] Starting pipeline {my_gen_id} for: {user_text!r}")

        try:
            await self.ws.send_text(json.dumps({
                "type": "transcript",
                "speaker": "user",
                "text": user_text
            }))
            await self.ws.send_text(json.dumps({"type": "status", "status": "AI thinking..."}))
        except (WebSocketDisconnect, RuntimeError):
            return

        self.ai_task = asyncio.create_task(self.run_ai_pipeline(user_text, my_gen_id))

    # ------------------------------------------------------------------ #
    #  AI pipeline                                                          #
    # ------------------------------------------------------------------ #

    async def run_ai_pipeline(self, user_text: str, gen_id: int):
        """
        Runs LLM → TTS for one turn.

        gen_id: the generation counter snapshot at pipeline creation time.
        Before sending any audio chunk or LLM token, we check
        `self.gen_id != gen_id`. The moment a newer pipeline starts (or an
        interrupt fires), gen_id increments and this pipeline self-terminates
        on its very next iteration — no waiting for task cancellation.
        """
        try:
            # Reconnect TTS — each turn needs a fresh ElevenLabs WS connection.
            # Note: _teardown_pipeline already disconnected TTS, so connect() here
            # always starts from a clean state. Do NOT reconnect in CancelledError
            # handler — that races with the next pipeline's own connect().
            tts_online = await self.tts.connect()
            if not tts_online:
                print(f"[PIPELINE {gen_id}] TTS connect failed — skipping.")
                return

            # Bail if superseded during the TTS connect round-trip
            if self.gen_id != gen_id:
                print(f"[PIPELINE {gen_id}] Superseded after TTS connect — aborting.")
                await self.tts.disconnect()
                return

            ai_text_full = ""
            stream_gen = self.llm.generate_response(user_text, self.context)

            # Sub-task: read audio from ElevenLabs and forward to browser
            async def tts_receiver():
                async for audio_chunk in self.tts.receive_audio():
                    # Self-terminate if a newer pipeline is running
                    if self.gen_id != gen_id:
                        print(f"[TTS RECV {gen_id}] Superseded — dropping audio.")
                        break
                    try:
                        await self.ws.send_bytes(audio_chunk)
                    except Exception:
                        break

            self.tts_recv_task = asyncio.create_task(tts_receiver())

            # Stream LLM tokens → TTS (self-terminate if superseded)
            print(f"[LLM {gen_id}] Starting generation...")
            async for chunk in stream_gen:
                if self.gen_id != gen_id:
                    print(f"[LLM {gen_id}] Superseded — stopping token feed.")
                    break
                ai_text_full += chunk
                await self.tts.stream_text(chunk)

            # Completed without interruption
            if self.gen_id == gen_id:
                print(f"[LLM {gen_id}] Done.")
                await self.tts.flush()

                try:
                    await asyncio.wait_for(self.tts_recv_task, timeout=20.0)
                except asyncio.TimeoutError:
                    print(f"[TTS {gen_id}] Receiver timeout — cancelling.")
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
            else:
                # Superseded mid-generation — close TTS without updating context
                await self.tts.disconnect()

        except asyncio.CancelledError:
            # Externally cancelled by _teardown_pipeline.
            # Only disconnect TTS — do NOT reconnect here, the next pipeline
            # handles its own connect() at the top of run_ai_pipeline().
            await self.tts.disconnect()
        except Exception as e:
            print(f"[Pipeline {gen_id}] Error: {e}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session = ConversationSession(websocket)
    await session.start()


if __name__ == "__main__":
    run("main:app", host="0.0.0.0", port=8000, reload=True)