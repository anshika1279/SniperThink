import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# Preferred flash models in priority order (no audio/vision variants)
PREFERRED_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
]


def _pick_best_model(client: genai.Client) -> str:
    """
    Queries the API for available models and returns the best flash model.
    Falls back to the first available flash model if none of the preferred ones match.
    """
    try:
        available = [m.name for m in client.models.list()]
        # Try preferred models first
        for preferred in PREFERRED_MODELS:
            for name in available:
                if preferred in name and "audio" not in name:
                    print(f"[LLM] Auto-selected model: {name}")
                    return name  # return full 'models/...' name
        # Fall back to first non-audio flash model
        flash = [m for m in available if "flash" in m and "audio" not in m]
        if flash:
            print(f"[LLM] Fallback model: {flash[0]}")
            return flash[0]
    except Exception as e:
        print(f"[LLM] Warning: could not list models ({e}), using default.")
    return "gemini-2.0-flash-lite"


class LLMStreamer:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            print("WARNING: GEMINI_API_KEY missing.")

        self.client = genai.Client(api_key=self.api_key)
        self.model_id = _pick_best_model(self.client)
        self.system_prompt = (
            "You are a helpful, conversational AI assistant. "
            "Keep responses brief, natural, and conversational."
        )

    async def generate_response(self, text: str, context: list):
        """
        True async generator that yields text tokens from Gemini one-by-one
        as they arrive, using the native async streaming API.

        Using client.aio.models.generate_content_stream() is critical — it
        returns an AsyncIterator that yields each chunk the moment Gemini
        sends it, allowing us to pipeline tokens directly into ElevenLabs TTS
        without waiting for the full response. This minimises TTFB by ~1-2s
        compared to collecting the entire response first.

        context: list of {"role": "user"|"assistant", "content": "..."} dicts.
        """
        history = []
        for msg in context:
            role = "user" if msg["role"] == "user" else "model"
            history.append(
                types.Content(role=role, parts=[types.Part(text=msg["content"])])
            )

        contents = history + [
            types.Content(
                role="user",
                parts=[types.Part(text=f"{self.system_prompt}\n\nUser: {text}")],
            )
        ]

        try:
            # client.aio is the async namespace of the google-genai SDK.
            # generate_content_stream returns an AsyncIterator — each chunk
            # is yielded the instant Gemini streams it over the network,
            # with no buffering or blocking of the event loop.
            async for chunk in await self.client.aio.models.generate_content_stream(
                model=self.model_id,
                contents=contents,
            ):
                if chunk.text:
                    yield chunk.text

        except Exception as e:
            print(f"Gemini LLM Error: {e}")
            yield "Sorry, I encountered an error with the brain module."
