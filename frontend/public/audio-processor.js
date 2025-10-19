class AudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
  }

  floatTo16BitPCM(input) {
    const buffer = new ArrayBuffer(input.length * 2);
    const view = new DataView(buffer);
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]));
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return buffer;
  }

  process(inputs) {
    const input = inputs[0];
    if (input && input[0]) {
      const pcmBuffer = this.floatTo16BitPCM(input[0]);
      this.port.postMessage(pcmBuffer, [pcmBuffer]);
    }
    return true;
  }
}

registerProcessor('audio-processor', AudioProcessor);
