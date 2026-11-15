import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, font, radius, space, type } from '../components/theme';
import { Body, Button, Card, Field, Hero, Label, Notice, Progress, Screen, Segmented, Small, Title, ToggleRow } from '../components/ui';
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

// First run: the step-by-step flow of the sos/phone-app redesign (one question per screen, a progress
// bar, a big button at the bottom). Editing later: the one-page form. Both collect the same fields
// (spec section 9.11) and save them the same way (lib/profile.ts saveProfile).

const ROLE_OPTIONS = (Object.keys(RESPONDER_ROLE_LABELS) as ResponderRole[]).map((value) => ({
  value,
  label: RESPONDER_ROLE_LABELS[value],
}));

const STEPS = ['intro', 'name', 'phone', 'about', 'building', 'consent'] as const;
type Step = (typeof STEPS)[number];

export default function Onboarding() {
  const { profile } = useProfile();
  const editing = profile !== null;

  const [name, setName] = useState(profile?.name ?? '');
  const [phone, setPhone] = useState(profile?.phone ?? '');
  const [cprTrained, setCprTrained] = useState(profile?.cpr_trained ?? false);
  const [role, setRole] = useState<ResponderRole>(profile?.role ?? 'public');
  const [buildingId, setBuildingId] = useState<string | null>(profile?.building_id ?? null);
  const [buildingText, setBuildingText] = useState<string | null>(profile?.building_label ?? null);
  // First run: location on by default (the alert and the walk to the AED need it); calls are opt-in.
  const [consentLocation, setConsentLocation] = useState(profile?.consent_location ?? !editing);
  const [consentCalls, setConsentCalls] = useState(profile?.consent_calls ?? false);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<BuildingRow[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [picking, setPicking] = useState(!editing);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [step, setStep] = useState<Step>('intro');

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

  const buildingPicker = (
    <BuildingPicker
      picking={picking}
      setPicking={setPicking}
      query={query}
      setQuery={setQuery}
      results={results}
      searchError={searchError}
      buildingId={buildingId}
      buildingText={buildingText}
      choose={(id, text) => {
        setBuildingId(id);
        setBuildingText(text);
        setPicking(false);
      }}
    />
  );
  const supabaseMissing = !isSupabaseConfigured ? (
    <Notice tone="error">
      This build has no Supabase settings. Set EXPO_PUBLIC_SUPABASE_URL and EXPO_PUBLIC_SUPABASE_ANON_KEY in mobile/.env,
      then restart Expo.
    </Notice>
  ) : null;

  if (editing) {
    return (
      <Screen>
        <Title>Your profile</Title>
        <Body muted>When someone collapses nearby, Within Reach can alert you on this phone while the app is open.</Body>
        {supabaseMissing}
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
          {buildingPicker}
        </Card>
        <Card>
          <Label>Consent</Label>
          <ToggleRow label={CONSENT_LOCATION_LABEL} help={CONSENT_LOCATION_HELP} value={consentLocation} onValueChange={setConsentLocation} />
          <ToggleRow label={CONSENT_CALLS_LABEL} value={consentCalls} onValueChange={setConsentCalls} />
          <Small>{PRIVACY_LINE}</Small>
          <Small>{GOOD_SAMARITAN_LINE}</Small>
        </Card>
        {saveError ? <Notice tone="error">Could not save: {saveError}</Notice> : null}
        <Button title="Save" onPress={onSave} disabled={!canSave} busy={saving} big />
        <Button title="Cancel" kind="secondary" onPress={() => router.back()} />
      </Screen>
    );
  }

  const index = STEPS.indexOf(step);
  const next = () => setStep(STEPS[Math.min(STEPS.length - 1, index + 1)]);
  const back = () => index > 0 && setStep(STEPS[index - 1]);

  return (
    <SafeAreaView style={local.flex} edges={['top', 'bottom']}>
      <KeyboardAvoidingView style={local.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        {step !== 'intro' ? (
          <View style={local.top}>
            <Pressable onPress={back} hitSlop={12} accessibilityRole="button" accessibilityLabel="Back">
              <Ionicons name="arrow-back" size={26} color={colors.faint} />
            </Pressable>
            <View style={local.flex}>
              <Progress value={index / (STEPS.length - 1)} />
            </View>
          </View>
        ) : null}

        <ScrollView contentContainerStyle={local.body} keyboardShouldPersistTaps="handled">
          {step === 'intro' ? (
            <>
              <View style={local.badge}>
                <Ionicons name="heart" size={64} color={colors.white} />
              </View>
              <Hero center>Be the help{'\n'}that arrives first</Hero>
              <Body muted>
                When a camera sees someone collapse nearby, Within Reach alerts the people closest to them and walks
                them there, past the nearest AED.
              </Body>
              {supabaseMissing}
            </>
          ) : null}

          {step === 'name' ? (
            <>
              <Text style={type.title}>What should we call you?</Text>
              <Field
                label="Name"
                value={name}
                onChangeText={setName}
                placeholder="First name"
                autoFocus
                autoCapitalize="words"
                autoComplete="name"
                textContentType="name"
                returnKeyType="next"
                onSubmitEditing={() => nameOk && next()}
              />
              <Small>The desk sees this name when you accept an alert.</Small>
            </>
          ) : null}

          {step === 'phone' ? (
            <>
              <Text style={type.title}>Your phone number</Text>
              <Field
                label="Phone"
                value={phone}
                onChangeText={setPhone}
                placeholder="Include the country code"
                autoFocus
                keyboardType="phone-pad"
                textContentType="telephoneNumber"
                autoComplete="tel"
              />
              {phone.length > 0 && !phoneOk ? <Text style={local.error}>That does not look like a phone number.</Text> : null}
              <View style={local.why}>
                <Ionicons name="call" size={20} color={colors.red} />
                <View style={local.flex}>
                  <ToggleRow label={CONSENT_CALLS_LABEL} value={consentCalls} onValueChange={setConsentCalls} />
                </View>
              </View>
            </>
          ) : null}

          {step === 'about' ? (
            <>
              <Text style={type.title}>A bit about you</Text>
              <Card>
                <ToggleRow label="I am trained in CPR" value={cprTrained} onValueChange={setCprTrained} />
              </Card>
              <Label>Role</Label>
              <Segmented options={ROLE_OPTIONS} value={role} onChange={setRole} />
            </>
          ) : null}

          {step === 'building' ? (
            <>
              <Text style={type.title}>Where are you based?</Text>
              <Small>Pick your building, or skip if it is not listed.</Small>
              {buildingPicker}
            </>
          ) : null}

          {step === 'consent' ? (
            <>
              <View style={[local.badge, { backgroundColor: colors.blue }]}>
                <Ionicons name="navigate" size={56} color={colors.white} />
              </View>
              <Text style={[type.title, local.center]}>Share your location</Text>
              <Card>
                <ToggleRow label={CONSENT_LOCATION_LABEL} help={CONSENT_LOCATION_HELP} value={consentLocation} onValueChange={setConsentLocation} />
              </Card>
              <Small>{PRIVACY_LINE}</Small>
              <Small>{GOOD_SAMARITAN_LINE}</Small>
              {saveError ? <Notice tone="error">Could not save: {saveError}</Notice> : null}
            </>
          ) : null}
        </ScrollView>

        <View style={local.footer}>
          {step === 'intro' ? <Button title="Get started" onPress={next} /> : null}
          {step === 'name' ? <Button title="Continue" disabled={!nameOk} onPress={next} /> : null}
          {step === 'phone' ? <Button title="Continue" disabled={!phoneOk} onPress={next} /> : null}
          {step === 'about' ? <Button title="Continue" onPress={next} /> : null}
          {step === 'building' ? <Button title={buildingId ? 'Continue' : 'Skip'} onPress={next} /> : null}
          {step === 'consent' ? (
            <Button title="Join as a responder" icon="heart" onPress={() => void onSave()} disabled={!canSave} busy={saving} />
          ) : null}
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function BuildingPicker({
  picking,
  setPicking,
  query,
  setQuery,
  results,
  searchError,
  buildingId,
  buildingText,
  choose,
}: {
  picking: boolean;
  setPicking: (v: boolean) => void;
  query: string;
  setQuery: (v: string) => void;
  results: BuildingRow[];
  searchError: string | null;
  buildingId: string | null;
  buildingText: string | null;
  choose: (id: string | null, text: string | null) => void;
}) {
  if (!picking) {
    return (
      <View style={local.row}>
        <Body>{buildingText ?? 'Not in a listed building'}</Body>
        <Button title="Change" kind="secondary" onPress={() => setPicking(true)} />
      </View>
    );
  }
  return (
    <>
      <Field label="Search" value={query} onChangeText={setQuery} placeholder="Building name or address" autoCorrect={false} />
      {searchError ? <Text style={local.error}>Could not load buildings: {searchError}</Text> : null}
      <Choice label="Not in a listed building" selected={buildingId === null} onPress={() => choose(null, null)} />
      {results.map((b) => (
        <Choice key={b.id} label={buildingLabel(b)} selected={b.id === buildingId} onPress={() => choose(b.id, buildingLabel(b))} />
      ))}
    </>
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
  flex: { flex: 1, backgroundColor: colors.white },
  top: { flexDirection: 'row', alignItems: 'center', gap: space.lg, paddingHorizontal: space.xl, paddingTop: space.md },
  body: { flexGrow: 1, padding: space.xl, gap: space.lg, justifyContent: 'center' },
  center: { textAlign: 'center' },
  badge: {
    width: 120,
    height: 120,
    borderRadius: 60,
    backgroundColor: colors.red,
    alignSelf: 'center',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.md,
    borderBottomWidth: 6,
    borderBottomColor: 'rgba(0,0,0,0.15)',
  },
  why: { flexDirection: 'row', gap: space.sm, backgroundColor: colors.redSoft, padding: space.md, borderRadius: 14, alignItems: 'center' },
  footer: { padding: space.xl, paddingTop: 0 },
  row: { gap: space.sm },
  error: { color: colors.red, fontSize: 14, fontFamily: font.bold },
  choice: {
    paddingVertical: space.md,
    paddingHorizontal: space.lg,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.line,
    backgroundColor: colors.white,
  },
  choiceSelected: { borderColor: colors.red, backgroundColor: colors.redSoft },
  choiceText: { fontFamily: font.bold, fontSize: 16, color: colors.ink },
  choiceTextSelected: { color: colors.red, fontFamily: font.heavy },
});
