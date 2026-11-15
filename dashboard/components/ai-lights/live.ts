// Within Reach: the words the AI lights card shows, set from the live incident (VARIANTS contents).
import {useSyncExternalStore} from 'react';

export type AgentWords = {
  steps: [string, string, string];
  live: 0 | 1 | 2; // which step is running
  doing: string; // progress row
  cmd: string; // terminal command
  result: string; // terminal output
  prompt: string; // prompt bar
};

let words: AgentWords = {
  steps: ['Watch', 'Alert', 'Call 911'],
  live: 0,
  doing: 'Watching',
  cmd: 'camera',
  result: 'all clear',
  prompt: 'waiting for a fall or fire',
};
const listeners = new Set<() => void>();

export function setAgentWords(next: AgentWords): void {
  if (JSON.stringify(next) === JSON.stringify(words)) return;
  words = next;
  listeners.forEach(l => l());
}

export function useAgentWords(): AgentWords {
  return useSyncExternalStore(
    l => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => words,
    () => words,
  );
}
