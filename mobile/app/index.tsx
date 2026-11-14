import { router } from 'expo-router';

import { Body, Button, Card, Label, Screen, Title } from '../components/ui';
import { PRIVACY_LINE, RESPONDER_ROLE_LABELS } from '../lib/copy';
import { useProfile } from '../lib/profile';

export default function Home() {
  const { profile } = useProfile();
  if (!profile) return null;

  return (
    <Screen>
      <Title>Within Reach</Title>
      <Card>
        <Label>Responder</Label>
        <Body>{profile.name}</Body>
        <Body muted>
          {RESPONDER_ROLE_LABELS[profile.role]}
          {profile.cpr_trained ? ', CPR trained' : ''}
          {profile.building_label ? `, ${profile.building_label}` : ''}
        </Body>
      </Card>
      <Button title="Edit profile" kind="secondary" onPress={() => router.push('/onboarding')} />
      <Body muted>{PRIVACY_LINE}</Body>
    </Screen>
  );
}
