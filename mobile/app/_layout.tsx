import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { colors } from '../components/theme';
import { useLocationReporter } from '../lib/location';
import { loadProfile, useProfile } from '../lib/profile';

export default function RootLayout() {
  const { ready, profile } = useProfile();

  useEffect(() => {
    void loadProfile();
  }, []);

  // Runs at the root so location keeps flowing on every screen while the app is open.
  useLocationReporter(profile?.id ?? null, Boolean(profile?.on_duty && profile?.consent_location));

  if (!ready) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.bg }}>
        <ActivityIndicator />
      </View>
    );
  }

  const hasProfile = profile !== null;
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.bg } }}>
        {/* Without a saved profile, protected screens fall through to onboarding. */}
        <Stack.Protected guard={hasProfile}>
          <Stack.Screen name="index" />
        </Stack.Protected>
        <Stack.Screen name="onboarding" />
      </Stack>
    </SafeAreaProvider>
  );
}
