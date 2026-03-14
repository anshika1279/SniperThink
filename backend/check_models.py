import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

def list_models():
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    
    print("Listing ALL available models:")
    try:
        found_models = []
        for model in client.models.list():
            print(f"  - {model.name}")
            found_models.append(model.name)
        
        # Try the first one that looks like a flash model if gemini-1.5-flash failed
        target = "models/gemini-1.5-flash"
        if target not in found_models:
             # Try without the models/ prefix just in case
             target = found_models[0] if found_models else None
        
        if target:
            print(f"Testing generation with {target}...")
            response = client.models.generate_content(
                model=target,
                contents="Hi"
            )
            print(f"Success! Response: {response.text}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_models()
