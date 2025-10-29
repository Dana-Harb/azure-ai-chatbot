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

// --- Helper: Convert Float32 → WAV (kept for your existing features) ---
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
  // Displayed bot transcript (revealed word-by-word)
  const [botTranscript, setBotTranscript] = useState('');

  // Refs to avoid re-renders causing duplicate connections
  const liveSocketRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);

  // Playback/capture control
  const playheadRef = useRef<number>(0);                           // next scheduled start time
  const outGainRef = useRef<GainNode | null>(null);                // output gain (for ducking/muting)
  const modelSpeakingRef = useRef<boolean>(false);                 // bot speaking flag (audio-based)
  const inResponseRef = useRef<boolean>(false);                    // response boundary (text or audio)
  const lastStopAtRef = useRef<number>(0);                         // debounce for voice "stop"
  const activeSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set()); // track scheduled nodes
  const dropChunksRef = useRef<boolean>(false);                    // ignore chunks after stop until next start

  // Keywords to trigger barge-in (interrupt)
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

  // Hard cut of any currently scheduled output audio
  const hardStopOutput = () => {
    const ctx = audioContextRef.current;
    if (outGainRef.current && ctx) {
      try {
        outGainRef.current.gain.cancelScheduledValues(ctx.currentTime);
        outGainRef.current.gain.setValueAtTime(0.0, ctx.currentTime); // immediate mute
      } catch { /* noop */ }
    }
    activeSourcesRef.current.forEach(src => {
      try { src.stop(0); } catch { /* already stopped */ }
    });
    activeSourcesRef.current.clear();
    if (ctx) {
      playheadRef.current = ctx.currentTime; // reset playhead
    }
    dropChunksRef.current = true; // ignore any late chunks for the old reply
  };

  // === Word-by-word reveal helpers (slower + placeholder if no text yet) ===
  const WORD_INTERVAL_MS = 340;     // slower base (tune 300–380)
  const PAUSE_PUNCT_MS = 280;       // pause after . ! ?
  const PAUSE_COMMA_MS = 160;       // pause after , ; :

  const botTargetRef = useRef<string>('');        // latest full transcript string from server
  const revealedWordsRef = useRef<string[]>([]);  // words already revealed
  const pendingWordsRef = useRef<string[]>([]);   // words queued to reveal
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

  // Compute and queue only the new words to reveal based on the latest full transcript
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
      // cancel placeholder if we just got real words
      clearTimer(placeholderTimerRef);
    }

    if (revealTimerRef.current === null) {
      scheduleNextReveal(WORD_INTERVAL_MS);
    }
  };

  const finishRevealNow = () => {
    const trimmed = botTargetRef.current.trim();
    const targetWords = trimmed.length ? trimmed.split(/\s+/) : [];
    revealedWordsRef.current = targetWords.slice();
    pendingWordsRef.current = [];
    setBotTranscript(revealedWordsRef.current.join(' '));
    clearTimer(revealTimerRef);
    clearTimer(placeholderTimerRef);
  };

  // Clear timers on unmount
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

      // NEW RESPONSE BOUNDARY (from backend response.created/started)
      if (data.event === 'new_response') {
        inResponseRef.current = true;
        modelSpeakingRef.current = false; // new turn hasn't started audio yet
        dropChunksRef.current = false;
        resetBotReveal();

        // Placeholder "…" if text hasn't arrived soon
        clearTimer(placeholderTimerRef);
        placeholderTimerRef.current = window.setTimeout(() => {
          if (!hasReceivedBotWordsRef.current) {
            setBotTranscript('…');
          }
        }, 500);
        return;
      }

      // Tool/function result -> append into target and reveal
      if (data.event === 'tool_result') {
        try {
          // DEFENSIVE RESET: if this is arriving for a new reply before audio start and we still show old text
          if (!modelSpeakingRef.current && inResponseRef.current && (botTranscript || revealedWordsRef.current.length || pendingWordsRef.current.length)) {
            resetBotReveal();
          }

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
        } catch {
          // silent UI fallback
        }
        return;
      }

      // Server can tell us to flush immediately
      if (data.event === 'flush_audio') {
        hardStopOutput();
        finishRevealNow(); // finalize whatever we had
        return;
      }

      // Bot speaking start/end -> reset transcript for new reply; show placeholder if no text arrives
      if (data.event === 'model_speech_start') {
        modelSpeakingRef.current = true;
        inResponseRef.current = true;
        dropChunksRef.current = false;

        // Reset (in case we didn't see new_response for some reason)
        resetBotReveal();

        // Show placeholder "…" if we don't get any bot words quickly
        clearTimer(placeholderTimerRef);
        placeholderTimerRef.current = window.setTimeout(() => {
          if (!hasReceivedBotWordsRef.current) {
            setBotTranscript('…');
          }
        }, 500);

        const ctx = audioContextRef.current;
        if (ctx && outGainRef.current) {
          outGainRef.current.gain.cancelScheduledValues(ctx.currentTime);
          outGainRef.current.gain.setTargetAtTime(0.35, ctx.currentTime, 0.015);
        }
        return;
      }
      if (data.event === 'model_speech_end') {
        modelSpeakingRef.current = false;
        inResponseRef.current = false;
        hardStopOutput();
        finishRevealNow();

        const ctx = audioContextRef.current;
        if (ctx && outGainRef.current) {
          outGainRef.current.gain.cancelScheduledValues(ctx.currentTime);
          outGainRef.current.gain.setTargetAtTime(0.85, ctx.currentTime, 0.02);
        }
        return;
      }

      // Audio playback: schedule contiguous; also reset transcript if a new audio reply starts without start event
      if (data.audioChunk) {
        if (!modelSpeakingRef.current && (botTranscript || revealedWordsRef.current.length || pendingWordsRef.current.length)) {
          // New reply detected only by audio; clear old transcript
          resetBotReveal();
          modelSpeakingRef.current = true;
          inResponseRef.current = true;

          // Start placeholder since we detected a new reply via audio only
          clearTimer(placeholderTimerRef);
          placeholderTimerRef.current = window.setTimeout(() => {
            if (!hasReceivedBotWordsRef.current) {
              setBotTranscript('…');
            }
          }, 500);
        }

        if (dropChunksRef.current) return;

        const ctx = audioContextRef.current;
        if (!ctx) return;

        const bytes = Uint8Array.from(atob(data.audioChunk), c => c.charCodeAt(0));
        const float32 = int16ToFloat32(new Int16Array(bytes.buffer));

        const buf = ctx.createBuffer(1, float32.length, 24000);
        buf.getChannelData(0).set(float32);

        const src = ctx.createBufferSource();
        src.buffer = buf;

        if (!outGainRef.current) {
          outGainRef.current = ctx.createGain();
          outGainRef.current.gain.value = 0.85;
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

      // Show separate transcripts and trigger voice interruption
      if (typeof data.transcript === 'string') {
        if (data.who === 'user') {
          setUserTranscript(data.transcript);

          if (modelSpeakingRef.current && isStopPhrase(data.transcript)) {
            const nowMs = Date.now();
            if (nowMs - lastStopAtRef.current > 600) {
              lastStopAtRef.current = nowMs;
              hardStopOutput();
              const s = liveSocketRef.current;
              if (s && s.readyState === WebSocket.OPEN) {
                s.send(JSON.stringify({ type: 'stop' }));
              }
            }
          }
        } else {
          // DEFENSIVE RESET: text-first reply (text delta before audio start)
          if (!modelSpeakingRef.current && inResponseRef.current && (botTranscript || revealedWordsRef.current.length || pendingWordsRef.current.length)) {
            resetBotReveal();
          }

          // Bot transcript stream
          if (data.transcript.trim() === '[stopped]') {
            botTargetRef.current = data.transcript;
            finishRevealNow();
          } else {
            enqueueBotTranscript(data.transcript);
          }
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
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
          channelCount: 1,
        }
      });
      const ctx = new AudioContext({ sampleRate: 24000 });
      await ctx.audioWorklet.addModule('/audio-processor.js');
      const node = new AudioWorkletNode(ctx, 'audio-processor');
      const source = ctx.createMediaStreamSource(stream);
      source.connect(node);

      // Reset state
      playheadRef.current = ctx.currentTime;
      outGainRef.current = ctx.createGain();
      outGainRef.current.gain.value = 0.85;
      outGainRef.current.connect(ctx.destination);
      modelSpeakingRef.current = false;
      inResponseRef.current = false;
      lastStopAtRef.current = 0;
      dropChunksRef.current = false;
      activeSourcesRef.current.clear();
      resetBotReveal();

      const socket = new WebSocket('ws://127.0.0.1:8000/ws/livechat');
      socket.binaryType = 'arraybuffer';
      socket.onerror = (err) => {
        console.error('WebSocket error:', err);
      };
      socket.onmessage = handleLiveSocketMessage;
      socket.onopen = () => {
        // Always send mic audio (for voice barge-in).
        node.port.onmessage = e => {
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
      workletNodeRef.current = node;

      // Reset transcripts at session start
      setUserTranscript('');
      resetBotReveal();
      setLiveMode(true);
    } catch (err) {
      console.error('Failed to start live chat:', err);
      stopLiveTalk();
    }
  };

  const stopLiveTalk = () => {
    try {
      if (liveSocketRef.current?.readyState === WebSocket.OPEN) {
        liveSocketRef.current.send(JSON.stringify({ type: 'commit' }));
      }
    } catch (err) { void err; }

    hardStopOutput();

    try { workletNodeRef.current?.disconnect(); } catch (err) { void err; }
    workletNodeRef.current = null;

    try { mediaStreamRef.current?.getTracks().forEach(t => t.stop()); } catch (err) { void err; }
    mediaStreamRef.current = null;

    try {
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close();
      }
    } catch (err) { void err; }
    audioContextRef.current = null;
    outGainRef.current = null;

    try {
      const s = liveSocketRef.current;
      if (s && s.readyState !== WebSocket.CLOSED && s.readyState !== WebSocket.CLOSING) {
        s.close();
      }
    } catch (err) { void err; }
    liveSocketRef.current = null;

    setUserTranscript('');
    resetBotReveal();
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
          {botTranscript !== '' && (
            <Typography variant="body2"><strong>Bot:</strong> {botTranscript}</Typography>
          )}
          {userTranscript === '' && botTranscript === '' && (
            <Typography variant="body2" color="textSecondary">Live transcripts will appear here…</Typography>
          )}
        </Stack>
      )}
    </Box>
  );
};

export default InputArea;