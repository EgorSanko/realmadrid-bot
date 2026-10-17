import { useSyncExternalStore } from 'react';

/** Короткие всплывающие сообщения («Вы вошли как …»). Одно за раз, исчезает само. */

export interface Toast {
  id: number;
  text: string;
}

let current: Toast | null = null;
let seq = 0;
let timer: number | undefined;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

export function showToast(text: string, ms = 3500): void {
  current = { id: ++seq, text };
  emit();
  if (typeof window === 'undefined') return;
  window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    current = null;
    emit();
  }, ms);
}

export function useToast(): Toast | null {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => current,
    () => current,
  );
}
