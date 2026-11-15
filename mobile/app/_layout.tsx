import {
  Nunito_600SemiBold,
  Nunito_700Bold,
  Nunito_800ExtraBold,
  Nunito_900Black,
  useFonts,
} from '@expo-google-fonts/nunito';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { colors } from '../components/theme';
import { loadSettings, useSettings } from '../lib/settings';
import { useLocationReporter, useSosConnection } from '../lib/sos';

export default function RootLayout() {
  const { ready, settings } = useSettings();
  const [fontsLoaded, fontError] = useFonts({ Nunito_600SemiBold, Nunito_700Bold, Nunito_800ExtraBold, Nunito_900Black });

  useEffect(() => {
    void loadSettings();
  }, []);

  // At the root, so the connection and location keep running on every screen while the app is open.
  useSosConnection();
  useLocationReporter();

  if (!ready || (!fontsLoaded && !fontError)) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.white }}>
        <ActivityIndicator color={colors.red} />
      </View>
    );
  }
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.bg }, animation: 'fade' }}>
        <Stack.Protected guard={settings.onboarded}>
          <Stack.Screen name="index" />
          <Stack.Screen name="alert" options={{ gestureEnabled: false, presentation: 'fullScreenModal', animation: 'slide_from_bottom' }} />
          <Stack.Screen name="mission" options={{ gestureEnabled: false }} />
          <Stack.Screen name="settings" options={{ presentation: 'modal', animation: 'slide_from_bottom' }} />
          <Stack.Screen name="cpr" />
          <Stack.Screen name="aed-help" />
        </Stack.Protected>
        <Stack.Protected guard={!settings.onboarded}>
          <Stack.Screen name="welcome" />
        </Stack.Protected>
      </Stack>
    </SafeAreaProvider>
  );
}
