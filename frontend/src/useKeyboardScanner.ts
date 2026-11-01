import { useEffect, useRef } from 'react';

const MAX_KEY_INTERVAL_MS = 50;
const MIN_CODE_LENGTH = 6;

/**
 * Intercetta lettori barcode USB/Bluetooth in modalita' "tastiera": digitano il codice
 * a raffica (<50ms tra un tasto e l'altro) e chiudono con Invio. I tasti digitati a mano
 * o dentro campi di testo vengono ignorati.
 */
export function useKeyboardScanner(enabled: boolean, onScan: (code: string) => void) {
  const handlerRef = useRef(onScan);
  useEffect(() => {
    handlerRef.current = onScan;
  }, [onScan]);

  useEffect(() => {
    if (!enabled) return;
    let buffer = '';
    let lastKeyAt = 0;

    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) {
        buffer = '';
        return;
      }
      if (event.ctrlKey || event.metaKey || event.altKey) return;

      const now = performance.now();
      if (now - lastKeyAt > MAX_KEY_INTERVAL_MS) buffer = '';
      lastKeyAt = now;

      if (event.key === 'Enter') {
        if (buffer.length >= MIN_CODE_LENGTH) {
          event.preventDefault();
          const code = buffer;
          buffer = '';
          handlerRef.current(code);
        }
        buffer = '';
        return;
      }
      if (event.key.length === 1) buffer += event.key;
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [enabled]);
}
