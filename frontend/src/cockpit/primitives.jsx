// Bento cockpit primitives — the tile, KPI, utilization bar, chip, notice,
// segmented control and field row the cockpit composes. Styling lives in the
// `.fp-*` classes of src/index.css (light + .theme-dark tokens).
import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, AlertTriangle, CheckCircle2, Info, ChevronDown } from 'lucide-react';
import { cn, ratioTone } from './util';

const reduceMotion = () => {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; }
};

/* One engineering module: titled strip + dense body. `title` is a section
   heading (h2) — the app name is the page's h1. */
export function Tile({ title, icon: Icon, actions, className, bodyClassName, children, id, ...rest }) {
  return (
    <section id={id} className={cn('fp-tile', className)} aria-labelledby={id ? `${id}-title` : undefined} {...rest}>
      <div className="fp-tile-head">
        <h2 className="fp-tile-title" id={id ? `${id}-title` : undefined}>
          {Icon && <Icon size={14} aria-hidden="true" />}
          {title}
        </h2>
        {actions && <div className="flex items-center gap-1.5 min-w-0">{actions}</div>}
      </div>
      <div className={cn('fp-tile-body flex-1', bodyClassName)}>{children}</div>
    </section>
  );
}

/* A value that briefly washes with the accent colour when it changes, so the
   eye finds what moved after an input edit. Skipped on first render and when
   the user prefers reduced motion. */
export function FlashValue({ value, className, children, title }) {
  const ref = useRef(null);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    const el = ref.current;
    if (!el || reduceMotion() || typeof el.animate !== 'function') return;
    el.animate(
      [{ backgroundColor: 'rgba(234, 88, 12, 0.22)' }, { backgroundColor: 'rgba(234, 88, 12, 0)' }],
      { duration: 900, easing: 'ease-out' },
    );
  }, [value]);
  return <span ref={ref} className={className} title={title}>{children ?? value}</span>;
}

/* KPI cell: label, value (+unit), optional sub-line and status tone. */
export function Kpi({ label, value, unit, sub, tone, title, flashKey }) {
  const toneClass = tone === 'fail' ? 'text-[var(--fail)]' : tone === 'warn' ? 'text-[var(--warn)]'
    : tone === 'ok' ? 'text-[var(--ok)]' : '';
  return (
    <div className="fp-kpi" title={title}>
      <span className="fp-kpi-label">{label}</span>
      <span>
        <FlashValue value={flashKey ?? value} className={cn('fp-kpi-value', toneClass)}>{value}</FlashValue>
        {unit && <span className="fp-kpi-unit">{unit}</span>}
      </span>
      {sub && <span className="fp-kpi-sub">{sub}</span>}
    </div>
  );
}

const TONE_FILL = { ok: 'var(--ok)', warn: 'var(--warn)', fail: 'var(--fail)', muted: 'var(--text-muted)' };

/* Utilization bar for a ratio (CDF, strain / limit). The scale runs to 1.25 so
   an exceedance is visible; the tick marks the limit (1.0). */
export function UtilBar({ label, ratio, display, title, note, ariaLabel }) {
  const tone = ratioTone(ratio);
  const max = 1.25;
  const w = ratio == null ? 0 : Math.max(0, Math.min(1, Number(ratio) / max));
  return (
    <div className="flex flex-col gap-0.5" title={title}>
      <div className="flex items-baseline justify-between gap-2 text-[12.5px]">
        <span className="fp-kpi-label truncate">{label}</span>
        <span className="fp-num font-semibold" style={{ color: TONE_FILL[tone] }}>{display}</span>
      </div>
      <div className="fp-bar" role="meter" aria-label={ariaLabel || (typeof label === 'string' ? label : undefined)} aria-valuemin={0} aria-valuemax={max}
           aria-valuenow={ratio == null ? undefined : Number(ratio)} aria-valuetext={display}>
        <span style={{ width: `${w * 100}%`, background: TONE_FILL[tone] }} />
        <i className="fp-bar-limit" style={{ left: `${(1 / max) * 100}%` }} aria-hidden="true" />
      </div>
      {note && <span className="text-[11.5px] text-[var(--text-muted)] fp-num truncate">{note}</span>}
    </div>
  );
}

export function Chip({ tone = 'muted', children, title, className }) {
  return <span className={cn('fp-chip', `fp-chip-${tone}`, className)} title={title}>{children}</span>;
}

const NOTICE_ICON = { fail: AlertCircle, warn: AlertTriangle, ok: CheckCircle2, info: Info };

/* Tinted message box (error / warning / advisory). */
export function Notice({ tone = 'info', title, children, className, onDismiss }) {
  const Icon = NOTICE_ICON[tone] || Info;
  return (
    <div
      role={tone === 'fail' ? 'alert' : 'status'}
      className={cn('flex gap-2.5 rounded-[var(--radius-control)] border px-3 py-2.5 text-[12.5px] leading-snug', className)}
      style={{
        color: `var(--${tone})`,
        background: `var(--${tone}-soft)`,
        borderColor: `color-mix(in oklab, var(--${tone}) 30%, transparent)`,
      }}
    >
      <Icon size={15} className="flex-none mt-px" aria-hidden="true" />
      <div className="min-w-0 flex-1 text-[var(--text-main)]">
        {title && <div className="font-bold mb-0.5" style={{ color: `var(--${tone})` }}>{title}</div>}
        {children}
      </div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="flex-none self-start text-[10px] font-semibold px-1 rounded hover:bg-black/5"
                style={{ color: `var(--${tone})` }} aria-label="Dismiss">✕</button>
      )}
    </div>
  );
}

/* Segmented control for 2–4 exclusive options. */
export function Seg({ value, options, onChange, label, disabled }) {
  return (
    <div className="fp-seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={value === o.id}
          disabled={disabled}
          title={o.title}
          onClick={() => onChange(o.id)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* Label + control row. */
export function Field({ label, htmlFor, title, children, className }) {
  return (
    <div className={cn('fp-field', className)} title={title}>
      <label htmlFor={htmlFor}>{label}</label>
      <div className="min-w-0 flex items-center gap-1.5">{children}</div>
    </div>
  );
}

/* Switch (checkbox semantics). */
export function Toggle({ checked, onChange, label, disabled, title, id }) {
  return (
    <label className={cn('flex items-center gap-2.5 select-none text-[13px] font-medium text-[var(--text-main)]',
                         disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer')} title={title} htmlFor={id}>
      <span className="relative inline-flex h-5 w-9 flex-none">
        <input id={id} type="checkbox" role="switch" className="peer sr-only" checked={!!checked}
               disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
        <span className="absolute inset-0 rounded-full bg-[var(--track)] transition-colors peer-checked:bg-[var(--accent-strong)] peer-focus-visible:shadow-[var(--ring-accent)]" />
        <span className="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-[#fff] shadow transition-transform peer-checked:translate-x-4" />
      </span>
      <span className="min-w-0">{label}</span>
    </label>
  );
}

const TONE_STROKE = { ok: 'var(--ok)', warn: 'var(--warn)', fail: 'var(--fail)', muted: 'var(--text-muted)' };

/* Ring gauge for a demand/capacity ratio. The arc fills to min(ratio, 1);
   above 1 the ring is full and turns red. Centre: the ratio in per cent. */
export function RingGauge({ ratio, size = 96, stroke = 10, label, sub, display, title, className, ariaLabel }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const has = ratio != null && Number.isFinite(Number(ratio));
  const frac = has ? Math.max(0, Math.min(1, Number(ratio))) : 0;
  const tone = ratioTone(has ? Number(ratio) : null);
  const text = display ?? (has ? `${(Number(ratio) * 100).toFixed(0)}%` : '—');
  return (
    <div className={cn('flex flex-col items-center gap-1.5 min-w-0', className)} title={title}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
             aria-label={`${ariaLabel || (typeof label === 'string' ? label : 'Utilization')} ${text}`}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--track)" strokeWidth={stroke} />
          {has && (
            <circle
              key={text}
              className="fp-ring-arc"
              cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke={TONE_STROKE[tone]} strokeWidth={stroke} strokeLinecap="round"
              strokeDasharray={c} strokeDashoffset={c * (1 - frac)}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
              style={{ '--ring-c': c }}
            />
          )}
        </svg>
        <span className="absolute inset-0 flex items-center justify-center fp-num font-semibold text-[var(--text-bold)]"
              style={{ fontSize: Math.round(size * 0.22 * Math.min(1, 4 / Math.max(4, String(text).length))) }}>
          {text}
        </span>
      </div>
      {label && <span className="fp-kpi-label text-center">{label}</span>}
      {sub && <span className="text-[11.5px] text-[var(--text-muted)] text-center fp-num leading-tight">{sub}</span>}
    </div>
  );
}

/* Numbered, collapsible section of the input rail. Open state is per viewer
   (localStorage, best effort). */
export function RailSection({ id, num, title, summary, defaultOpen = false, children, actions }) {
  const key = `indopave_sec_${id}`;
  const [open, setOpen] = useState(() => {
    try { const v = localStorage.getItem(key); return v == null ? defaultOpen : v === '1'; } catch { return defaultOpen; }
  });
  const toggle = () => setOpen((o) => {
    try { localStorage.setItem(key, o ? '0' : '1'); } catch { /* preference only */ }
    return !o;
  });
  return (
    <section className="fp-sec" aria-labelledby={`sec-${id}`}>
      <h3 className="m-0">
        <button type="button" className="fp-sec-head" aria-expanded={open} aria-controls={open ? `secb-${id}` : undefined} onClick={toggle}>
          <span className="fp-sec-num" aria-hidden="true">{num}</span>
          <span className="min-w-0 flex-1 flex flex-col">
            <span className="fp-sec-title" id={`sec-${id}`}>{title}</span>
            {!open && summary && <span className="fp-sec-sum">{summary}</span>}
          </span>
          <ChevronDown size={16} aria-hidden="true"
            className={cn('flex-none text-[var(--text-muted)] transition-transform', open && 'rotate-180')} />
        </button>
      </h3>
      {open && (
        <div className="fp-sec-body fp-fade-up" id={`secb-${id}`}>
          {actions && <div className="flex flex-wrap items-center gap-2 -mt-1 mb-1">{actions}</div>}
          {children}
        </div>
      )}
    </section>
  );
}

/* Show more / fewer fields inside a section. */
export function More({ label = 'More', children }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex flex-col gap-1.5">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="self-start inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--accent-text)] hover:underline">
        <ChevronDown size={13} className={cn('transition-transform', open && 'rotate-180')} aria-hidden="true" />
        {open ? 'Fewer' : label}
      </button>
      {open && <div className="flex flex-col gap-1.5 fp-fade-up">{children}</div>}
    </div>
  );
}
