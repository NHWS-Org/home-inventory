import { useCallback, useSyncExternalStore } from 'react';

export function useDesktopLayout(minWidth = 768) {
  const query = `(min-width: ${minWidth}px)`;
  const subscribe = useCallback((onChange: () => void) => {
    const media = window.matchMedia(query);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, [query]);
  const getSnapshot = useCallback(() => window.matchMedia(query).matches, [query]);
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
