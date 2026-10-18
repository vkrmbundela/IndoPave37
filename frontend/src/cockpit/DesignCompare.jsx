// Fills the rest of the results row: a side-by-side comparison when the
// optimizer returned several archetypes, or what to switch on to get more.
import React from 'react';
import { GitCompare, Lightbulb } from 'lucide-react';
import { Chip, Toggle } from './primitives';
import { archetypeTone, ratioTone, cn } from './util';

const BIT = /\b(BC|DBM|BM|SDBC|SMA)\b/;
const govRatio = (det) => Math.max(det.CDF_fatigue || 0, det.CDF_rutting || 0, det.CDF_ctb || 0, det.long_life?.ratio || 0);

export default function DesignCompare({ designs, className, optimizeByCost, optimizeByCo2, setOptimizeByCost, setOptimizeByCo2, onRerun, busy, selected, onSelect, wide }) {
  if (designs.length < 2) {
    const merged = (designs[0]?.details?.strategy || '').includes('+');
    const objectivesOn = optimizeByCost || optimizeByCo2;
    return (
      <section className={cn('fp-tile p-5 flex flex-col gap-3 self-start', className)} aria-label="More archetypes">
        <div className="flex items-center gap-2 text-[14px] font-bold text-[var(--text-bold)]">
          <Lightbulb size={16} className="text-[var(--accent)]" aria-hidden="true" />
          {merged ? 'Every objective chose the same section' : 'One archetype — the thinnest IRC-adequate section'}
        </div>
        {merged || objectivesOn ? (
          <p className="m-0 text-[13px] text-[var(--text-muted)] leading-relaxed max-w-[70ch]">
            The thinnest adequate design is also the cheapest and the lowest-carbon here, so the archetypes merge
            into one card. Real trade-offs appear when more than one layer may vary: set further layers to
            <b> Opt</b> with a min–max range (for example the granular base against the DBM) and optimize again.
          </p>
        ) : (
          <>
            <p className="m-0 text-[13px] text-[var(--text-muted)] leading-relaxed max-w-[70ch]">
              Turn on the cost and carbon objectives to add the Economy (lowest ₹ per lane-km), Sustainable
              (lowest embodied CO₂) and Premium (best combined) archetypes, then optimize again. Designs that win
              several objectives merge into one card.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <Toggle id="cmpCost" checked={optimizeByCost} onChange={setOptimizeByCost} label="Cost" />
              <Toggle id="cmpCo2" checked={optimizeByCo2} onChange={setOptimizeByCo2} label="Embodied CO₂" />
              <button type="button" className="fp-btn-grad h-8 px-3 rounded-[var(--radius-control)] text-[12.5px] font-bold"
                disabled={busy || (!optimizeByCost && !optimizeByCo2)} onClick={onRerun}>Optimize again</button>
            </div>
          </>
        )}
      </section>
    );
  }
  const rows = designs.map((d, i) => {
    const det = d.details || {};
    const bit = (det.layers || []).filter((l) => BIT.test(String(l.name).toUpperCase())).reduce((s2, l) => s2 + Number(l.thickness || 0), 0);
    return {
      i, det, bit, gov: govRatio(det),
      crust: Number(d.total_thickness),
      cost: d.cost != null ? Number(d.cost) / 1e5 : null,
      co2: d.co2 != null ? Number(d.co2) / 1000 : null,
      color: archetypeTone(det.strategy).color,
      label: (det.strategy || 'Design').replace(/\s*\+\s*Premium$/, ' = Premium'),
    };
  });
  const metrics = [
    { key: 'crust', label: 'Crust', unit: 'mm', fmt: (x) => x.toFixed(0), title: 'Total crust thickness' },
    { key: 'cost', label: 'Material cost', unit: '₹ lakh / lane-km', fmt: (x) => x.toFixed(1), title: 'Material cost per km of a 3.5 m lane' },
    { key: 'co2', label: 'Embodied CO₂', unit: 't / lane-km', fmt: (x) => x.toFixed(1), title: 'Embodied CO₂ of the materials per km of a 3.5 m lane' },
  ].filter((m) => rows.some((r) => r[m.key] != null));
  return (
    <section className={cn('fp-tile overflow-hidden', className)} aria-labelledby="cmp-title">
      <div className="fp-tile-head">
        <h3 className="fp-tile-title" id="cmp-title"><GitCompare size={14} aria-hidden="true" />Trade-off</h3>
        <span className="text-[11.5px] text-[var(--text-muted)]">shortest bar wins · click to inspect</span>
      </div>
      <div className="fp-tile-body flex flex-col gap-4">
        {/* Legend: archetype, bituminous thickness, governing ratio */}
        <div className="flex flex-wrap gap-x-4 gap-y-1.5">
          {rows.map((r) => (
            <button key={r.i} type="button" onClick={onSelect ? () => onSelect(r.i) : undefined} aria-pressed={selected === r.i}
              className={cn('inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[12.5px] font-semibold border border-transparent',
                selected === r.i ? 'bg-[var(--surface-sunken)] border-[var(--hairline-strong)]' : 'hover:bg-[var(--surface-sunken)]')}
              title={`#${r.i + 1} ${r.label}: ${r.bit.toFixed(0)} mm bituminous; governing ratio ${(r.gov * 100).toFixed(0)}%`}>
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: r.color }} aria-hidden="true" />
              <span style={{ color: r.color }}>{r.label}</span>
              <Chip tone={ratioTone(r.gov)} className="h-[18px] px-1.5 text-[10.5px]"><span className="fp-num">{(r.gov * 100).toFixed(0)}%</span></Chip>
            </button>
          ))}
        </div>
        <div className={cn('grid gap-4', wide && 'md:grid-cols-3 md:gap-6')}>
        {metrics.map((m) => {
          const vals = rows.map((r) => r[m.key]).filter((x) => x != null);
          const max = Math.max(...vals) || 1;
          const min = Math.min(...vals);
          return (
            <div key={m.key} className="flex flex-col gap-1.5" title={m.title}>
              <div className="flex items-baseline justify-between">
                <span className="fp-kpi-label">{m.label}</span>
                <span className="text-[11.5px] text-[var(--text-muted)]">{m.unit}</span>
              </div>
              {rows.map((r) => (
                <div key={r.i} className="grid grid-cols-[minmax(0,1fr)_56px] items-center gap-2">
                  <div className="h-3.5 rounded-full bg-[var(--track)] overflow-hidden">
                    {r[m.key] != null && (
                      <span className="block h-full rounded-full fp-grow" style={{
                        width: `${Math.max(4, (r[m.key] / max) * 100)}%`, background: r.color,
                        opacity: selected == null || selected === r.i ? 1 : 0.45,
                      }} />
                    )}
                  </div>
                  <span className={cn('fp-num text-right text-[12.5px]', r[m.key] === min ? 'font-bold text-[var(--ok)]' : 'text-[var(--text-bold)]')}>
                    {r[m.key] != null ? m.fmt(r[m.key]) : '—'}
                  </span>
                </div>
              ))}
            </div>
          );
        })}
        </div>
      </div>
    </section>
  );
}
