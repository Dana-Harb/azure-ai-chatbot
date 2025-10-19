import React, { useState, useRef } from 'react';
import { Box, TextField, IconButton, CircularProgress, Typography } from '@mui/material';
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

// --- Helper: Convert Float32 → WAV ---
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
  for (let i = 0; i < samples.length; i++, idx += 2) view.setInt16(idx, samples[i] * 0x7fff, true);
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
  const [liveTranscript, setLiveTranscript] = useState('');
  const [modelSpeaking, setModelSpeaking] = useState(false);

  // Refs to avoid re-renders causing duplicate connections
  const liveSocketRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);

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

      if (input_type === 'speech') addMessage('user', data.recognized_text || '[Voice message]');

      if (data.reply) addMessage('bot', data.reply, data.audio_base64);
      else if (data.error) addMessage('bot', `Error: ${data.error}`);
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
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
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

  // === REALTIME (SIMPLIFIED) ===
  const handleLiveSocketMessage = (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data);
      if (data.audioChunk) {
        const bytes = Uint8Array.from(atob(data.audioChunk), c => c.charCodeAt(0));
        const int16 = new Int16Array(bytes.buffer);
        const float32 = int16ToFloat32(int16);
        const ctx = audioContextRef.current;
        if (!ctx) return;
        const buf = ctx.createBuffer(1, float32.length, 24000);
        buf.getChannelData(0).set(float32);
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(ctx.destination);
        src.start();
        setModelSpeaking(true);
        src.onended = () => setModelSpeaking(false);
      }
      if (data.transcript) setLiveTranscript(data.transcript);
    } catch (err) {
      console.error('Error handling live msg:', err);
    }
  };

  const startLiveTalk = async () => {
    if (liveSocketRef.current && (liveSocketRef.current.readyState === WebSocket.OPEN || liveSocketRef.current.readyState === WebSocket.CONNECTING)) {
      // Already started or in progress
      setLiveMode(true);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext({ sampleRate: 24000 });
      await ctx.audioWorklet.addModule('/audio-processor.js');
      const node = new AudioWorkletNode(ctx, 'audio-processor');
      const source = ctx.createMediaStreamSource(stream);
      source.connect(node);

      const socket = new WebSocket('ws://127.0.0.1:8000/ws/livechat');
      socket.binaryType = 'arraybuffer';
      socket.onerror = (err) => console.error('WebSocket error:', err);
      socket.onmessage = handleLiveSocketMessage;
      socket.onopen = () => {
        // Start sending audio only after socket is open
        node.port.onmessage = e => {
          const chunk = e.data as ArrayBuffer;
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(chunk);
          }
        };
      };
      socket.onclose = () => {
        // If UI still thinks we're in live mode, stop to clean up
        if (liveMode) stopLiveTalk();
      };

      // Save refs
      liveSocketRef.current = socket;
      audioContextRef.current = ctx;
      mediaStreamRef.current = stream;
      workletNodeRef.current = node;

      setLiveTranscript('');
      setModelSpeaking(false);
      setLiveMode(true);
    } catch (err) {
      console.error('Failed to start live chat:', err);
      stopLiveTalk();
    }
  };

  const stopLiveTalk = () => {
    // Send a commit if socket is open (optional)
    try {
      if (liveSocketRef.current?.readyState === WebSocket.OPEN) {
        liveSocketRef.current.send(JSON.stringify({ type: 'commit' }));
      }
    } catch (err) { void err; }

    // Disconnect audio graph
    try { workletNodeRef.current?.disconnect(); } catch (err) { void err; }
    workletNodeRef.current = null;

    // Stop mic
    try { mediaStreamRef.current?.getTracks().forEach(t => t.stop()); } catch (err) { void err; }
    mediaStreamRef.current = null;

    // Close audio context
    try {
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close();
      }
    } catch (err) { void err; }
    audioContextRef.current = null;

    // Close WS once
    try {
      const s = liveSocketRef.current;
      if (s && s.readyState !== WebSocket.CLOSED && s.readyState !== WebSocket.CLOSING) {
        s.close();
      }
    } catch (err) { void err; }
    liveSocketRef.current = null;

    // Reset UI
    setModelSpeaking(false);
    setLiveTranscript('');
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
        >
          {liveMode ? <StopIcon /> : <RecordVoiceOverIcon />}
        </IconButton>
      </Box>

      {liveMode && (
        <Typography variant="body2" color="textSecondary">
          {modelSpeaking ? '🤖 Speaking...' : liveTranscript || 'Listening...'}
        </Typography>
      )}
    </Box>
  );
};

export default InputArea;