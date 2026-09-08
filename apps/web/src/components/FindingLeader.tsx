import { useLayoutEffect, useRef, useState } from 'react';

export function FindingLeader({ active }: { active: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const [path, setPath] = useState<string | null>(null);
  const [end, setEnd] = useState<{ x: number; y: number } | null>(null);

  useLayoutEffect(() => {
    const root = host.current?.parentElement;
    if (!active || !root) {
      setPath(null);
      setEnd(null);
      return;
    }
    const measure = () => {
      const pin = root.querySelector('[data-finding-pin]');
      const target = root.querySelector('[data-finding-target]');
      if (!pin || !target) {
        setPath(null);
        setEnd(null);
        return;
      }
      const rb = root.getBoundingClientRect();
      const pb = pin.getBoundingClientRect();
      const tb = target.getBoundingClientRect();
      const x1 = pb.left + pb.width / 2 - rb.left;
      const y1 = pb.top + pb.height / 2 - rb.top;
      const x2 = pb.left < tb.left ? tb.left - rb.left : tb.left + tb.width / 2 - rb.left;
      const y2 = tb.top + tb.height / 2 - rb.top;
      setPath(`M ${x1} ${y1} L ${x1} ${y2} L ${x2} ${y2}`);
      setEnd({ x: x2, y: y2 });
    };
    measure();
    const frame = window.requestAnimationFrame(measure);
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    root.addEventListener('click', measure);
    root.addEventListener('input', measure);
    window.addEventListener('resize', measure);
    return () => {
      window.cancelAnimationFrame(frame);
      ro.disconnect();
      root.removeEventListener('click', measure);
      root.removeEventListener('input', measure);
      window.removeEventListener('resize', measure);
    };
  }, [active]);

  if (!active) return <div ref={host} className="finding-leader-host" aria-hidden />;
  return (
    <div ref={host} className="finding-leader-host" aria-hidden>
      {path && end ? (
        <svg className="finding-leader">
          <path d={path} />
          <circle cx={end.x} cy={end.y} r="2.25" />
        </svg>
      ) : null}
    </div>
  );
}
