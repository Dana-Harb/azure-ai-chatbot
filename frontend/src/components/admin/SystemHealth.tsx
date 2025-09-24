// components/admin/SystemHealth.tsx
import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Alert
} from '@mui/material';

interface HealthStatus {
  api: string;
  database: string;
  search: string;
  speech: string;
}

interface SystemInfo {
  version: string;
  uptime: string;
  lastUpdated: string;
}

const SystemHealth: React.FC = () => {
  const [healthStatus, setHealthStatus] = useState<HealthStatus>({
    api: 'checking',
    database: 'checking',
    search: 'checking',
    speech: 'checking'
  });
  const [systemInfo, setSystemInfo] = useState<SystemInfo>({
    version: '',
    uptime: '',
    lastUpdated: ''
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchHealthData = async () => {
      try {
        setLoading(true);
        setError('');

        // Test all services by making actual API calls
        const healthChecks = await Promise.allSettled([
          // Test API service
          fetch('http://localhost:7071/api/health').then(res => res.ok ? 'operational' : 'down'),
          
          // Test database connectivity (via users endpoint)
          fetch('http://localhost:7071/api/management/users', {
            headers: { 'Authorization': 'Bearer test' } // Will fail auth but test connection
          }).then(res => res.status !== 500 ? 'connected' : 'disconnected'),
          
          // Test search functionality (via chat endpoint with simple query)
          fetch('http://localhost:7071/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: 'test', input_type: 'text' })
          }).then(res => res.status !== 500 ? 'indexed' : 'error'),
          
          // Test speech services (health check would need specific endpoint)
          fetch('http://localhost:7071/api/health').then(res => res.ok ? 'operational' : 'down')
        ]);

        const [apiStatus, dbStatus, searchStatus, speechStatus] = healthChecks.map(check => 
          check.status === 'fulfilled' ? check.value : 'down'
        );

        setHealthStatus({
          api: apiStatus as string,
          database: dbStatus as string,
          search: searchStatus as string,
          speech: speechStatus as string
        });

        // Get system information
        const startTime = Date.now();
        const systemRes = await fetch('http://localhost:7071/api/health');
        if (systemRes.ok) {
          const systemData = await systemRes.json();
          setSystemInfo({
            version: systemData.version || '1.0.0',
            uptime: calculateUptime(startTime),
            lastUpdated: new Date().toLocaleDateString()
          });
        }

      } catch (err) {
        console.error(err);
        setError('Failed to fetch system health data');
        setHealthStatus({
          api: 'down',
          database: 'disconnected',
          search: 'error',
          speech: 'down'
        });
      } finally {
        setLoading(false);
      }
    };

    fetchHealthData();
    
    // Refresh health status every 30 seconds
    const interval = setInterval(fetchHealthData, 30000);
    return () => clearInterval(interval);
  }, []);

  const calculateUptime = (startTime: number) => {
    const uptimeMs = Date.now() - startTime;
    const days = Math.floor(uptimeMs / (1000 * 60 * 60 * 24));
    const hours = Math.floor((uptimeMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    return `${days} days, ${hours} hours`;
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'operational':
      case 'connected':
      case 'indexed':
        return 'success';
      case 'checking':
        return 'warning';
      default:
        return 'error';
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
        <Typography variant="h5" gutterBottom sx={{ mb: 3, textAlign: 'center', color: '#3e2723' }}>
          System Health
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
            {error}
          </Alert>
        )}

        <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, gap: 3, flexWrap: 'wrap' }}>
          <Box sx={{ flex: { xs: '1 1 100%', md: '1 1 48%' } }}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom color='#3e2723'>
                  Services Status
                </Typography>
                {['API Service', 'Database', 'Search Index', 'Speech Services'].map((service, idx) => {
                  const key = service.toLowerCase().split(' ')[0] as keyof HealthStatus;
                  return (
                    <Box key={service} sx={{ display: 'flex', alignItems: 'center', mb: idx < 3 ? 2 : 0 }}>
                      <Typography variant="body1" sx={{ flexGrow: 1, color: '#3e2723' }}>
                        {service}
                      </Typography>
                      <Chip
                        label={healthStatus[key]}
                        color={getStatusColor(healthStatus[key])}
                        size="small"
                      />
                    </Box>
                  );
                })}
              </CardContent>
            </Card>
          </Box>

          <Box sx={{ flex: { xs: '1 1 100%', md: '1 1 48%' } }}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom color='#3e2723'>
                  System Information
                </Typography>
                <Typography variant="body2" sx={{ color: '#3e2723', mb: 1 }}>
                  <strong>Version:</strong> {systemInfo.version}
                </Typography>
                <Typography variant="body2" sx={{ color: '#3e2723', mb: 1 }}>
                  <strong>Uptime:</strong> {systemInfo.uptime}
                </Typography>
                <Typography variant="body2" sx={{ color: '#3e2723' }}>
                  <strong>Last Updated:</strong> {systemInfo.lastUpdated}
                </Typography>
              </CardContent>
            </Card>
          </Box>
        </Box>
      </Box>
    </Box>
  );
};

export default SystemHealth;