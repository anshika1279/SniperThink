import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

class LLMStreamer:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            print("WARNING: GEMINI_API_KEY missing.")
        
        self.client = genai.Client(api_key=self.api_key)
        self.model_id = "models/gemini-2.0-flash-exp"
        print(f"[LLM] Initializing with model: {self.model_id}")
        self.system_prompt = "You are a helpful, conversational AI assistant. Keep responses brief, natural, and conversational."
    
    async def generate_response(self, text: str, context: list):
        """
        Yields tokens/chunks as they arrive from Gemini.
        context is a list of {"role": "...", "content": "..."} history.
        """
        # Convert context format to Gemini's history format
        history = []
        for msg in context:
            role = 'user' if msg['role'] == 'user' else 'model'
            history.append(types.Content(role=role, parts=[types.Part(text=msg['content'])]))
            
        try:
            # Prepare contents with the current message
            contents = history + [types.Content(role='user', parts=[types.Part(text=f"{self.system_prompt}\n\nUser: {text}")])]
            
            # Using generate_content_stream for low latency
            response = self.client.models.generate_content_stream(
                model=self.model_id,
                contents=contents
            )
            
            for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            print(f"Gemini LLM Error: {e}")
            yield "Sorry, I encountered an error with the brain module."
