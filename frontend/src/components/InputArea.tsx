import React, { useState, useRef, useEffect } from 'react';
import { Box, TextField, IconButton, CircularProgress, Typography, Stack } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import MicIcon from '@mui/icons-material/Mic';
import StopIcon from '@mui/icons-material/Stop';
import RecordVoiceOverIcon from '@mui/icons-material/RecordVoiceOver';

interface UserData {
  userId: string;
  username: string;
  role: string;
  sessionId: string;
}

interface InputAreaProps {
  sessionId: string | null;
  setSessionId: (id: string) => void;
  addMessage: (sender: 'user' | 'bot', text: string, audioBase64?: string) => void;
  userData: UserData | null;
}

// --- Helper: Convert Float32 → WAV (existing) ---
const encodeWAV = (samples: Float32Array, sampleRate: number): ArrayBuffer => {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };
  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  let idx = 44;
  for (let i = 0; i < samples.length; i++, idx += 2)
    view.setInt16(idx, samples[i] * 0x7fff, true);
  return buffer;
};

const int16ToFloat32 = (int16: Int16Array): Float32Array => {
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 0x7fff;
  return float32;
};

const InputArea: React.FC<InputAreaProps> = ({ sessionId, setSessionId, addMessage, userData }) => {
  const [input, setInput] = useState('');
  const [recording, setRecording] = useState(false);

  // Live talk UI state
  const [liveMode, setLiveMode] = useState(false);
  const [userTranscript, setUserTranscript] = useState('');
  const [botTranscript, setBotTranscript] = useState('');

  // Refs to avoid re-renders causing duplicate connections
  const liveSocketRef = useRef<WebSocket | null>(null);

  // Audio graph
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const captureWorkletRef = useRef<AudioWorkletNode | null>(null); // existing capture node
  const pcmPlayerNodeRef = useRef<AudioWorkletNode | null>(null);  // NEW: pull-based player node

  // Playback/capture control
  const playheadRef = useRef<number>(0); // retained for fallback path
  const outGainRef = useRef<GainNode | null>(null);
  const modelSpeakingRef = useRef<boolean>(false);
  const inResponseRef = useRef<boolean>(false);
  const lastStopAtRef = useRef<number>(0);
  const activeSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set()); // retained for fallback
  const dropChunksRef = useRef<boolean>(false);

  // Stop keywords
  const STOP_RE = /\b(stop|cancel|pause|hold on|wait|quiet|be quiet|silence|shut up)\b/i;
  const isStopPhrase = (s: string) => {
    const t = s.trim().toLowerCase();
    if (t === 'st' || t === 'sto' || t === 'stop' || t === 'stop.' || t === 'stop!') return true;
    return STOP_RE.test(s);
  };

  // === TEXT / SINGLE STT PATH (unchanged) ===
  const sendMessage = async (
    message: string,
    input_type: 'text' | 'speech' = 'text',
    audioBase64?: string
  ) => {
    if (input_type === 'text') addMessage('user', message);

    try {
      const res = await fetch('http://localhost:7071/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          user_id: userData?.userId,
          input_type,
          message: input_type === 'text' ? message : undefined,
          audio_base64: audioBase64,
        }),
      });

      const data = await res.json();
      if (data.session_id) setSessionId(data.session_id);

      if (input_type === 'speech')
        addMessage('user', data.recognized_text || '[Voice message]');

      if (data.reply)
        addMessage('bot', data.reply, data.audio_base64);
      else if (data.error)
        addMessage('bot', `Error: ${data.error}`);
    } catch (err) {
      console.error('Error sending message:', err);
      addMessage('bot', 'Error: Could not reach server.');
    }
  };

  const handleSendClick = () => {
    if (!input.trim()) return;
    sendMessage(input.trim(), 'text');
    setInput('');
  };

  // === OLD MIC RECORD FUNCTIONALITY (unchanged) ===
  const handleMicClick = async () => {
    setRecording(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true }
      });

      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      const chunks: BlobPart[] = [];
      recorder.ondataavailable = e => e.data.size > 0 && chunks.push(e.data);
      recorder.start();
      setTimeout(() => recorder.state === 'recording' && recorder.stop(), 5000);

      recorder.onstop = async () => {
        const blob = new Blob(chunks, { type: 'audio/webm' });
        const buffer = await blob.arrayBuffer();
        const audioCtx = new AudioContext({ sampleRate: 16000 });
        const decoded = await audioCtx.decodeAudioData(buffer);
        const wavBuffer = encodeWAV(decoded.getChannelData(0), 16000);
        const wavBlob = new Blob([wavBuffer], { type: 'audio/wav' });
        const reader = new FileReader();
        reader.onloadend = () => {
          const base64 = reader.result?.toString().split(',')[1];
          if (base64) sendMessage('', 'speech', base64);
        };
        reader.readAsDataURL(wavBlob);
        setRecording(false);
      };
    } catch {
      addMessage('bot', 'Microphone access denied or unavailable.');
      setRecording(false);
    }
  };

  // Hard cut of any currently scheduled output audio (fallback path)
  const hardStopOutput = () => {
    const ctx = audioContextRef.current;
    if (outGainRef.current && ctx) {
      try {
        outGainRef.current.gain.cancelScheduledValues(ctx.currentTime);
        outGainRef.current.gain.setValueAtTime(0.0, ctx.currentTime);
      } catch { /* noop */ }
    }
    // Stop any scheduled buffer-source nodes (fallback path)
    activeSourcesRef.current.forEach(src => {
      try { src.stop(0); } catch { /* already stopped */ }
    });
    activeSourcesRef.current.clear();
    if (ctx) {
      playheadRef.current = ctx.currentTime;
    }
    dropChunksRef.current = true;
    // NEW: also clear ring buffer player immediately
    try {
      const player = pcmPlayerNodeRef.current;
      if (player) {
        player.port.postMessage({ type: 'clear' });
        player.port.postMessage({ type: 'setPlaying', playing: false });
      }
    } catch { /* ignore */ }
  };

  // === Word-by-word reveal helpers (unchanged logic) ===
  const WORD_INTERVAL_MS = 340;
  const PAUSE_PUNCT_MS = 280;
  const PAUSE_COMMA_MS = 160;

  const botTargetRef = useRef<string>('');
  const revealedWordsRef = useRef<string[]>([]);
  const pendingWordsRef = useRef<string[]>([]);
  const revealTimerRef = useRef<number | null>(null);
  const placeholderTimerRef = useRef<number | null>(null);
  const hasReceivedBotWordsRef = useRef<boolean>(false);

  const clearTimer = (ref: React.MutableRefObject<number | null>) => {
    if (ref.current !== null) {
      window.clearTimeout(ref.current);
      ref.current = null;
    }
  };

  const resetBotReveal = () => {
    botTargetRef.current = '';
    revealedWordsRef.current = [];
    pendingWordsRef.current = [];
    hasReceivedBotWordsRef.current = false;
    clearTimer(revealTimerRef);
    clearTimer(placeholderTimerRef);
    setBotTranscript('');
  };

  const scheduleNextReveal = (delay: number = WORD_INTERVAL_MS) => {
    clearTimer(revealTimerRef);
    revealTimerRef.current = window.setTimeout(tickReveal, delay);
  };

  const tickReveal = () => {
    if (pendingWordsRef.current.length === 0) {
      revealTimerRef.current = null;
      return;
    }
    const next = pendingWordsRef.current.shift()!;
    revealedWordsRef.current.push(next);
    setBotTranscript(revealedWordsRef.current.join(' '));

    let delay = WORD_INTERVAL_MS;
    if (/[.?!]$/.test(next)) delay += PAUSE_PUNCT_MS;
    else if (/[,;:]$/.test(next)) delay += PAUSE_COMMA_MS;

    scheduleNextReveal(delay);
  };

  const enqueueBotTranscript = (full: string) => {
    botTargetRef.current = full || '';
    const trimmed = botTargetRef.current.trim();
    const targetWords = trimmed.length ? trimmed.split(/\s+/) : [];
    const revealedCount = revealedWordsRef.current.length;

    const before = pendingWordsRef.current.length;
    for (let i = revealedCount; i < targetWords.length; i++) {
      pendingWordsRef.current.push(targetWords[i]);
    }
    const added = pendingWordsRef.current.length - before;

    if (added > 0) {
      hasReceivedBotWordsRef.current = true;
      clearTimer(placeholderTimerRef);
    }

    if (revealTimerRef.current === null) {
      scheduleNextReveal(WORD_INTERVAL_MS);
    }
  };

  useEffect(() => {
    return () => {
      clearTimer(revealTimerRef);
      clearTimer(placeholderTimerRef);
    };
  }, []);

  // === REALTIME (voice barge-in + scheduled playback + transcripts) ===
  const handleLiveSocketMessage = (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data);

      // New reply boundary -> reset transcript and prepare audio
      if (data.event === 'new_response') {
        inResponseRef.current = true;
        modelSpeakingRef.current = false;
        dropChunksRef.current = false;
        resetBotReveal();

        clearTimer(placeholderTimerRef);
        placeholderTimerRef.current = window.setTimeout(() => {
          if (!hasReceivedBotWordsRef.current) setBotTranscript('…');
        }, 500);

        // Ensure pull player starts fresh for this turn
        if (pcmPlayerNodeRef.current) {
          pcmPlayerNodeRef.current.port.postMessage({ type: 'clear' });
          pcmPlayerNodeRef.current.port.postMessage({ type: 'setPlaying', playing: true });
        }
        return;
      }

      // Optional tool result (unchanged behavior)
      if (data.event === 'tool_result') {
        try {
          if (data.function === 'find_coffee_shops') {
            const places = (data.result?.places ?? []) as Array<{name:string; address:string}>;
            const city = data.result?.city || '';
            const header = city ? `Top coffee spots in ${city}:` : `Top coffee spots:`;
            const lines = places.length
              ? places.map(p => `• ${p.name}${p.address && p.address !== 'Address not available' ? ` — ${p.address}` : ''}`).join('\n')
              : '• No places found.';
            const summary = `${header}\n${lines}`;
            const newTarget = (botTargetRef.current ? `${botTargetRef.current}\n` : '') + summary;
            enqueueBotTranscript(newTarget);
          } else if (data.function === 'calculate_brew_ratio') {
            const advice = data.result?.advice || 'Brew ratio calculated.';
            const newTarget = (botTargetRef.current ? `${botTargetRef.current}\n` : '') + advice;
            enqueueBotTranscript(newTarget);
          } else {
            const summary = `[${data.function}] completed.`;
            const newTarget = (botTargetRef.current ? `${botTargetRef.current}\n` : '') + summary;
            enqueueBotTranscript(newTarget);
          }
        } catch { /* noop */ }
        return;
      }

      // Immediate cut from backend (interruption)
      if (data.event === 'flush_audio') {
        hardStopOutput(); // also clears player & gates playing=false
        modelSpeakingRef.current = false;
        inResponseRef.current = false;
        return;
      }

      // Start/end markers (unchanged UI cues; prep the player as well)
      if (data.event === 'model_speech_start') {
        modelSpeakingRef.current = true;
        inResponseRef.current = true;
        dropChunksRef.current = false;

        resetBotReveal();
        clearTimer(placeholderTimerRef);
        placeholderTimerRef.current = window.setTimeout(() => {
          if (!hasReceivedBotWordsRef.current) setBotTranscript('…');
        }, 500);

        if (pcmPlayerNodeRef.current) {
          pcmPlayerNodeRef.current.port.postMessage({ type: 'clear' });
          pcmPlayerNodeRef.current.port.postMessage({ type: 'setPlaying', playing: true });
        }
        return;
      }
      if (data.event === 'model_speech_end') {
        modelSpeakingRef.current = false;
        inResponseRef.current = false;
        // Do not auto-finish transcript; keep current behavior
        return;
      }

      // Audio playback
      if (data.audioChunk) {
        if (dropChunksRef.current) return;

        const ctx = audioContextRef.current;
        if (!ctx) return;

        // Decode Int16 PCM -> Float32
        const bytes = Uint8Array.from(atob(data.audioChunk), c => c.charCodeAt(0));
        const float32 = int16ToFloat32(new Int16Array(bytes.buffer));

        // NEW: preferred path — push into PCM player node (no pre-scheduling)
        const player = pcmPlayerNodeRef.current;
        if (player) {
          // Transfer the underlying buffer to avoid copies
          const chunk = new Float32Array(float32.buffer.slice(0)); // use a distinct buffer for transfer safety
          try {
            player.port.postMessage({ type: 'push', chunk }, [chunk.buffer]);
          } catch {
            // Fallback without transfer
            player.port.postMessage({ type: 'push', chunk });
          }
          return;
        }

        // Fallback path: keep your existing scheduling in case player isn't available
        const buf = ctx.createBuffer(1, float32.length, 24000);
        buf.getChannelData(0).set(float32);

        const src = ctx.createBufferSource();
        src.buffer = buf;

        // Ensure persistent gain for output
        if (!outGainRef.current) {
          outGainRef.current = ctx.createGain();
          outGainRef.current.gain.value = 0.85; // baseline
          outGainRef.current.connect(ctx.destination);
        }
        src.connect(outGainRef.current);

        const now = ctx.currentTime;
        const startAt = Math.max(now + 0.02, playheadRef.current || now + 0.02);
        try { src.start(startAt); } catch { /* ignore start errors */ }

        activeSourcesRef.current.add(src);
        src.onended = () => {
          activeSourcesRef.current.delete(src);
        };

        playheadRef.current = startAt + (buf.length / buf.sampleRate);
        return;
      }

      // Transcripts (unchanged)
      if (typeof data.transcript === 'string') {
        if (data.who === 'user') {
          setUserTranscript(data.transcript);
          // Voice barge-in on stop keywords
          if (modelSpeakingRef.current && isStopPhrase(data.transcript)) {
            const nowMs = Date.now();
            if (nowMs - lastStopAtRef.current > 300) { // tight debounce
              lastStopAtRef.current = nowMs;
              hardStopOutput(); // cuts ring player + fallback buffers
              const s = liveSocketRef.current;
              if (s && s.readyState === WebSocket.OPEN) {
                s.send(JSON.stringify({ type: 'stop' })); // backend cancels and sends flush_audio
              }
            }
          }
        } else {
          enqueueBotTranscript(data.transcript);
        }
      }
    } catch (err) {
      console.error('Error handling live msg:', err);
    }
  };

  const startLiveTalk = async () => {
    if (
      liveSocketRef.current &&
      (liveSocketRef.current.readyState === WebSocket.OPEN ||
        liveSocketRef.current.readyState === WebSocket.CONNECTING)
    ) {
      setLiveMode(true);
      return;
    }

    try {
      // Capture setup (unchanged)
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
          channelCount: 1,
        }
      });
      const ctx = new AudioContext({ sampleRate: 24000 });

      // Load worklets
      await ctx.audioWorklet.addModule('/audio-processor.js');         // existing capture worklet
      await ctx.audioWorklet.addModule('/pcm-player-processor.js');    // NEW player worklet

      // Create nodes
      const captureNode = new AudioWorkletNode(ctx, 'audio-processor');
      const source = ctx.createMediaStreamSource(stream);
      source.connect(captureNode);
      captureWorkletRef.current = captureNode;

      // Output gain stays as before (ducking etc.)
      outGainRef.current = ctx.createGain();
      outGainRef.current.gain.value = 0.85;
      outGainRef.current.connect(ctx.destination);

      // NEW: create pull-based PCM player and connect to same gain
      const playerNode = new AudioWorkletNode(ctx, 'pcm-player-processor');
      playerNode.connect(outGainRef.current);
      // Start muted until a turn begins
      playerNode.port.postMessage({ type: 'setPlaying', playing: false });
      pcmPlayerNodeRef.current = playerNode;

      // Reset state
      playheadRef.current = ctx.currentTime;
      modelSpeakingRef.current = false;
      inResponseRef.current = false;
      lastStopAtRef.current = 0;
      dropChunksRef.current = false;
      activeSourcesRef.current.clear();

      const socket = new WebSocket('ws://127.0.0.1:8000/ws/livechat');
      socket.binaryType = 'arraybuffer';
      socket.onerror = (err) => {
        console.error('WebSocket error:', err);
      };
      socket.onmessage = handleLiveSocketMessage;
      socket.onopen = () => {
        // Always send mic audio (for voice barge-in).
        captureNode.port.onmessage = e => {
          const chunk = e.data as ArrayBuffer;
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(chunk);
          }
        };
      };
      socket.onclose = () => {
        if (liveMode) stopLiveTalk();
      };

      // Save refs
      liveSocketRef.current = socket;
      audioContextRef.current = ctx;
      mediaStreamRef.current = stream;

      // Reset transcripts at session start
      setUserTranscript('');
      setBotTranscript('');
      setLiveMode(true);
    } catch (err) {
      console.error('Failed to start live chat:', err);
      stopLiveTalk();
    }
  };

  const stopLiveTalk = () => {
    // Ask backend to commit pending buffer
    try {
      if (liveSocketRef.current?.readyState === WebSocket.OPEN) {
        liveSocketRef.current.send(JSON.stringify({ type: 'commit' }));
      }
    } catch { /* noop */ }

    // Hard stop any remaining output nodes and ring player
    hardStopOutput();

    try { captureWorkletRef.current?.disconnect(); } catch { /* noop */ }
    captureWorkletRef.current = null;

    try { pcmPlayerNodeRef.current?.disconnect(); } catch { /* noop */ }
    pcmPlayerNodeRef.current = null;

    try { mediaStreamRef.current?.getTracks().forEach(t => t.stop()); } catch { /* noop */ }
    mediaStreamRef.current = null;

    try {
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close();
      }
    } catch { /* noop */ }
    audioContextRef.current = null;
    outGainRef.current = null;

    try {
      const s = liveSocketRef.current;
      if (s && s.readyState !== WebSocket.CLOSED && s.readyState !== WebSocket.CLOSING) {
        s.close();
      }
    } catch { /* noop */ }
    liveSocketRef.current = null;

    setUserTranscript('');
    setBotTranscript('');
    setLiveMode(false);
  };

  const toggleLive = () => {
    if (!liveMode) startLiveTalk();
    else stopLiveTalk();
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, width: '100%', pt: 2 }}>
      {recording && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <CircularProgress size={20} />
          <Typography variant="body2">Recording... (5s)</Typography>
        </Box>
      )}

      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
        <TextField
          fullWidth
          placeholder="Enter Your Query..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSendClick()}
          sx={{
            backgroundColor: '#fff',
            borderRadius: 1,
            '& .MuiInputBase-input': { color: '#3e2f2f' },
            '& .MuiOutlinedInput-notchedOutline': { borderColor: '#6f4e37' },
          }}
        />
        <IconButton color="primary" onClick={handleSendClick}>
          <SendIcon />
        </IconButton>

        <IconButton color="primary" onClick={handleMicClick} disabled={recording || liveMode}>
          <MicIcon />
        </IconButton>

        <IconButton
          color={liveMode ? 'error' : 'primary'}
          onClick={toggleLive}
          disabled={recording}
          title={liveMode ? 'Stop live' : 'Start live'}
        >
          {liveMode ? <StopIcon /> : <RecordVoiceOverIcon />}
        </IconButton>
      </Box>

      {liveMode && (
        <Stack spacing={0.5} sx={{ mt: 0.5 }}>
          {userTranscript && (
            <Typography variant="body2"><strong>You:</strong> {userTranscript}</Typography>
          )}
          {botTranscript && (
            <Typography variant="body2"><strong>Bot:</strong> {botTranscript}</Typography>
          )}
          {!userTranscript && !botTranscript && (
            <Typography variant="body2" color="textSecondary">Live transcripts will appear here…</Typography>
          )}
        </Stack>
      )}
    </Box>
  );
};

export default InputArea;