import React, { useState } from 'react';
import { Box, TextField, IconButton, CircularProgress, Typography } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import MicIcon from '@mui/icons-material/Mic';

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
  userData: UserData | null; // Add this prop
}

// Helper function to convert audio buffer to WAV
const encodeWAV = (samples: Float32Array, sampleRate: number): ArrayBuffer => {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  // Write WAV header
  const writeString = (offset: number, string: string) => {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  };

  writeString(0, 'RIFF'); // RIFF header
  view.setUint32(4, 36 + samples.length * 2, true); // RIFF chunk size
  writeString(8, 'WAVE'); // WAVE header
  writeString(12, 'fmt '); // format chunk identifier
  view.setUint32(16, 16, true); // format chunk length
  view.setUint16(20, 1, true); // sample format (1 = PCM)
  view.setUint16(22, 1, true); // channel count
  view.setUint32(24, sampleRate, true); // sample rate
  view.setUint32(28, sampleRate * 2, true); // byte rate (sample rate * block align)
  view.setUint16(32, 2, true); // block align (channel count * bytes per sample)
  view.setUint16(34, 16, true); // bits per sample
  writeString(36, 'data'); // data chunk identifier
  view.setUint32(40, samples.length * 2, true); // data chunk length

  // Write audio samples
  const volume = 1;
  let index = 44;
  for (let i = 0; i < samples.length; i++) {
    view.setInt16(index, samples[i] * (0x7FFF * volume), true);
    index += 2;
  }

  return buffer;
};

const InputArea: React.FC<InputAreaProps> = ({ sessionId, setSessionId, addMessage, userData }) => {
  const [input, setInput] = useState('');
  const [recording, setRecording] = useState(false);

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
          user_id: userData?.userId, // ADD THIS LINE - send user ID to backend
          input_type,
          message: input_type === 'text' ? message : undefined,
          audio_base64: audioBase64,
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}: ${res.statusText}`);
      }

      const data = await res.json();
      console.log('Backend response:', data);

      if (data.session_id) setSessionId(data.session_id);

      // Show recognized text if speech
      if (input_type === 'speech') {
        if (data.recognized_text) {
          addMessage('user', data.recognized_text);
        } else {
          addMessage('user', '[Voice message]');
        }
      }

      if (data.reply) {
        addMessage('bot', data.reply, data.audio_base64);
      } else if (data.error) {
        addMessage('bot', `Error: ${data.error}`);
      }
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

  const handleMicClick = async () => {
    setRecording(true);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true
        }
      });
      
      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      const audioChunks: BlobPart[] = [];

      mediaRecorder.ondataavailable = e => {
        if (e.data.size > 0) {
          audioChunks.push(e.data);
        }
      };
      
      mediaRecorder.start();

      // Stop after 5 seconds
      setTimeout(() => {
        if (mediaRecorder.state === 'recording') {
          mediaRecorder.stop();
        }
        stream.getTracks().forEach(track => track.stop());
      }, 5000);

      mediaRecorder.onstop = async () => {
        try {
          const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
          
          // Convert WebM to WAV
          const audioContext = new AudioContext({ sampleRate: 16000 });
          const arrayBuffer = await audioBlob.arrayBuffer();
          const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
          
          // Get the audio data
          const channelData = audioBuffer.getChannelData(0);
          
          // Convert to WAV
          const wavBuffer = encodeWAV(channelData, 16000);
          const wavBlob = new Blob([wavBuffer], { type: 'audio/wav' });
          
          // Convert to base64
          const reader = new FileReader();
          reader.onloadend = () => {
            const base64String = reader.result?.toString().split(',')[1];
            if (base64String) {
              console.log('Sending audio data, size:', base64String.length);
              sendMessage('', 'speech', base64String);
            }
          };
          reader.readAsDataURL(wavBlob);
        } catch (error) {
          console.error('Error processing audio:', error);
          addMessage('bot', 'Error processing audio recording.');
        } finally {
          setRecording(false);
        }
      };
    } catch (err) {
      console.error('Microphone error:', err);
      setRecording(false);
      addMessage('bot', 'Microphone access denied or unavailable.');
    }
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, width: '100%', paddingTop: 2 }}>
      {recording && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <CircularProgress size={20} color="secondary" />
          <Typography color="text.primary" variant="body2">Recording... (5 seconds max)</Typography>
        </Box>
      )}
      <Box sx={{ display: 'flex', width: '100%', gap: 1, alignItems: 'center' }}>
        <TextField
          fullWidth
          variant="outlined"
          placeholder="Enter Your Query..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => {
            if (e.key === 'Enter') handleSendClick();
          }}
          sx={{
            backgroundColor: '#fff',
            borderRadius: 1,
            '& .MuiInputBase-input': { color: '#3e2f2f' },
            '& .MuiInputBase-input::placeholder': { color: '#6f4e37', opacity: 1 },
            '& .MuiOutlinedInput-notchedOutline': { borderColor: '#6f4e37' },
          }}
        />
        <IconButton
          color="primary"
          sx={{ flexShrink: 0, padding: 1.5, backgroundColor: 'primary.main', color: '#f5f0e6', '&:hover': { backgroundColor: '#5a3e2b' } }}
          onClick={handleSendClick}
        >
          <SendIcon />
        </IconButton>
        <IconButton
          color="primary"
          sx={{ flexShrink: 0, padding: 1.5, backgroundColor: 'primary.main', color: '#f5f0e6', '&:hover': { backgroundColor: '#5a3e2b' } }}
          onClick={handleMicClick}
          disabled={recording}
        >
          <MicIcon />
        </IconButton>
      </Box>
    </Box>
  );
};

export default InputArea;