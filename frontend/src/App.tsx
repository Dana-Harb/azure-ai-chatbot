import React, { useState } from 'react';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import Box from '@mui/material/Box';
import ChatWindow from './components/ChatWindow';
import InputArea from './components/InputArea';
import SoundToggle from './components/SoundToggle';

const theme = createTheme({
  palette: {
    background: { default: '#3e2f2f' },
    primary: { main: '#6f4e37' },
    secondary: { main: '#d8cfc4' },
    text: { primary: '#f5f0e6' },
  },
});

interface Message {
  sender: 'user' | 'bot';
  text: string;
  audioBase64?: string;
}

const App: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [soundEnabled, setSoundEnabled] = useState(true);

  const addMessage = (sender: 'user' | 'bot', text: string, audioBase64?: string) => {
    setMessages(prev => [...prev, { sender, text, audioBase64 }]);

    // Play audio if bot message and sound is enabled
    if (sender === 'bot' && audioBase64 && soundEnabled) {
      const audio = new Audio(`data:audio/wav;base64,${audioBase64}`);
      audio.play();
    }
  };

  return (
    <ThemeProvider theme={theme}>
      <Box sx={{ height: '100vh', width: '100vw', backgroundColor: 'background.default', display: 'flex', justifyContent: 'center', alignItems: 'center', padding: 2 }}>
        <Box sx={{ width: '80vw', maxWidth: '1000px', height: '80vh', backgroundColor: 'background.default', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', alignItems: 'center', padding: 2, borderRadius: 4, boxShadow: 3 }}>
          <SoundToggle enabled={soundEnabled} setEnabled={setSoundEnabled} />
          <ChatWindow messages={messages} />
          <InputArea sessionId={sessionId} setSessionId={setSessionId} addMessage={addMessage} />
        </Box>
      </Box>
    </ThemeProvider>
  );
};

export default App;
