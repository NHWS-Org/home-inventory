const label = document.querySelector<HTMLMetaElement>('meta[name="env-label"]')?.content.trim() ?? '';

// Etichetta d'ambiente (es. DEV) al centro in alto: non tocca gli angoli arrotondati dello schermo
// e resta sotto la safe area (notch/dynamic island). Non intercetta i click.
export default function EnvBadge() {
  if (!label) return null;
  return (
    <div
      className="fixed inset-x-0 top-0 z-[100] flex justify-center pointer-events-none"
      style={{ paddingTop: 'env(safe-area-inset-top)' }}
      aria-hidden="true"
    >
      <span className="rounded-b-md bg-amber-500/85 px-3 py-0.5 text-[10px] font-bold uppercase tracking-widest text-black shadow">
        {label}
      </span>
    </div>
  );
}
