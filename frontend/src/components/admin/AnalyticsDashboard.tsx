import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Typography,
  Paper,
  Card,
  CardContent,
  CircularProgress,
  Alert,
  Button
} from '@mui/material';
import { Refresh } from '@mui/icons-material';

interface AnalyticsData {
  totalUsers: number;
  activeSessions: number;
  todayMessages: number;
  dailyMessages?: Array<{ date: string; count: number }>;
  popularSearches?: Array<{ query: string; count: number }>;
}

interface AnalyticsDashboardProps {
  userData?: {
    sessionId: string;
  };
}

const AnalyticsDashboard: React.FC<AnalyticsDashboardProps> = ({ userData }) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [data, setData] = useState<AnalyticsData>({
    totalUsers: 0,
    activeSessions: 0,
    todayMessages: 0
  });
  const [lastUpdated, setLastUpdated] = useState<string>('');

  const fetchAnalyticsData = useCallback(async () => {
    try {
      setLoading(true);
      setError('');

      console.log('Fetching analytics data...');
      
      // Fetch stats from your backend
      const statsRes = await fetch('http://localhost:7071/api/management/stats', {
        headers: { 
          'Authorization': `Bearer ${userData?.sessionId || 'test'}`,
          'Content-Type': 'application/json'
        }
      });

      console.log('Response status:', statsRes.status);
      
      if (statsRes.ok) {
        const statsData = await statsRes.json();
        console.log('Raw API response:', statsData);
        
        // Map the API response to our component state with fallbacks
        const mappedData = {
          totalUsers: statsData.total_users || statsData.totalUsers || 0,
          activeSessions: statsData.active_sessions || statsData.activeSessions || 0,
          todayMessages: statsData.today_messages || statsData.todayMessages || statsData.messages_today || 0,
          dailyMessages: statsData.daily_messages || statsData.dailyMessages || [],
          popularSearches: statsData.popular_searches || statsData.popularSearches || []
        };
        
        console.log('Mapped data:', mappedData);
        setData(mappedData);
      } else {
        const errorText = await statsRes.text();
        console.error('API error response:', errorText);
        throw new Error(`Failed to fetch analytics data: ${statsRes.status} ${errorText}`);
      }

      setLastUpdated(new Date().toLocaleTimeString());
    } catch (err) {
      console.error('Analytics fetch error:', err);
      setError('Failed to load analytics data');
      
      // Fallback to basic health check if stats endpoint fails
      try {
        console.log('Attempting health check...');
        const healthRes = await fetch('http://localhost:7071/api/health');
        console.log('Health check status:', healthRes.status);
        
        if (healthRes.ok) {
          setData(prev => ({ ...prev, activeSessions: 1 })); // At least API is working
        } else {
          throw new Error('Health check failed');
        }
      } catch (healthErr) {
        console.error('Health check error:', healthErr);
        setError('Server is unavailable');
      }
    } finally {
      setLoading(false);
    }
  }, [userData?.sessionId]);

  useEffect(() => {
    fetchAnalyticsData();
    
    // Refresh data every 2 minutes
    const interval = setInterval(fetchAnalyticsData, 120000);
    return () => clearInterval(interval);
  }, [fetchAnalyticsData]);

  const handleRefresh = () => {
    fetchAnalyticsData();
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
        <CircularProgress />
        <Typography variant="body2" sx={{ ml: 2 }}>
          Loading analytics data...
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3, minHeight: '100vh', backgroundColor: '#f5f5f5', display: 'flex', justifyContent: 'center' }}>
      <Box sx={{ width: '100%', maxWidth: '1200px' }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h5" sx={{ color: '#3e2723' }}>
            Analytics Dashboard
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            {lastUpdated && (
              <Typography variant="body2" color="text.secondary">
                Last updated: {lastUpdated}
              </Typography>
            )}
            <Button 
              startIcon={<Refresh />} 
              onClick={handleRefresh}
              variant="outlined"
              disabled={loading}
            >
              Refresh
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
            {error}
          </Alert>
        )}

        <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, gap: 3, flexWrap: 'wrap', justifyContent: 'center' }}>
          <Box sx={{ flex: { xs: '1 1 100%', md: '1 1 30%' }, maxWidth: '300px' }}>
            <Card>
              <CardContent sx={{ textAlign: 'center' }}>
                <Typography variant="h6" sx={{ color: '#3e2723' }}>Total Users</Typography>
                <Typography variant="h4" sx={{ color: '#3e2723', fontWeight: 'bold' }}>
                  {data.totalUsers.toLocaleString()}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Registered users
                </Typography>
              </CardContent>
            </Card>
          </Box>

          <Box sx={{ flex: { xs: '1 1 100%', md: '1 1 30%' }, maxWidth: '300px' }}>
            <Card>
              <CardContent sx={{ textAlign: 'center' }}>
                <Typography variant="h6" sx={{ color: '#3e2723' }}>Active Sessions</Typography>
                <Typography variant="h4" sx={{ color: '#3e2723', fontWeight: 'bold' }}>
                  {data.activeSessions.toLocaleString()}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Current conversations
                </Typography>
              </CardContent>
            </Card>
          </Box>

          <Box sx={{ flex: { xs: '1 1 100%', md: '1 1 30%' }, maxWidth: '300px' }}>
            <Card>
              <CardContent sx={{ textAlign: 'center' }}>
                <Typography variant="h6" sx={{ color: '#3e2723' }}>Today's Messages</Typography>
                <Typography variant="h4" sx={{ color: '#3e2723', fontWeight: 'bold' }}>
                  {data.todayMessages.toLocaleString()}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Messages sent today
                </Typography>
                {data.todayMessages === 0 && (
                  <Typography variant="caption" color="error">
                    No messages recorded today
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Box>
        </Box>

        <Paper sx={{ p: 3, mt: 3 }}>
          <Typography variant="h6" gutterBottom sx={{ color: '#3e2723' }}>
            Usage Statistics
          </Typography>
          
          {data.dailyMessages && data.dailyMessages.length > 0 ? (
            <Box>
              <Typography variant="body1" gutterBottom>
                Message activity (last 7 days):
              </Typography>
              {data.dailyMessages.map((day, index) => (
                <Box key={index} sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                  <Typography variant="body2">{day.date}</Typography>
                  <Typography variant="body2" fontWeight="bold">{day.count} messages</Typography>
                </Box>
              ))}
            </Box>
          ) : (
            <Typography variant="body2" color="text.secondary">
              Detailed analytics will be displayed here as more data becomes available.
              {data.todayMessages === 0 && " No activity recorded today."}
            </Typography>
          )}

          {data.popularSearches && data.popularSearches.length > 0 && (
            <Box sx={{ mt: 3 }}>
              <Typography variant="body1" gutterBottom>
                Popular searches:
              </Typography>
              {data.popularSearches.slice(0, 5).map((search, index) => (
                <Box key={index} sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                  <Typography variant="body2">"{search.query}"</Typography>
                  <Typography variant="body2" color="text.secondary">{search.count} searches</Typography>
                </Box>
              ))}
            </Box>
          )}

          {/* Debug information */}
          <Box sx={{ mt: 3, p: 2, backgroundColor: '#f0f0f0', borderRadius: 1 }}>
            <Typography variant="body2" fontWeight="bold" gutterBottom>
              Debug Information:
            </Typography>
            <Typography variant="caption" component="div">
              Today's Messages value: {data.todayMessages}
            </Typography>
            <Typography variant="caption" component="div">
              Total Users: {data.totalUsers}
            </Typography>
            <Typography variant="caption" component="div">
              Active Sessions: {data.activeSessions}
            </Typography>
            <Typography variant="caption" component="div">
              Daily Messages array length: {data.dailyMessages?.length || 0}
            </Typography>
          </Box>
        </Paper>
      </Box>
    </Box>
  );
};

export default AnalyticsDashboard;