class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 4096;
    this.buffer = new Float32Array(this.bufferSize);
    this.offset = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (input.length > 0) {
      const channelData = input[0];
      
      for (let i = 0; i < channelData.length; i++) {
        this.buffer[this.offset++] = channelData[i];
        
        if (this.offset >= this.bufferSize) {
          // Send downsampled buffer to main thread (convert to Int16)
          const pcm16 = new Int16Array(this.bufferSize);
          for (let j = 0; j < this.bufferSize; j++) {
            const s = Math.max(-1, Math.min(1, this.buffer[j]));
            pcm16[j] = s < 0 ? s * 0x8000 : s * 0x7FFF;
          }
          
          this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
          this.offset = 0;
        }
      }
    }
    return true; // Keep processor alive
  }
}

registerProcessor("pcm-processor", PCMProcessor);
