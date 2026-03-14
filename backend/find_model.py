import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("GEMINI_API_KEY")
print(f"Key starts with: {key[:15] if key else 'MISSING'}")

c = genai.Client(api_key=key)

print("\n=== All available models ===")
models = []
for m in c.models.list():
    models.append(m.name)
    print(m.name)

print(f"\nTotal: {len(models)}")

# Test the first generateContent-compatible model
print("\n=== Testing first flash model with streaming ===")
flash_models = [m for m in models if 'flash' in m and 'audio' not in m]
if flash_models:
    test_model = flash_models[0]
    print(f"Testing: {test_model}")
    try:
        for chunk in c.models.generate_content_stream(model=test_model, contents="Say hello in 5 words"):
            if chunk.text:
                print(chunk.text, end="", flush=True)
        print("\nSTREAMING WORKS!")
    except Exception as e:
        print(f"\nStreaming error: {e}")
