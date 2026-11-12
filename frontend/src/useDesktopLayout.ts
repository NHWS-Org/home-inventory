import { useSyncExternalStore } from 'react';

const desktopQuery = '(min-width: 768px)';

function subscribe(onChange: () => void) {
  const media = window.matchMedia(desktopQuery);
  media.addEventListener('change', onChange);
  return () => media.removeEventListener('change', onChange);
}

function getSnapshot() {
  return window.matchMedia(desktopQuery).matches;
}

export function useDesktopLayout() {
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
