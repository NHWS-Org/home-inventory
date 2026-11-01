import { useEffect, useRef, useState } from 'react';
import { Dialog } from '@headlessui/react';
import { useBottomSheetDrag } from './useBottomSheetDrag';
import { BrowserMultiFormatReader } from '@zxing/browser';
import { BarcodeFormat } from '@zxing/library';

interface Props {
  open: boolean;
  onClose: () => void;
  onDetected: (code: string, format: string | null) => void;
}

interface NativeDetector {
  detect(source: HTMLVideoElement): Promise<{ rawValue: string; format: string; cornerPoints?: { x: number; y: number }[] }[]>;
}
type NativeDetectorCtor = {
  new (options?: { formats?: string[] }): NativeDetector;
  getSupportedFormats?: () => Promise<string[]>;
};

type Point = { x: number; y: number };
const HIGHLIGHT_MS = 700;

const VIDEO_CONSTRAINTS: MediaTrackConstraints = {
  facingMode: { ideal: 'environment' },
  width: { ideal: 1280 },
  height: { ideal: 720 },
};

type CameraCaps = { torch: boolean; zoom: { min: number; max: number; step: number } | null };
type ExtendedCaps = MediaTrackCapabilities & {
  torch?: boolean;
  zoom?: { min: number; max: number; step: number };
  focusMode?: string[];
};
const applyAdvanced = (track: MediaStreamTrack, c: Record<string, unknown>) =>
  track.applyConstraints({ advanced: [c as MediaTrackConstraintSet] });

const NATIVE_FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code', 'data_matrix'];

export default function BarcodeScanner({ open, onClose, onDetected }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const onDetectedRef = useRef(onDetected);
  useEffect(() => {
    onDetectedRef.current = onDetected;
  }, [onDetected]);
  const [videoReady, setVideoReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualCode, setManualCode] = useState('');
  const [caps, setCaps] = useState<CameraCaps | null>(null);
  const [torchOn, setTorchOn] = useState(false);
  const [zoom, setZoom] = useState(1);

  const currentTrack = () =>
    (videoRef.current?.srcObject as MediaStream | null)?.getVideoTracks()[0] ?? null;

  // Legge le capacità della fotocamera (flash, zoom) e attiva la messa a fuoco continua se disponibile
  const readCaps = () => {
    const track = currentTrack();
    if (!track?.getCapabilities) return;
    const c = track.getCapabilities() as ExtendedCaps;
    if (c.focusMode?.includes('continuous')) applyAdvanced(track, { focusMode: 'continuous' }).catch(() => {});
    setTorchOn(false);
    setZoom(c.zoom?.min ?? 1);
    setCaps({ torch: !!c.torch, zoom: c.zoom ?? null });
  };

  const toggleTorch = async () => {
    const track = currentTrack();
    if (!track) return;
    try {
      await applyAdvanced(track, { torch: !torchOn });
      setTorchOn(!torchOn);
    } catch {
      setCaps((prev) => (prev ? { ...prev, torch: false } : prev));
    }
  };

  const changeZoom = (value: number) => {
    const track = currentTrack();
    setZoom(value);
    if (track) applyAdvanced(track, { zoom: value }).catch(() => {});
  };

  useEffect(() => {
    const videoEl = videoRef.current;
    if (!open || !videoReady || !videoEl) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      queueMicrotask(() => setError('Fotocamera non disponibile (serve HTTPS o localhost): inserisci il codice a mano.'));
      return;
    }

    let cancelled = false;
    let stop: () => void = () => {};
    let emitTimer: number | undefined;

    // Disegna i punti rilevati (coordinate video) sul canvas, tenendo conto di object-cover.
    const highlight = (points: Point[]) => {
      const canvas = canvasRef.current;
      if (!canvas || points.length === 0 || !videoEl.videoWidth) return;
      const cw = videoEl.clientWidth;
      const ch = videoEl.clientHeight;
      canvas.width = cw;
      canvas.height = ch;
      const scale = Math.max(cw / videoEl.videoWidth, ch / videoEl.videoHeight);
      const offX = (cw - videoEl.videoWidth * scale) / 2;
      const offY = (ch - videoEl.videoHeight * scale) / 2;
      const mapped = points.map((pt) => ({ x: pt.x * scale + offX, y: pt.y * scale + offY }));
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.clearRect(0, 0, cw, ch);
      ctx.strokeStyle = '#22c55e';
      ctx.fillStyle = '#22c55e';
      ctx.lineWidth = 4;
      if (mapped.length >= 3) {
        ctx.beginPath();
        mapped.forEach((pt, i) => (i === 0 ? ctx.moveTo(pt.x, pt.y) : ctx.lineTo(pt.x, pt.y)));
        ctx.closePath();
        ctx.stroke();
      } else if (mapped.length === 2) {
        ctx.beginPath();
        ctx.moveTo(mapped[0].x, mapped[0].y);
        ctx.lineTo(mapped[1].x, mapped[1].y);
        ctx.stroke();
      }
      mapped.forEach((pt) => {
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 6, 0, Math.PI * 2);
        ctx.fill();
      });
    };

    const emit = (code: string, format: string | null, points: Point[] = []) => {
      if (cancelled) return;
      cancelled = true;
      highlight(points);
      // il flusso resta attivo per mostrare l'evidenziazione prima di chiudere
      emitTimer = window.setTimeout(() => {
        stop();
        onDetectedRef.current(code, format);
      }, points.length > 0 ? HIGHLIGHT_MS : 0);
    };
    const fail = (err: unknown) => {
      if (cancelled) return;
      const name = (err as { name?: string })?.name;
      setError(
        name === 'NotAllowedError'
          ? 'Permesso fotocamera negato: inserisci il codice a mano o abilita la fotocamera.'
          : 'Impossibile avviare la fotocamera: inserisci il codice a mano.',
      );
    };

    const Native = (window as unknown as { BarcodeDetector?: NativeDetectorCtor }).BarcodeDetector;

    const startNative = async (Ctor: NativeDetectorCtor) => {
      const supported = (await Ctor.getSupportedFormats?.()) ?? NATIVE_FORMATS;
      const detector = new Ctor({ formats: NATIVE_FORMATS.filter((f) => supported.includes(f)) });
      const stream = await navigator.mediaDevices.getUserMedia({
        video: VIDEO_CONSTRAINTS,
        audio: false,
      });
      if (cancelled) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      videoEl.srcObject = stream;
      await videoEl.play();
      const timer = window.setInterval(async () => {
        if (cancelled || videoEl.readyState < 2) return;
        try {
          const found = await detector.detect(videoEl);
          if (found.length > 0) emit(found[0].rawValue, found[0].format, found[0].cornerPoints ?? []);
        } catch {
          // frame non leggibile: si riprova al tick successivo
        }
      }, 200);
      stop = () => {
        window.clearInterval(timer);
        stream.getTracks().forEach((t) => t.stop());
        videoEl.srcObject = null;
      };
    };

    const startZxing = async () => {
      const reader = new BrowserMultiFormatReader();
      const controls = await reader.decodeFromConstraints(
        { video: VIDEO_CONSTRAINTS, audio: false },
        videoEl,
        (result) => {
          if (result) {
            const points = (result.getResultPoints() ?? []).map((pt) => ({ x: pt.getX(), y: pt.getY() }));
            emit(result.getText(), BarcodeFormat[result.getBarcodeFormat()]?.toLowerCase() ?? null, points);
          }
        },
      );
      if (cancelled) {
        controls.stop();
        return;
      }
      stop = () => controls.stop();
    };

    (Native ? startNative(Native).catch(() => startZxing()) : startZxing()).catch(fail);

    return () => {
      cancelled = true;
      window.clearTimeout(emitTimer);
      stop();
    };
  }, [open, videoReady, onDetected]);

  const closeAndReset = () => {
    setCaps(null);
    setTorchOn(false);
    setError(null);
    setManualCode('');
    onClose();
  };

  const sheetDrag = useBottomSheetDrag(closeAndReset);

  const submitManual = () => {
    const code = manualCode.trim();
    if (!code) return;
    setManualCode('');
    onDetected(code, null);
  };

  return (
    <Dialog open={open} onClose={closeAndReset} className="relative z-[60]">
      <div className="fixed inset-0 bg-black/60" aria-hidden="true" />
      <div className="fixed inset-0 flex items-end justify-center sm:items-center sm:p-4">
        <Dialog.Panel
          style={{ transform: `translateY(${sheetDrag.offset}px)`, transition: sheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }}
          className="flex max-h-[92dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-3xl bg-white shadow-2xl dark:bg-gray-900 dark:text-white sm:rounded-2xl"
        >
          <div className="shrink-0 px-4 pb-3 pt-2 sm:p-5 sm:pb-3">
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...sheetDrag.gripProps} className="mx-auto mb-2 flex h-8 w-16 touch-none items-center justify-center sm:hidden">
              <span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" />
            </button>
            <div className="flex items-center justify-between gap-3">
              <Dialog.Title className="text-lg font-semibold">Scansiona codice</Dialog.Title>
              <button type="button" onClick={closeAndReset} aria-label="Chiudi scanner" className="grid h-10 w-10 shrink-0 place-items-center rounded-xl text-2xl text-gray-500 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800">×</button>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-3 sm:px-5">
          {error ? (
            <p className="text-sm text-red-600 mb-3">{error}</p>
          ) : (
            <div className="relative w-full rounded bg-black aspect-[4/3] sm:aspect-video overflow-hidden mb-3">
              <video
                ref={(el) => {
                  videoRef.current = el;
                  setVideoReady(el !== null);
                }}
                className="absolute inset-0 w-full h-full object-cover"
                muted
                playsInline
                onPlaying={readCaps}
              />
              <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />
              {/* guida di allineamento: riquadro + linea centrale */}
              <div className="absolute inset-0 pointer-events-none flex items-center justify-center">
                <div className="relative w-4/5 h-1/2 border-2 border-white/80 rounded-lg shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]">
                  <div className="absolute left-2 right-2 top-1/2 h-0.5 -translate-y-1/2 bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.9)]" />
                </div>
              </div>
              {caps && (caps.torch || caps.zoom) && (
                <div className="absolute top-2 inset-x-2 flex items-center gap-2">
                  {caps.torch && (
                    <button
                      type="button"
                      onClick={() => void toggleTorch()}
                      aria-pressed={torchOn}
                      aria-label="Flash"
                      className={`w-10 h-10 shrink-0 rounded-full text-xl flex items-center justify-center ${
                        torchOn ? 'bg-yellow-400 text-black' : 'bg-black/50 text-white'
                      }`}
                    >
                      🔦
                    </button>
                  )}
                  {caps.zoom && caps.zoom.max > caps.zoom.min && (
                    <input
                      type="range"
                      aria-label="Zoom"
                      className="flex-1"
                      min={caps.zoom.min}
                      max={Math.min(caps.zoom.max, 8)}
                      step={caps.zoom.step || 0.1}
                      value={zoom}
                      onChange={(e) => changeZoom(Number(e.target.value))}
                    />
                  )}
                </div>
              )}
              <p className="absolute bottom-1 inset-x-0 text-center text-xs text-white/90 pointer-events-none">
                Allinea il codice alla linea rossa
              </p>
            </div>
          )}
          <form
            className="mb-3 grid grid-cols-[1fr_auto] gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              submitManual();
            }}
          >
            <input
              type="text"
              inputMode="text"
              placeholder="Oppure digita / incolla il codice"
              className="min-h-12 min-w-0 rounded-xl border px-3"
              value={manualCode}
              onChange={(e) => setManualCode(e.target.value)}
            />
            <button type="submit" className="min-h-12 rounded-xl bg-blue-600 px-5 font-medium text-white hover:bg-blue-700">
              Leggi
            </button>
          </form>
          </div>
          <div className="shrink-0 border-t border-gray-200 bg-white p-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] dark:border-gray-700 dark:bg-gray-900 sm:pb-4">
            <button type="button" onClick={closeAndReset} className="min-h-12 w-full rounded-xl bg-gray-300 px-4 font-medium text-gray-900 hover:bg-gray-400 dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600">Chiudi</button>
          </div>
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}
