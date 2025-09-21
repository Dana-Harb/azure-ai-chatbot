// components/admin/UsersTable.tsx
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
  TextField,
  MenuItem,
  Alert,
  CircularProgress
} from '@mui/material';
import { Delete, Edit } from '@mui/icons-material';

interface User {
  id: string;
  user_id: string;
  username: string;
  role: string;
  created_at: string;
}

interface UsersTableProps {
  userData: {
    sessionId: string;
  };
  onUserUpdate: () => void;
}

const UsersTable: React.FC<UsersTableProps> = ({ userData, onUserUpdate }) => {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [newRole, setNewRole] = useState('');

  const fetchUsers = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch('http://localhost:7071/api/management/users', {
        headers: {
          'Authorization': `Bearer ${userData.sessionId}`
        }
      });

      if (res.ok) {
        const data = await res.json();
        setUsers(data.users);
      } else {
        setError('Failed to fetch users');
      }
    } catch (err) {
      console.log(err);
      setError('Could not connect to server');
    } finally {
      setLoading(false);
    }
  }, [userData.sessionId]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleDeleteUser = async () => {
    if (!selectedUser) return;

    try {
      const res = await fetch(`http://localhost:7071/api/management/user/${selectedUser.user_id}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${userData.sessionId}`
        }
      });

      if (res.ok) {
        setUsers(users.filter(user => user.user_id !== selectedUser.user_id));
        setDeleteDialogOpen(false);
        setSelectedUser(null);
        onUserUpdate();
      } else {
        setError('Failed to delete user');
      }
    } catch (err) {
      console.log(err);
      setError('Could not connect to server');
    }
  };

  const handleUpdateRole = async () => {
    if (!selectedUser) return;

    try {
      const res = await fetch(`http://localhost:7071/api/management/user/${selectedUser.user_id}/role`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${userData.sessionId}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ role: newRole })
      });

      if (res.ok) {
        setUsers(users.map(user => 
          user.user_id === selectedUser.user_id ? { ...user, role: newRole } : user
        ));
        setEditDialogOpen(false);
        setSelectedUser(null);
        onUserUpdate();
      } else {
        setError('Failed to update user role');
      }
    } catch (err) {
      console.log(err);
      setError('Could not update user role');
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
              <TableRow color='#3e2723'>
                <TableCell>Username</TableCell>
                <TableCell>Role</TableCell>
                <TableCell>User ID</TableCell>
                <TableCell>Created At</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.map((user) => (
                <TableRow key={user.user_id}>
                  <TableCell sx={{ color: '#3e2723' }}>{user.username}</TableCell>
                  <TableCell sx={{ color: '#3e2723' }}>{user.role}</TableCell>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.8rem', color: '#3e2723' }}>
                    {user.user_id.substring(0, 8)}...
                  </TableCell>
                  <TableCell sx={{ color: '#3e2723' }}>
                    {new Date(user.created_at).toLocaleDateString()}
                  </TableCell>
                  <TableCell>
                    <IconButton
                      size="small"
                      onClick={() => {
                        setSelectedUser(user);
                        setNewRole(user.role);
                        setEditDialogOpen(true);
                      }}
                    >
                      <Edit />
                    </IconButton>
                    <IconButton
                      size="small"
                      onClick={() => {
                        setSelectedUser(user);
                        setDeleteDialogOpen(true);
                      }}
                    >
                      <Delete />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>

        {/* Delete Confirmation Dialog */}
        <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
          <DialogTitle>Delete User</DialogTitle>
          <DialogContent>
            <Typography>
              Are you sure you want to delete user "{selectedUser?.username}"? This will also delete all their sessions.
            </Typography>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setDeleteDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleDeleteUser} color="error">
              Delete
            </Button>
          </DialogActions>
        </Dialog>

        {/* Edit User Dialog */}
        <Dialog open={editDialogOpen} onClose={() => setEditDialogOpen(false)}>
          <DialogTitle>Edit User Role</DialogTitle>
          <DialogContent>
            <TextField
              select
              fullWidth
              label="Role"
              value={newRole}
              onChange={(e) => setNewRole(e.target.value)}
              sx={{ mt: 2 }}
            >
              <MenuItem value="admin">Admin</MenuItem>
              <MenuItem value="client">Client</MenuItem>
            </TextField>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setEditDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleUpdateRole}>Save</Button>
          </DialogActions>
        </Dialog>
      </Box>
    </Box>
  );
};

export default UsersTable;
