class SimpleRAG:
    """
    A minimalist in-memory Retrieval-Augmented Generation module.
    For a production system, this would use vector embeddings (e.g., FAISS + OpenAI text-embedding-ada-002).
    """
    def __init__(self):
        self.knowledge_base = {
            "voice ai": "Voice AI systems require extremely low latency. Processing text to speech at a token level can reduce latency down to 200 milliseconds.",
            "websocket": "WebSockets provide persistent, low-latency, bi-directional communication exactly required for streaming PCM audio chunks natively without HTTP overhead.",
            "webrtc": "WebRTC is an open framework that enables Real-Time Communications. It includes highly optimized Voice Activity Detection (VAD)."
        }
        
    def get_context(self, query: str) -> str:
        """Finds matching knowledge based on keyword hits in the query."""
        context_snippets = []
        query_lower = query.lower()
        
        for keyword, info in self.knowledge_base.items():
            if keyword in query_lower:
                context_snippets.append(info)
                
        return " ".join(context_snippets)
