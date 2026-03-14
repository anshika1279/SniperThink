import asyncio
import os
import json
from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
from dotenv import load_dotenv

load_dotenv()

class DeepgramSTT:
    def __init__(self):
        # We instantiate a Deepgram Client using DEEPGRAM_API_KEY from env
        key = os.getenv("DEEPGRAM_API_KEY")
        if not key:
            print("WARNING: DEEPGRAM_API_KEY missing.")
        
        self.deepgram = DeepgramClient(key)
        self.dg_connection = None
        self.transcript_queue = asyncio.Queue()

    async def connect(self):
        try:
            self.dg_connection = self.deepgram.listen.websocket.v("1")
        except Exception as e:
            print(f"Failed to setup connection: {e}")
            return False

        stt_self = self  # capture outer DeepgramSTT instance before callback shadows it
        loop = asyncio.get_event_loop()  # capture the running loop NOW (in async context, before background thread)

        def on_message(client, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            if len(sentence) == 0:
                return
            
            print(f"[STT] Intermediate: {sentence}")
            
            if result.is_final:
                print(f"[STT] Final Transcript: {sentence}")
                # Deepgram callbacks run on a background thread - use threadsafe bridge
                asyncio.run_coroutine_threadsafe(stt_self.transcript_queue.put(sentence), loop)

        self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)

        options = LiveOptions(
            model="nova-2",
            language="en-US",
            encoding="linear16",
            channels=1,
            sample_rate=16000,
            endpointing=True,
            interim_results=False
        )
        
        res = self.dg_connection.start(options)
        if not res:
            print("Failed to start deepgram WS")
            return False
        return True

    async def send_audio(self, pcm_data: bytes):
        if self.dg_connection:
            try:
                self.dg_connection.send(pcm_data)
            except Exception as e:
                print(f"Error sending audio to STT: {e}")

    async def get_transcript(self):
        return await self.transcript_queue.get()

    async def disconnect(self):
        if self.dg_connection:
            self.dg_connection.finish()
            self.dg_connection = None
