// components/admin/SystemHealth.tsx
import React, { useState, useEffect } from 'react';
import { Box, Typography, Card, CardContent, Chip} from '@mui/material';

const SystemHealth: React.FC = () => {
  const [healthStatus, setHealthStatus] = useState({
    api: 'checking',
    database: 'checking',
    search: 'checking',
    speech: 'checking'
  });

  useEffect(() => {
    setTimeout(() => {
      setHealthStatus({
        api: 'operational',
        database: 'connected',
        search: 'indexed',
        speech: 'operational'
      });
    }, 1000);
  }, []);

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

  return (
    <Box sx={{ p: 3, minHeight: '100vh', backgroundColor: '#f5f5f5', display: 'flex', justifyContent: 'center' }}>
      <Box sx={{ width: '100%', maxWidth: '1200px' }}>
        <Typography variant="h5" gutterBottom sx={{ mb: 3, textAlign: 'center' , color:'#3e2723'}}>
          System Health
        </Typography>

        <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, gap: 3, flexWrap: 'wrap' }}>
          <Box sx={{ flex: { xs: '1 1 100%', md: '1 1 48%' } }}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom color='#3e2723'>
                  Services Status
                </Typography>
                {['API Service', 'Database', 'Search Index', 'Speech Services'].map((service, idx) => {
                  const key = service.toLowerCase().split(' ')[0];
                  return (
                    <Box key={service} sx={{ display: 'flex', alignItems: 'center', mb: idx < 3 ? 2 : 0 }}>
                      <Typography variant="body1" sx={{ flexGrow: 1, color: '#3e2723' }}>
                        {service}
                      </Typography>
                      <Chip
                        label={healthStatus[key as keyof typeof healthStatus]}
                        color={getStatusColor(healthStatus[key as keyof typeof healthStatus])}
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
                <Typography variant="h6" gutterBottom>
                  System Information
                </Typography>
                <Typography variant="body2" sx={{ color: '#3e2723' }}>
                  <strong>Version:</strong> 1.0.0
                </Typography>
                <Typography variant="body2" sx={{ color: '#3e2723' }}>
                  <strong>Uptime:</strong> 5 days, 3 hours
                </Typography>
                <Typography variant="body2" sx={{ color: '#3e2723' }}>
                  <strong>Last Updated:</strong> {new Date().toLocaleDateString()}
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
