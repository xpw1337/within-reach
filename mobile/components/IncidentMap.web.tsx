import { Text } from 'react-native';

type Point = { lat: number; lng: number };

/** react-native-maps has no web support; the web build (used only for bundle checks) shows coordinates. */
export function IncidentMap({ target }: { target: Point; title: string; me: Point | null }) {
  return (
    <Text>
      Map is shown on the phone. Location: {target.lat.toFixed(5)}, {target.lng.toFixed(5)}
    </Text>
  );
}
