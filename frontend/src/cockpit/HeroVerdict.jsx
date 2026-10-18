// The hero tile: the IRC verdict of the section on screen (the evaluated
// trial section, or the optimized design picked below), drawn as a ring gauge
// of the governing demand/capacity ratio with one smaller ring per criterion.
// Before any run it shows the design basis every check is made against.
import React from 'react';
import { Play, ArrowRight, Loader2, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react';
import { RingGauge, Chip } from './primitives';
import { cn, ratioTone } from './util';

const TONE_TEXT = { ok: 'var(--ok)', warn: 'var(--warn)', fail: 'var(--fail)', muted: 'var(--text-muted)' };

function BasisBig({ basis }) {
  return (
    <div className="flex flex-wrap items-end gap-x-10 gap-y-5">
      <div className="fp-kpi">
        <span className="fp-kpi-label">Design traffic</span>
        <span className="flex items-baseline gap-1.5">
          <span className="fp-hero-value">{basis.msa.toFixed(1)}</span>
          <span className="text-[16px] font-medium text-[var(--text-muted)]">msa</span>
        </span>
        <span className="fp-kpi-sub">R{basis.reliability} · {basis.designLife}-year period · {basis.roadLabel}</span>
      </div>
      <div className="flex gap-8">
        <div className="fp-kpi">
          <span className="fp-kpi-label">Allowable <span className="normal-case">εt</span></span>
          <span><span className="fp-kpi-value">{basis.allowT != null ? (basis.allowT * 1e6).toFixed(0) : '—'}</span><span className="fp-kpi-unit">µε</span></span>
          <span className="fp-kpi-sub">{basis.allowT != null ? `Eq. 3.${basis.reliability === 90 ? 4 : 3} · fatigue` : 'no bituminous layer'}</span>
        </div>
        <div className="fp-kpi">
          <span className="fp-kpi-label">Allowable <span className="normal-case">εv</span></span>
          <span><span className="fp-kpi-value">{basis.allowV != null ? (basis.allowV * 1e6).toFixed(0) : '—'}</span><span className="fp-kpi-unit">µε</span></span>
          <span className="fp-kpi-sub">Eq. 3.{basis.reliability === 90 ? 2 : 1} · rutting</span>
        </div>
      </div>
    </div>
  );
}

export default function HeroVerdict({ state, basis, verdict, onEvaluate, onOptimize, busyText, className }) {
  const chips = (state === 'design' && verdict?.chips) || basis;
  const head = (
    <div className="fp-tile-head">
      <h2 className="fp-tile-title" id="tile-hero-title">
        {state === 'design' ? 'Selected design' : state === 'evaluate' ? 'Trial section' : 'IRC verdict'}
      </h2>
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip tone="info" title={chips === basis ? 'Cumulative design traffic, IRC:37-2018 Eq. 4.5/4.6' : 'Design traffic this design was optimized for'}><span className="fp-num">{Number(chips.msa).toFixed(1)}</span>&nbsp;msa</Chip>
        <Chip tone="muted" title="Reliability per IRC:37-2018 §3.7">R{chips.reliability ?? chips.rel}</Chip>
        {chips.longLife && <Chip tone="ok" title="Long-life checks on (IRC:37-2018 §10)">Long-life</Chip>}
        {verdict?.stale && <Chip tone="warn" title={state === 'evaluate' ? 'An input changed after this evaluation — run Evaluate again' : 'An input changed after this optimization — run Optimize again'}>Inputs changed</Chip>}
      </div>
    </div>
  );

  let body;
  if (state === 'solving') {
    body = (
      <div className="flex flex-col sm:flex-row items-center gap-8 py-2" aria-live="polite">
        <div className="fp-skeleton rounded-full flex-none" style={{ width: 176, height: 176 }} />
        <div className="flex flex-col gap-3 flex-1 min-w-0 w-full">
          <span className="inline-flex items-center gap-2 text-[15px] font-semibold text-[var(--text-bold)]">
            <Loader2 size={18} className="animate-spin text-[var(--accent)]" aria-hidden="true" /> {busyText}
          </span>
          <div className="fp-skeleton h-4 w-2/3" />
          <div className="flex gap-4">{[0, 1, 2].map((k) => <div key={k} className="fp-skeleton rounded-full" style={{ width: 72, height: 72, animationDelay: `${k * 120}ms` }} />)}</div>
        </div>
      </div>
    );
  } else if (state === 'none') {
    body = (
      <div className="flex flex-col sm:flex-row items-center gap-8 py-2">
        <RingGauge ratio={verdict?.closest ?? 1.25} size={176} stroke={16} display={verdict?.closest != null ? `${verdict.closestLower ? '≥' : ''}${verdict.closest >= 10 ? `${verdict.closest.toFixed(0)}×` : `${(verdict.closest * 100).toFixed(0)}%`}` : '—'}
          label="Closest to passing" sub={verdict?.closest != null ? `max CDF ${verdict.closestLower ? '≥ ' : ''}${verdict.closest.toFixed(2)}` : undefined}
          title="Governing ratio of the design nearest to IRC adequacy (from the engine advisories)" />
        <div className="flex flex-col gap-2 min-w-0 flex-1">
          <span className="inline-flex items-center gap-2 text-[26px] font-bold leading-tight text-[var(--fail)]">
            <XCircle size={26} aria-hidden="true" /> No IRC-adequate design
          </span>
          <p className="m-0 text-[14px] leading-relaxed text-[var(--text-main)] max-w-[52ch]">
            Nothing in the constructable range passes every criterion. Raise the maximum thickness of the
            Opt layers, revisit the subgrade CBR, or check the traffic inputs (CVPD, VDF, growth, period).
            The engine advisories below name the governing failure.
          </p>
        </div>
      </div>
    );
  } else if (state === 'evaluate' || state === 'design') {
    const v = verdict;
    const tone = v.adequate == null ? 'muted' : v.adequate ? 'ok' : 'fail';
    const Icon = v.adequate == null ? AlertTriangle : v.adequate ? CheckCircle2 : XCircle;
    body = (
      <div className="flex flex-col md:flex-row items-center md:items-stretch gap-6 md:gap-8">
        <div className="flex flex-col items-center justify-center gap-1 flex-none">
          <RingGauge ratio={v.governing?.ratio} size={184} stroke={16}
            label={v.governing ? <>Governs · {v.governing.label}</> : 'Governing ratio'}
            ariaLabel={v.governing?.ariaLabel ? `Governs: ${v.governing.ariaLabel}` : v.governing && typeof v.governing.label === 'string' ? `Governs: ${v.governing.label}` : 'Governing ratio'}
            sub={v.governing?.ratio != null ? (v.governing.ratio > 1 ? `${((v.governing.ratio - 1) * 100).toFixed(0)}% over the limit`
              : v.governing.ratio < 0.1 ? 'far within the limit' : `${((1 / v.governing.ratio - 1) * 100).toFixed(0)}% structural reserve`) : undefined}
            title="Largest demand/capacity ratio of the applicable IRC criteria (CDF, or strain / long-life limit)" />
        </div>
        <div className="flex flex-col gap-4 min-w-0 flex-1 justify-center">
          <div className="flex flex-col gap-1">
            {v.title && <span className="text-[13px] font-bold" style={{ color: v.titleColor || 'var(--text-muted)' }}>{v.title}</span>}
            <span className="inline-flex items-center gap-2 text-[30px] font-bold leading-none" style={{ color: TONE_TEXT[tone] }}>
              <Icon size={28} aria-hidden="true" /> {v.statusText || (v.adequate == null ? 'Verdict incomplete' : v.adequate ? 'IRC-adequate' : 'Not IRC-adequate')}
            </span>
            <span className="fp-num text-[15px] text-[var(--text-main)] mt-1">
              <b className="text-[var(--text-bold)] font-semibold">{v.crust.toFixed(0)} mm</b> crust
              {v.bit > 0 && <> · <b className="text-[var(--text-bold)] font-semibold">{v.bit.toFixed(0)} mm</b> bituminous</>}
              {v.extra && <> · {v.extra}</>}
            </span>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-3">
            {v.ratios.map((r) => (
              <RingGauge key={r.key} ratio={r.ratio} size={78} stroke={8} label={r.label} ariaLabel={r.ariaLabel} sub={r.sub} title={r.title}
                display={r.display} className="w-[96px]" />
            ))}
          </div>
          {v.note && <p className="m-0 text-[12.5px] text-[var(--text-muted)] leading-snug">{v.note}</p>}
        </div>
      </div>
    );
  } else {
    body = (
      <div className="flex flex-col gap-6">
        <BasisBig basis={basis} />
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" onClick={onEvaluate} className="fp-tbtn h-10 px-4 text-[13.5px]"
            title="Analyse the trial section at the analysis points (Ctrl+Enter)">
            <Play size={15} aria-hidden="true" /> Evaluate trial section
          </button>
          <button type="button" onClick={onOptimize}
            className="fp-btn-grad h-10 px-4 rounded-[var(--radius-control)] text-[13.5px] font-bold inline-flex items-center gap-2"
            title="Search constructable thicknesses for the IRC-adequate archetypes (Ctrl+Shift+Enter)">
            <ArrowRight size={15} aria-hidden="true" /> Optimize thicknesses
          </button>
          <span className="text-[12px] text-[var(--text-muted)]">
            <kbd className="fp-num">Ctrl</kbd>+<kbd className="fp-num">Enter</kbd> evaluates · add <kbd className="fp-num">Shift</kbd> to optimize
          </span>
        </div>
      </div>
    );
  }

  return (
    <section id="tile-hero" aria-labelledby="tile-hero-title" className={cn('fp-tile', className)}
             data-tone={state === 'evaluate' || state === 'design' ? ratioTone(verdict?.governing?.ratio) : undefined}>
      {head}
      <div className="fp-tile-body flex-1 flex flex-col justify-center">{body}</div>
    </section>
  );
}
