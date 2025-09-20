import React from 'react';
import { Box, Typography } from '@mui/material';

interface Props {
  sender: 'user' | 'bot';
  text: string;
}

const MessageBubble: React.FC<Props> = ({ sender, text }) => {
  const isUser = sender === 'user';

  return (
    <Box
      sx={{
        backgroundColor: isUser ? 'primary.main' : '#fff',
        color: isUser ? '#f5f0e6' : '#3e2f2f',
        borderRadius: 2,
        padding: 1,
        marginBottom: 1,
        alignSelf: isUser ? 'flex-end' : 'flex-start',
        maxWidth: '80%',
      }}
    >
      <Typography variant="body1">{text}</Typography>
    </Box>
  );
};

export default MessageBubble;
