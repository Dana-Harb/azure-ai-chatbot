// components/admin/SessionsTable.tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Typography,
  IconButton,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Alert,
  CircularProgress
} from '@mui/material';
import { Visibility } from '@mui/icons-material';

interface Session {
  session_id: string;
  user_id: string;
  username: string;
  role: string;
  created_at: string;
  message_count: number;
  last_updated: number;
}

interface ChatMessage {
  role: string;
  content: string;
}

interface SessionsTableProps {
  userData: {
    sessionId: string;
  };
}

const SessionsTable: React.FC<SessionsTableProps> = ({ userData }) => {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [selectedSession, setSelectedSession] = useState<{ session_id: string; history: ChatMessage[] } | null>(null);

  const fetchSessions = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch('http://localhost:7071/api/management/sessions', {
        headers: {
          'Authorization': `Bearer ${userData.sessionId}`
        }
      });

      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions);
      } else {
        setError('Failed to fetch sessions');
      }
    } catch {
      setError('Could not connect to server');
    } finally {
      setLoading(false);
    }
  }, [userData.sessionId]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const viewSessionDetails = async (sessionId: string) => {
    try {
      const res = await fetch(`http://localhost:7071/api/management/session/${sessionId}`, {
        headers: {
          'Authorization': `Bearer ${userData.sessionId}`
        }
      });
      if (res.ok) {
        const data = await res.json();
        setSelectedSession(data);
        setViewDialogOpen(true);
      } else {
        setError('Failed to load session details');
      }
    } catch {
      setError('Could not load session details');
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3, minHeight: '100vh', backgroundColor: '#f5f5f5', display: 'flex', justifyContent: 'center' }}>
      <Box sx={{ width: '100%', maxWidth: '1200px' }}>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
            {error}
          </Alert>
        )}

        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow >
                <TableCell color='#3e2723'>Session ID</TableCell>
                <TableCell color='#3e2723'>Username</TableCell>
                <TableCell color='#3e2723'>Role</TableCell>
                <TableCell color='#3e2723'>Messages</TableCell>
                <TableCell color='#3e2723'>Created</TableCell>
                <TableCell color='#3e2723'>Last Updated</TableCell>
                <TableCell color='#3e2723'>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sessions.map((session) => (
                <TableRow key={session.session_id}>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.8rem', color: '#3e2723' }}>
                    {session.session_id.substring(0, 8)}...
                  </TableCell>
                  <TableCell sx={{ color: '#3e2723' }}>{session.username}</TableCell>
                  <TableCell sx={{ color: '#3e2723' }}>{session.role}</TableCell>
                  <TableCell sx={{ color: '#3e2723' }}>{session.message_count}</TableCell>
                  <TableCell sx={{ color: '#3e2723' }}>{new Date(session.created_at).toLocaleDateString()}</TableCell>
                  <TableCell sx={{ color: '#3e2723' }}>{new Date(session.last_updated * 1000).toLocaleDateString()}</TableCell>
                  <TableCell>
                    <IconButton
                      size="small"
                      onClick={() => viewSessionDetails(session.session_id)}
                    >
                      <Visibility />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>

        {/* Session Details Dialog */}
        <Dialog
          open={viewDialogOpen}
          onClose={() => setViewDialogOpen(false)}
          maxWidth="md"
          fullWidth
        >
          <DialogTitle>Session Details</DialogTitle>
          <DialogContent>
            {selectedSession && (
              <Box>
                <Typography variant="h6" gutterBottom>
                  Chat History
                </Typography>
                {selectedSession.history.map((msg, index) => (
                  <Paper
                    key={index}
                    sx={{
                      p: 1,
                      mb: 1,
                      backgroundColor: msg.role === 'user' ? '#e3f2fd' : '#f3e5f5'
                    }}
                  >
                    <Typography variant="body2">
                      <strong>{msg.role}:</strong> {msg.content}
                    </Typography>
                  </Paper>
                ))}
              </Box>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setViewDialogOpen(false)}>Close</Button>
          </DialogActions>
        </Dialog>
      </Box>
    </Box>
  );
};

export default SessionsTable;
