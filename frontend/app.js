let localStream = null;
let audioContext = null;
let processor = null;
let websocket = null;

let isPlaying = false;
let audioQueue = [];
let nextStartTime = 0;
let checkQueueTimer = null;
let audioGate = true; // false = drop incoming audio (AI was interrupted)

const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const connectionIndicator = document.getElementById('connection-status');
const aiStatus = document.getElementById('ai-status');
const transcriptBox = document.getElementById('transcript');

function updateStatus(statusStr) {
    aiStatus.textContent = statusStr;
}

function appendTranscript(text, type) {
    const div = document.createElement('div');
    div.className = `message ${type}`;
    div.textContent = text;
    transcriptBox.appendChild(div);
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
}

// Websocket Handling
const WS_URL = 'ws://localhost:8000/ws';

function connectWebSocket() {
    return new Promise((resolve, reject) => {
        websocket = new WebSocket(WS_URL);
        websocket.binaryType = 'arraybuffer';
        
        websocket.onopen = () => {
            connectionIndicator.classList.remove('offline');
            connectionIndicator.classList.add('online');
            connectionIndicator.querySelector('.text').textContent = 'Connected';
            resolve();
        };

        websocket.onclose = () => {
            connectionIndicator.classList.remove('online');
            connectionIndicator.classList.add('offline');
            connectionIndicator.querySelector('.text').textContent = 'Disconnected';
            stopCall();
        };

        websocket.onmessage = async (event) => {
            if (typeof event.data === 'string') {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'clear') {
                        // User interrupted — close gate so stale audio is dropped
                        audioGate = false;
                        clearPlaybackQueue();
                        updateStatus('Listening...');
                    } else if (data.type === 'transcript') {
                        appendTranscript(data.text, data.speaker); // speaker = 'user' or 'ai'
                    } else if (data.type === 'status') {
                        if (data.status === 'AI thinking...') {
                            audioGate = true; // new turn — allow audio again
                        }
                        updateStatus(data.status);
                    }
                } catch(e) { console.error("Error parsing message", e); }
            } else {
                // Binary Data (Audio from AI) — drop if gate is closed (interrupted)
                if (!audioGate) return;
                const audioData = new Int16Array(event.data);
                queueAudio(audioData);
            }
        };

        websocket.onerror = (err) => {
            console.error("WS Error:", err);
            reject(err);
        };
    });
}

// Playback Logic
function clearPlaybackQueue() {
    audioQueue = [];
    nextStartTime = audioContext.currentTime;
}

function queueAudio(pcm16Data) {
    if (!audioContext) return;
    
    // Convert Int16 to Float32
    const float32Data = new Float32Array(pcm16Data.length);
    for (let i = 0; i < pcm16Data.length; i++) {
        float32Data[i] = pcm16Data[i] / 32768.0;
    }

    const audioBuffer = audioContext.createBuffer(1, float32Data.length, 16000); // Wait, ElevenLabs streams in 16k or 24k? Let's assume backend resamples to 16k
    audioBuffer.getChannelData(0).set(float32Data);
    
    // Play with small delay to prevent clicking if chunks arrive fast
    if (audioContext.currentTime > nextStartTime) {
        nextStartTime = audioContext.currentTime + 0.05; 
    }

    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);
    source.start(nextStartTime);
    
    nextStartTime += audioBuffer.duration;
}

// Capture Logic
async function startAudioCapture() {
    localStream = await navigator.mediaDevices.getUserMedia({ audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
        sampleRate: 16000
    }});

    audioContext = new AudioContext({ sampleRate: 16000 });
    await audioContext.audioWorklet.addModule('audio-processor.js');

    const source = audioContext.createMediaStreamSource(localStream);
    processor = new AudioWorkletNode(audioContext, 'pcm-processor');

    processor.port.onmessage = (e) => {
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.send(e.data); // Int16Array ArrayBuffer
        }
    };

    source.connect(processor);
    processor.connect(audioContext.destination); 
    // It's connected to destination just to keep pipeline alive, but the processor itself doesn't output audio data to destination
}

async function startCall() {
    btnStart.disabled = true;
    updateStatus('Connecting...');
    try {
        await connectWebSocket();
        await startAudioCapture();
        btnStop.disabled = false;
        updateStatus('Listening...');
        appendTranscript('System connected.', 'system');
    } catch(err) {
        alert("Failed to connect: " + err.message);
        btnStart.disabled = false;
        updateStatus('Ready');
    }
}

function stopCall() {
    if (processor) processor.disconnect();
    if (audioContext) audioContext.close();
    if (localStream) localStream.getTracks().forEach(t => t.stop());
    if (websocket) websocket.close();

    processor = null;
    audioContext = null;
    localStream = null;
    websocket = null;

    btnStart.disabled = false;
    btnStop.disabled = true;
    updateStatus('Ready');
    appendTranscript('Call ended.', 'system');
}

btnStart.addEventListener('click', startCall);
btnStop.addEventListener('click', stopCall);
