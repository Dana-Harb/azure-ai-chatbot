import React, { useEffect, useRef } from 'react';
import Box from '@mui/material/Box';
import MessageBubble from './MessageBubble';

interface Message {
  sender: 'user' | 'bot';
  text: string;
}

interface ChatWindowProps {
  messages: Message[];
}

const ChatWindow: React.FC<ChatWindowProps> = ({ messages }) => {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <Box sx={{ flex: 1, width: '100%', backgroundColor: 'secondary.main', borderRadius: 2, padding: 2, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
      {messages.map((msg, idx) => (
        <MessageBubble key={idx} sender={msg.sender} text={msg.text} />
      ))}
      <div ref={endRef} />
    </Box>
  );
};

export default ChatWindow;
