import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, space } from '../components/theme';
import { Body, Button, Card, Field, Label, Notice, Screen, Segmented, Title, ToggleRow } from '../components/ui';
import { buildingLabel, searchBuildings } from '../lib/buildings';
import {
  CONSENT_CALLS_LABEL,
  CONSENT_LOCATION_HELP,
  CONSENT_LOCATION_LABEL,
  GOOD_SAMARITAN_LINE,
  PRIVACY_LINE,
  RESPONDER_ROLE_LABELS,
} from '../lib/copy';
import { isPlausiblePhone, saveProfile, useProfile } from '../lib/profile';
import { errorMessage, isSupabaseConfigured } from '../lib/supabase';
import type { BuildingRow, ResponderRole } from '../lib/types';

const ROLE_OPTIONS = (Object.keys(RESPONDER_ROLE_LABELS) as ResponderRole[]).map((value) => ({
  value,
  label: RESPONDER_ROLE_LABELS[value],
}));

export default function Onboarding() {
  const { profile } = useProfile();
  const editing = profile !== null;

  const [name, setName] = useState(profile?.name ?? '');
  const [phone, setPhone] = useState(profile?.phone ?? '');
  const [cprTrained, setCprTrained] = useState(profile?.cpr_trained ?? false);
  const [role, setRole] = useState<ResponderRole>(profile?.role ?? 'public');
  const [buildingId, setBuildingId] = useState<string | null>(profile?.building_id ?? null);
  const [buildingText, setBuildingText] = useState<string | null>(profile?.building_label ?? null);
  const [consentLocation, setConsentLocation] = useState(profile?.consent_location ?? false);
  const [consentCalls, setConsentCalls] = useState(profile?.consent_calls ?? false);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<BuildingRow[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [picking, setPicking] = useState(!editing);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!picking || !isSupabaseConfigured) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      searchBuildings(query)
        .then((rows) => {
          if (!cancelled) {
            setResults(rows);
            setSearchError(null);
          }
        })
        .catch((error) => {
          if (!cancelled) setSearchError(errorMessage(error));
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, picking]);

  const nameOk = name.trim().length > 0;
  const phoneOk = isPlausiblePhone(phone);
  const canSave = nameOk && phoneOk && !saving && isSupabaseConfigured;

  async function onSave() {
    setSaving(true);
    setSaveError(null);
    try {
      await saveProfile({
        name,
        phone,
        cpr_trained: cprTrained,
        role,
        building_id: buildingId,
        building_label: buildingText,
        consent_location: consentLocation,
        consent_calls: consentCalls,
      });
      if (router.canGoBack()) router.back();
      else router.replace('/');
    } catch (error) {
      setSaveError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Screen>
      <Title>{editing ? 'Your profile' : 'Become a responder'}</Title>
      <Body muted>
        When someone collapses nearby, Within Reach can alert you on this phone while the app is open.
      </Body>

      {!isSupabaseConfigured ? (
        <Notice tone="error">
          This build has no Supabase settings. Set EXPO_PUBLIC_SUPABASE_URL and EXPO_PUBLIC_SUPABASE_ANON_KEY in
          mobile/.env, then restart Expo.
        </Notice>
      ) : null}

      <Card>
        <Field label="Name" value={name} onChangeText={setName} autoComplete="name" textContentType="name" placeholder="Your name" />
        <Field
          label="Phone"
          value={phone}
          onChangeText={setPhone}
          keyboardType="phone-pad"
          autoComplete="tel"
          textContentType="telephoneNumber"
          placeholder="Include the country code"
        />
        {phone.length > 0 && !phoneOk ? <Text style={local.error}>That does not look like a phone number.</Text> : null}
        <ToggleRow label="I am trained in CPR" value={cprTrained} onValueChange={setCprTrained} />
      </Card>

      <Card>
        <Label>Role</Label>
        <Segmented options={ROLE_OPTIONS} value={role} onChange={setRole} />
      </Card>

      <Card>
        <Label>Building</Label>
        {!picking ? (
          <View style={local.row}>
            <Body>{buildingText ?? 'Not in a listed building'}</Body>
            <Button title="Change" kind="secondary" onPress={() => setPicking(true)} />
          </View>
        ) : (
          <>
            <Field label="Search" value={query} onChangeText={setQuery} placeholder="Building name or address" autoCorrect={false} />
            {searchError ? <Text style={local.error}>Could not load buildings: {searchError}</Text> : null}
            <Choice
              label="Not in a listed building"
              selected={buildingId === null}
              onPress={() => {
                setBuildingId(null);
                setBuildingText(null);
                setPicking(false);
              }}
            />
            {results.map((b) => (
              <Choice
                key={b.id}
                label={buildingLabel(b)}
                selected={b.id === buildingId}
                onPress={() => {
                  setBuildingId(b.id);
                  setBuildingText(buildingLabel(b));
                  setPicking(false);
                }}
              />
            ))}
          </>
        )}
      </Card>

      <Card>
        <Label>Consent</Label>
        <ToggleRow
          label={CONSENT_LOCATION_LABEL}
          help={CONSENT_LOCATION_HELP}
          value={consentLocation}
          onValueChange={setConsentLocation}
        />
        <ToggleRow label={CONSENT_CALLS_LABEL} value={consentCalls} onValueChange={setConsentCalls} />
        <Body muted>{PRIVACY_LINE}</Body>
        <Body muted>{GOOD_SAMARITAN_LINE}</Body>
      </Card>

      {saveError ? <Notice tone="error">Could not save: {saveError}</Notice> : null}
      <Button title={editing ? 'Save' : 'Join as a responder'} onPress={onSave} disabled={!canSave} busy={saving} big />
      {editing ? <Button title="Cancel" kind="secondary" onPress={() => router.back()} /> : null}
    </Screen>
  );
}

function Choice({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={[local.choice, selected && local.choiceSelected]}
    >
      <Text style={[local.choiceText, selected && local.choiceTextSelected]}>{label}</Text>
    </Pressable>
  );
}

const local = StyleSheet.create({
  row: { gap: space.sm },
  error: { color: colors.primary, fontSize: 14 },
  choice: {
    paddingVertical: space.md,
    paddingHorizontal: space.md,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
  },
  choiceSelected: { borderColor: colors.text, backgroundColor: colors.text },
  choiceText: { fontSize: 15, color: colors.text },
  choiceTextSelected: { color: colors.primaryText, fontWeight: '600' },
});
