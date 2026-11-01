import { useRef, useState } from 'react';

export function useBottomSheetDrag(onDismiss: () => void) {
  const startY = useRef<number | null>(null);
  const suppressClick = useRef(false);
  const suppressClickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [offset, setOffset] = useState(0);
  const [isDragging, setIsDragging] = useState(false);

  const onPointerDown = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    startY.current = event.clientY;
    setIsDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (startY.current === null) return;
    setOffset(Math.max(0, event.clientY - startY.current));
  };

  const finish = (event: React.PointerEvent<HTMLButtonElement>, dismiss: boolean) => {
    if (startY.current === null) return;
    const distance = event.clientY - startY.current;
    startY.current = null;
    setIsDragging(false);
    setOffset(0);
    if (Math.abs(distance) > 8) {
      suppressClick.current = true;
      if (suppressClickTimer.current) clearTimeout(suppressClickTimer.current);
      suppressClickTimer.current = setTimeout(() => {
        suppressClick.current = false;
      }, 300);
    }
    if (dismiss && distance >= 100) onDismiss();
  };

  const onClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    if (suppressClick.current) {
      event.preventDefault();
      suppressClick.current = false;
      if (suppressClickTimer.current) clearTimeout(suppressClickTimer.current);
      return;
    }
    onDismiss();
  };

  return {
    offset,
    isDragging,
    gripProps: {
      onClick,
      onPointerDown,
      onPointerMove,
      onPointerUp: (event: React.PointerEvent<HTMLButtonElement>) => finish(event, true),
      onPointerCancel: (event: React.PointerEvent<HTMLButtonElement>) => finish(event, false),
    },
  };
}
