import { router } from 'expo-router';
import { useState } from 'react';
import { Linking, View } from 'react-native';

import { space } from '../components/theme';
import { Button, Field, Small, Screen, Title } from '../components/ui';
import { automaticServerUrl, updateSettings, useSettings } from '../lib/settings';
import { useSos } from '../lib/sos';

export default function SettingsScreen() {
  const { settings } = useSettings();
  const sos = useSos();
  const [name, setName] = useState(settings.name);
  const [phone, setPhone] = useState(settings.phone);
  const [server, setServer] = useState(settings.serverUrl);

  function save() {
    void updateSettings({ name: name.trim(), phone: phone.trim(), serverUrl: server.trim() });
    router.back();
  }

  return (
    <Screen>
      <Title>Settings</Title>
      <Field label="Name" value={name} onChangeText={setName} autoCapitalize="words" />
      <View style={{ gap: space.xs }}>
        <Field label="Phone number" value={phone} onChangeText={setPhone} keyboardType="phone-pad" />
        <Small>Rung when an emergency near you needs help, so you hear it with the app closed.</Small>
      </View>
      <View style={{ gap: space.xs }}>
        <Field
          label="Server"
          value={server}
          onChangeText={setServer}
          placeholder={automaticServerUrl() || 'http://192.168.1.20:8000'}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />
        <Small>Leave empty to find the laptop automatically. Now using {sos.server || 'nothing'}.</Small>
      </View>
      <Button title="Save" onPress={save} />
      {sos.locationStatus === 'denied' ? (
        <Button title="Open iPhone Settings" kind="secondary" onPress={() => void Linking.openSettings()} />
      ) : null}
      <Button title="Close" kind="ghost" onPress={() => router.back()} />
    </Screen>
  );
}

