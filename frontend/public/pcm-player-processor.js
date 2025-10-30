// Minimal pull-based PCM player for 24 kHz mono Float32 audio.
// Main thread posts messages:
// - { type: 'push', chunk: Float32Array }  // enqueue audio samples
// - { type: 'clear' }                      // drop all queued samples immediately
// - { type: 'setPlaying', playing: boolean } // gate output; false => silence
//
// This avoids pre-scheduling buffers so "stop" can cut output in the next render quantum.

class PCMQueue {
  constructor() {
    this.buffers = [];   // Array<Float32Array>
    this.readIndex = 0;  // position within the head buffer
    this.length = 0;     // total samples available
  }
  push(f32) {
    if (f32 && f32.length) {
      this.buffers.push(f32);
      this.length += f32.length;
    }
  }
  clear() {
    this.buffers = [];
    this.readIndex = 0;
    this.length = 0;
  }
  // Pop up to 'n' samples; return count copied into 'out'
  popInto(out) {
    let wanted = out.length;
    let written = 0;
    while (wanted > 0 && this.buffers.length > 0) {
      const head = this.buffers[0];
      const remainInHead = head.length - this.readIndex;
      const toCopy = Math.min(remainInHead, wanted);
      if (toCopy > 0) {
        out.set(head.subarray(this.readIndex, this.readIndex + toCopy), written);
        this.readIndex += toCopy;
        written += toCopy;
        wanted -= toCopy;
      }
      if (this.readIndex >= head.length) {
        this.buffers.shift();
        this.readIndex = 0;
      }
    }
    return written;
  }
}

class PCMPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = new PCMQueue();
    this.playing = false;

    this.port.onmessage = (e) => {
      const data = e.data || {};
      switch (data.type) {
        case 'push': {
          // Expect a Float32Array; if transferred as ArrayBuffer, reconstruct.
          let chunk = data.chunk;
          if (chunk && !(chunk instanceof Float32Array) && chunk.buffer) {
            chunk = new Float32Array(chunk.buffer);
          }
          if (chunk instanceof Float32Array && chunk.length > 0) {
            this.queue.push(chunk);
          }
          break;
        }
        case 'clear':
          this.queue.clear();
          break;
        case 'setPlaying':
          this.playing = !!data.playing;
          break;
        default:
          break;
      }
    };
  }

  process(_inputs, outputs) {
    const outCh = outputs[0][0]; // mono
    if (!outCh) return true;

    if (!this.playing) {
      outCh.fill(0);
      return true;
    }

    // Pull from the queue; zero-fill if underflow.
    const frames = outCh.length;
    const written = this.queue.popInto(outCh);
    if (written < frames) {
      outCh.fill(0, written);
    }
    return true; // keep alive
  }
}

registerProcessor('pcm-player-processor', PCMPlayerProcessor);