import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Paper,
  Card,
  CardContent,
  CircularProgress,
  Alert,
} from '@mui/material';

interface AnalyticsData {
  totalUsers: number;
  activeSessions: number;
  todayMessages: number;
}

const AnalyticsDashboard: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [data, setData] = useState<AnalyticsData>({
    totalUsers: 0,
    activeSessions: 0,
    todayMessages: 0
  });

  useEffect(() => {
    const fetchAnalyticsData = async () => {
      try {
        setLoading(true);
        setTimeout(() => {
          setData({
            totalUsers: 25,
            activeSessions: 8,
            todayMessages: 142
          });
          setLoading(false);
        }, 1000);
      } catch (err) {
        console.log(err);
        setError('Failed to load analytics data');
        setLoading(false);
      }
    };

    fetchAnalyticsData();
  }, []);

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
        <Typography variant="h5" gutterBottom sx={{ color: '#3e2723', textAlign: 'center' }}>
          Analytics Dashboard
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
            {error}
          </Alert>
        )}

        <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, gap: 3, flexWrap: 'wrap', justifyContent: 'center' }}>
          <Box sx={{ flex: { xs: '1 1 100%', md: '1 1 30%' }, maxWidth: '300px' }}>
            <Card>
              <CardContent>
                <Typography variant="h6" sx={{ color: '#3e2723' }}>Total Users</Typography>
                <Typography variant="h4" sx={{ color: '#3e2723' }}>{data.totalUsers}</Typography>
              </CardContent>
            </Card>
          </Box>

          <Box sx={{ flex: { xs: '1 1 100%', md: '1 1 30%' }, maxWidth: '300px' }}>
            <Card>
              <CardContent>
                <Typography variant="h6" sx={{ color: '#3e2723' }}>Active Sessions</Typography>
                <Typography variant="h4" sx={{ color: '#3e2723' }}>{data.activeSessions}</Typography>
              </CardContent>
            </Card>
          </Box>

          <Box sx={{ flex: { xs: '1 1 100%', md: '1 1 30%' }, maxWidth: '300px' }}>
            <Card>
              <CardContent>
                <Typography variant="h6" sx={{ color: '#3e2723' }}>Today's Messages</Typography>
                <Typography variant="h4" sx={{ color: '#3e2723' }}>{data.todayMessages}</Typography>
              </CardContent>
            </Card>
          </Box>
        </Box>

        <Paper sx={{ p: 3, mt: 3 }}>
          <Typography variant="h6" gutterBottom sx={{ color: '#3e2723' }}>
            Usage Statistics
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Analytics charts will be implemented here
          </Typography>
        </Paper>
      </Box>
    </Box>
  );
};

export default AnalyticsDashboard;
