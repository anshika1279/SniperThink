import os
import asyncio
import json
import base64
import websockets
from dotenv import load_dotenv

load_dotenv()

class ElevenLabsTTS:
    def __init__(self, voice_id="EXAVITQu4vr4xnSDxMaL"): # Example voice ID
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        self.voice_id = voice_id
        # We use the ElevenLabs WebSocket API for text-in, audio-out streaming
        self.ws_url = f"wss://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream-input?model_id=eleven_turbo_v2_5&output_format=pcm_16000"
        self.ws = None

    async def connect(self):
        try:
            self.ws = await websockets.connect(self.ws_url)
            # Send initial configuration
            init_msg = {
                "text": " ",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
                "xi_api_key": self.api_key,
            }
            await self.ws.send(json.dumps(init_msg))
            return True
        except Exception as e:
            print(f"TTS Connection error: {e}")
            return False

    async def stream_text(self, text_chunk: str):
        if self.ws and text_chunk:
            try:
                msg = {"text": text_chunk, "try_trigger_generation": True}
                await self.ws.send(json.dumps(msg))
            except websockets.exceptions.ConnectionClosed:
                pass

    async def flush(self):
        # Sends empty string to demarcate end of text stream
        if self.ws:
            try:
                await self.ws.send(json.dumps({"text": ""}))
            except websockets.exceptions.ConnectionClosed:
                pass

    async def receive_audio(self):
        """Yields raw PCM chunks from Elevenlabs"""
        if not self.ws:
            return
            
        try:
            while True:
                try:
                    # Timeout so we never hang if ElevenLabs stops sending
                    response = await asyncio.wait_for(self.ws.recv(), timeout=8.0)
                except asyncio.TimeoutError:
                    print("[TTS] recv timeout — assuming stream ended")
                    break

                data = json.loads(response)

                # Handle ElevenLabs error messages
                if data.get("error"):
                    print(f"[TTS] ElevenLabs error: {data['error']}")
                    break

                if data.get("audio"):
                    audio_b64 = data["audio"]
                    yield base64.b64decode(audio_b64)
                    
                if data.get("isFinal"):
                    break
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"TTS Receive error: {e}")

    async def disconnect(self):
        if self.ws:
            await self.ws.close()
            self.ws = None
