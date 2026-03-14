### Problem Statement
Your task is to design and build a complete real-time voice conversation system that runs in
a web browser and supports low-latency, bidirectional audio communication.
The objective is to architect the core voice AI infrastructure from scratch, focusing on system
design, streaming, and latency control.
This is not a UI exercise. This is a systems engineering problem.
---

### Core Requirements

## Frontend (Browser)
● Real-time audio capture from microphone
● Audio transport to backend (streaming, not batch uploads)
● Real-time audio playback
● Handle interruptions (user speaking while AI is responding)
## Backend
● WebSocket-based gateway for audio streaming
● End-to-end voice processing pipeline
● Proper session handling and stream orchestration
● Robust interruption and turn-taking logic
---

### Key Constraints (Strict)
You must NOT use any managed or pre-built voice AI platforms, including but not limited to:
● LiveKit (Voice)
● Pipecat
● Daily.co
● Retell AI
● VAPI
● Omnidim
● Bolna
● Any similar abstraction that hides core voice infrastructure
You are expected to build the foundational pipeline yourself.
---

### Evaluation Criteria
We will evaluate you on:
● A working system
● System design clarity
● Latency management strategy
● Handling of real-time audio streaming
● Your understanding of fundamental voice communication challenges
Clean, simple, and well-reasoned solutions are preferred over over-engineered ones.
---

### Bonus (Optional)
● Implement RAG (Retrieval-Augmented Generation) so the system can respond
based on a provided knowledge base.
● Focus on architecture and correctness rather than dataset size.
---
Submission Expectations
● Source code
● Clear README explaining:
1. Architecture
2. Design decisions
3. Latency considerations
4. Known trade-offs
● Basic instructions to run the system locally