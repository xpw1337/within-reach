import { router } from 'expo-router';
import { useEffect } from 'react';

import { Body, Button, Screen, Title } from '../components/ui';
import { stopAlarm } from '../lib/alarm';
import { RELEASED_BODY, RELEASED_TITLE } from '../lib/copy';
import { closeAlert } from '../lib/useDispatches';

export default function Released() {
  useEffect(() => {
    stopAlarm();
  }, []);

  return (
    <Screen>
      <Title>{RELEASED_TITLE}</Title>
      <Body>{RELEASED_BODY}</Body>
      <Button
        title="Back to home"
        onPress={() => {
          closeAlert();
          if (router.canDismiss()) router.dismissTo('/');
          else router.replace('/');
        }}
      />
    </Screen>
  );
}
