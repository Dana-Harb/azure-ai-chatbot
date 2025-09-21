// components/admin/AdminDashboard.tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Typography,
  Paper,
  Card,
  CardContent,
  CircularProgress,
  Alert,
  Tabs,
  Tab,
  AppBar,
  Toolbar,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField
} from '@mui/material';
import { CloudUpload, Refresh } from '@mui/icons-material';
import UsersTable from './admin/UsersTable';
import SessionsTable from './admin/SessionsTable';
import AnalyticsDashboard from './admin/AnalyticsDashboard';
import SystemHealth from './admin/SystemHealth';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

interface UserData {
  userId: string;
  username: string;
  role: string;
  sessionId: string;
}

interface StatsData {
  totalUsers: number;
  activeSessions: number;
  totalMessages: number;
}

interface AdminDashboardProps {
  userData: UserData;
  onLogout: () => void;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`admin-tabpanel-${index}`}
      aria-labelledby={`admin-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

const AdminDashboard: React.FC<AdminDashboardProps> = ({ userData, onLogout }) => {
  const [tabValue, setTabValue] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [stats, setStats] = useState<StatsData>({
    totalUsers: 0,
    activeSessions: 0,
    totalMessages: 0
  });

  const fetchStats = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch('http://localhost:7071/api/management/stats', {
        headers: { 'Authorization': `Bearer ${userData.sessionId}` }
      });
      if (res.ok) {
        const data = await res.json();
        setStats({
          totalUsers: data.total_users || 0,
          activeSessions: data.active_sessions || 0,
          totalMessages: data.today_messages || 0
        });
      } else setError('Failed to load statistics');
    } catch {
      setError('Could not connect to server');
    } finally {
      setLoading(false);
    }
  }, [userData.sessionId]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setTabValue(newValue);
  };

  const handleFileUpload = async () => {
  if (!selectedFile) return;

  setUploading(true);
  try {
    const fileBuffer = await selectedFile.arrayBuffer();

    const res = await fetch("http://localhost:7071/api/management/upload", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${userData.sessionId}`,
        "X-Filename": selectedFile.name,
        "Content-Type": "application/octet-stream"
      },
      body: fileBuffer
    });

    if (res.ok) {
      setSuccess("File uploaded successfully!");
      setUploadDialogOpen(false);
      setSelectedFile(null);
    } else {
      const err = await res.text();
      setError(`Upload failed: ${err}`);
    }
  } catch (err) {
    console.error(err);
    setError("Could not upload file");
  } finally {
    setUploading(false);
  }
};

  const handleReindex = async () => {
    try {
      setLoading(true);
      const res = await fetch('http://localhost:7071/api/management/reindex', {
        headers: { 'Authorization': `Bearer ${userData.sessionId}` }
      });
      if (res.ok) setSuccess('Documents reindexed successfully!');
      else setError('Failed to reindex documents');
    } catch {
      setError('Could not reindex documents');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{ minHeight: '100vh', backgroundColor: '#f5f5f5' }}>
      {/* AppBar */}
      <AppBar position="static" sx={{ backgroundColor: '#3e2723', color: 'white' }}>
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 'bold' }}>
            Admin Panel - Coffee Expert
          </Typography>
          <Button color="inherit" startIcon={<CloudUpload />} onClick={() => setUploadDialogOpen(true)}>
            Upload
          </Button>
          <Button color="inherit" startIcon={<Refresh />} onClick={handleReindex}>
            Reindex
          </Button>
          <Typography variant="body2" sx={{ mx: 2 }}>
            Welcome, {userData.username}
          </Typography>
          <Button color="inherit" onClick={onLogout}>Logout</Button>
        </Toolbar>
      </AppBar>

      {/* Centered Content */}
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
        <Paper sx={{ width: '100%', maxWidth: '1200px' }}>
          <Tabs value={tabValue} onChange={handleTabChange} centered>
            <Tab label="Dashboard" />
            <Tab label="Users" />
            <Tab label="Sessions" />
            <Tab label="Analytics" />
            <Tab label="System Health" />
          </Tabs>

          {error && <Alert severity="error" sx={{ m: 2 }} onClose={() => setError('')}>{error}</Alert>}
          {success && <Alert severity="success" sx={{ m: 2 }} onClose={() => setSuccess('')}>{success}</Alert>}

          {/* Tab Panels */}
          <TabPanel value={tabValue} index={0}>
            <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, gap: 3, flexWrap: 'wrap', justifyContent: 'center' }}>
              {['Total Users', 'Active Sessions', 'Messages Today'].map((label, idx) => (
                <Box key={label} sx={{ flex: { xs: '1 1 100%', md: '1 1 30%' }, maxWidth: '300px' }}>
                  <Card>
                    <CardContent sx={{ textAlign: 'center' }}>
                      <Typography variant="h6" sx={{ fontWeight: 'bold', color: '#3e2723' }}>
                        {label}
                      </Typography>
                      {loading ? <CircularProgress size={24} /> : (
                        <Typography variant="h4" sx={{ fontWeight: 'bold', color: '#3e2723' }}>
                          {idx === 0 ? stats.totalUsers : idx === 1 ? stats.activeSessions : stats.totalMessages}
                        </Typography>
                      )}
                    </CardContent>
                  </Card>
                </Box>
              ))}
            </Box>
          </TabPanel>

          <TabPanel value={tabValue} index={1}>
            <UsersTable userData={userData} onUserUpdate={fetchStats} />
          </TabPanel>

          <TabPanel value={tabValue} index={2}>
            <SessionsTable userData={userData} />
          </TabPanel>

          <TabPanel value={tabValue} index={3}>
            <AnalyticsDashboard />
          </TabPanel>

          <TabPanel value={tabValue} index={4}>
            <SystemHealth />
          </TabPanel>
        </Paper>
      </Box>

      {/* File Upload Dialog */}
      <Dialog open={uploadDialogOpen} onClose={() => setUploadDialogOpen(false)}>
        <DialogTitle>Upload Document</DialogTitle>
        <DialogContent>
          <TextField
            type="file"
            fullWidth
            inputProps={{ accept: '.pdf,.txt,.doc,.docx,.png,.jpg,.jpeg,.tiff' }}
            onChange={(e) => {
              const input = e.target as HTMLInputElement;
              if (input.files && input.files[0]) setSelectedFile(input.files[0]);
            }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUploadDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleFileUpload} disabled={!selectedFile || uploading} variant="contained">
            {uploading ? <CircularProgress size={24} /> : 'Upload'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default AdminDashboard;
