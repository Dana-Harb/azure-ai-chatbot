import React, { useState, useEffect } from 'react';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import { Typography, CircularProgress, Box } from '@mui/material';
import ChatWindow from './components/ChatWindow';
import InputArea from './components/InputArea';
import SoundToggle from './components/SoundToggle';
import Login from './components/Login';

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

interface UserData {
  userId: string;
  username: string;
  role: string;
  sessionId: string;
}

interface BackendMessage {
  role: string;
  content: string;
}

const App: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [userData, setUserData] = useState<UserData | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // Load ONLY non-user-specific settings from localStorage on component mount
  useEffect(() => {
    const savedSoundEnabled = localStorage.getItem('soundEnabled');
    if (savedSoundEnabled !== null) {
      setSoundEnabled(savedSoundEnabled === 'true');
    }
    setIsLoading(false);
  }, []);

  // Save sound settings to localStorage whenever they change
  useEffect(() => {
    localStorage.setItem('soundEnabled', soundEnabled.toString());
  }, [soundEnabled]);

  const addMessage = (sender: 'user' | 'bot', text: string, audioBase64?: string) => {
    setMessages(prev => [...prev, { sender, text, audioBase64 }]);

    if (sender === 'bot' && audioBase64 && soundEnabled) {
      const audio = new Audio(`data:audio/wav;base64,${audioBase64}`);
      audio.play();
    }
  };

  const loadSessionHistory = async (sessionId: string, username: string) => {
    setLoadingHistory(true);
    try {
      const res = await fetch(`http://localhost:7071/api/session/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        
        // Convert backend format to frontend format
        const previousMessages: Message[] = data.history.map((msg: BackendMessage) => ({
          sender: msg.role === 'user' ? 'user' : 'bot',
          text: msg.content
        }));
        
        setMessages(previousMessages);
        
        // Only add welcome message if it's a new session with no history
        if (previousMessages.length === 0) {
          addMessage('bot', `Welcome, ${username}! How can I help you with coffee today?`);
        } else {
          addMessage('bot', `Welcome back, ${username}! Continuing your previous conversation.`);
        }
      }
    } catch (error) {
      console.error('Error loading session history:', error);
      // Show welcome message if loading fails
      addMessage('bot', `Welcome, ${username}! How can I help you with coffee today?`);
    } finally {
      setLoadingHistory(false);
    }
  };

  const handleLoginSuccess = async (userData: UserData) => {
    // Clear any previous state completely
    setMessages([]);
    setUserData(userData);
    setSessionId(userData.sessionId);
    setIsLoggedIn(true);
    
    // Load chat history for THIS specific user
    await loadSessionHistory(userData.sessionId, userData.username);
  };

  const handleLogout = () => {
    // Clear all state (don't save user data to localStorage)
    setUserData(null);
    setSessionId(null);
    setIsLoggedIn(false);
    setMessages([]);
  };

  // Show loading screen while checking settings
  if (isLoading) {
    return (
      <ThemeProvider theme={theme}>
        <Box sx={{ 
          height: '100vh', 
          width: '100vw', 
          backgroundColor: 'background.default', 
          display: 'flex', 
          justifyContent: 'center', 
          alignItems: 'center' 
        }}>
          <CircularProgress color="primary" />
        </Box>
      </ThemeProvider>
    );
  }

  if (!isLoggedIn) {
    return (
      <ThemeProvider theme={theme}>
        <Login onLoginSuccess={handleLoginSuccess} />
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider theme={theme}>
      <Box sx={{ 
        height: '100vh', 
        width: '100vw', 
        backgroundColor: 'background.default', 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        padding: 2 
      }}>
        <Box sx={{ 
          width: '80vw', 
          maxWidth: '1000px', 
          height: '80vh', 
          backgroundColor: 'background.default', 
          display: 'flex', 
          flexDirection: 'column', 
          justifyContent: 'space-between', 
          alignItems: 'center', 
          padding: 2, 
          borderRadius: 4, 
          boxShadow: 3,
          position: 'relative'
        }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', width: '100%', alignItems: 'center' }}>
            <Box>
              <Typography color="text.primary" variant="body2">
                Welcome, {userData?.username}
              </Typography>
              <Typography 
                color="text.primary" 
                variant="caption" 
                sx={{ cursor: 'pointer', textDecoration: 'underline' }}
                onClick={handleLogout}
              >
                Logout
              </Typography>
            </Box>
            <SoundToggle enabled={soundEnabled} setEnabled={setSoundEnabled} />
          </Box>
          
          {loadingHistory ? (
            <Box sx={{ 
              display: 'flex', 
              justifyContent: 'center', 
              alignItems: 'center', 
              flex: 1,
              flexDirection: 'column',
              gap: 2
            }}>
              <CircularProgress color="primary" />
              <Typography color="text.primary">Loading your chat history...</Typography>
            </Box>
          ) : (
            <ChatWindow messages={messages} />
          )}
          
          <InputArea 
            sessionId={sessionId} 
            setSessionId={setSessionId} 
            addMessage={addMessage} 
            userData={userData}
          />
        </Box>
      </Box>
    </ThemeProvider>
  );
};

export default App;