// Crust composition: one ring segment per structural layer, in proportion to
// its thickness, with the total crust in the centre and a legend of
// thickness and share. Hovering a segment or a legend row highlights the
// layer (linked with the layer list and the cross-section).
import React from 'react';
import { cn } from './util';

export default function CrustDonut({ layers, size = 132, stroke = 20, highlight, onHover, caption }) {
  const rows = (layers || []).filter((l) => Number(l.h) > 0);
  const total = rows.reduce((s, l) => s + Number(l.h), 0);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const segGap = rows.length > 1 ? Math.min(3, c * 0.006) : 0;
  let acc = 0;
  return (
    <div className="flex items-center gap-x-5 gap-y-3 min-w-0 flex-wrap">
      <div className="relative flex-none" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
             aria-label={`Crust ${total.toFixed(0)} mm: ${rows.map((l) => `${l.name} ${Number(l.h).toFixed(0)} mm`).join(', ')}`}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--track)" strokeWidth={stroke} />
          {total > 0 && rows.map((l, k) => {
            const len = (Number(l.h) / total) * c;
            const off = acc;
            acc += len;
            const active = highlight === l.index;
            return (
              <circle key={k} cx={size / 2} cy={size / 2} r={r} fill="none" className="fp-ink transition-[stroke-width] duration-150"
                stroke={l.color} strokeWidth={active ? stroke + 4 : stroke}
                strokeDasharray={`${Math.max(0, len - segGap)} ${c}`} strokeDashoffset={-off}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
                onMouseEnter={onHover ? () => onHover(l.index) : undefined}
                onMouseLeave={onHover ? () => onHover(null) : undefined} />
            );
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="fp-num text-[26px] font-semibold leading-none text-[var(--text-bold)]">{total.toFixed(0)}</span>
          <span className="text-[11px] text-[var(--text-muted)] mt-1">mm crust</span>
        </div>
      </div>
      <ul className="m-0 p-0 list-none flex flex-col gap-1 min-w-[160px] flex-1">
        {rows.map((l, k) => (
          <li key={k}
              className={cn('flex items-center gap-2 rounded-md px-1.5 py-0.5 text-[12.5px] transition-colors',
                highlight === l.index && 'bg-[var(--accent-soft)]')}
              onMouseEnter={onHover ? () => onHover(l.index) : undefined}
              onMouseLeave={onHover ? () => onHover(null) : undefined}>
            <span className="fp-ink h-2.5 w-2.5 rounded-sm flex-none border border-[var(--hairline-strong)]" style={{ background: l.color }} aria-hidden="true" />
            <span className="font-semibold text-[var(--text-main)] truncate">{l.name}</span>
            <span className="ml-auto fp-num text-[var(--text-bold)] font-semibold">{Number(l.h).toFixed(0)}</span>
            <span className="fp-num text-[var(--text-muted)] w-9 text-right">{total ? `${((Number(l.h) / total) * 100).toFixed(0)}%` : ''}</span>
          </li>
        ))}
        {caption && <li className="text-[11.5px] text-[var(--text-muted)] pt-1 px-1.5">{caption}</li>}
      </ul>
    </div>
  );
}
