import React from 'react';
import { FormControlLabel, Switch, Typography } from '@mui/material';

interface SoundToggleProps {
  enabled: boolean;
  setEnabled: (val: boolean) => void;
}

const SoundToggle: React.FC<SoundToggleProps> = ({ enabled, setEnabled }) => {
  return (
    <FormControlLabel
      control={
        <Switch
          checked={enabled}
          onChange={() => setEnabled(!enabled)}
          color="primary"
        />
      }
      label={<Typography color="text.primary">Voice Output</Typography>}
      sx={{ alignSelf: 'flex-end', marginBottom: 2 }}
    />
  );
};

export default SoundToggle;
