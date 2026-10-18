// Fills the rest of the results row: a side-by-side comparison when the
// optimizer returned several archetypes, or what to switch on to get more.
import React from 'react';
import { GitCompare, Lightbulb } from 'lucide-react';
import { Chip, Toggle } from './primitives';
import { archetypeTone, ratioTone, cn } from './util';

const BIT = /\b(BC|DBM|BM|SDBC|SMA)\b/;
const govRatio = (det) => Math.max(det.CDF_fatigue || 0, det.CDF_rutting || 0, det.CDF_ctb || 0, det.long_life?.ratio || 0);

export default function DesignCompare({ designs, className, optimizeByCost, optimizeByCo2, setOptimizeByCost, setOptimizeByCo2, onRerun, busy }) {
  if (designs.length < 2) {
    const merged = (designs[0]?.details?.strategy || '').includes('+');
    const objectivesOn = optimizeByCost || optimizeByCo2;
    return (
      <section className={cn('fp-tile p-3 flex flex-col gap-2 self-start', className)} aria-label="More archetypes">
        <div className="flex items-center gap-1.5 text-[11px] font-bold text-[var(--text-bold)]">
          <Lightbulb size={13} className="text-[var(--accent)]" aria-hidden="true" />
          {merged ? 'Every objective chose the same section' : 'One archetype — the thinnest IRC-adequate section'}
        </div>
        {merged || objectivesOn ? (
          <p className="m-0 text-[10.5px] text-[var(--text-muted)] leading-snug max-w-[70ch]">
            The thinnest adequate design is also the cheapest and the lowest-carbon here, so the archetypes merge
            into one card. Real trade-offs appear when more than one layer may vary: set further layers to
            <b> Opt</b> with a min–max range (for example the granular base against the DBM) and optimize again.
          </p>
        ) : (
          <>
            <p className="m-0 text-[10.5px] text-[var(--text-muted)] leading-snug max-w-[70ch]">
              Turn on the cost and carbon objectives to add the Economy (lowest ₹ per lane-km), Sustainable
              (lowest embodied CO₂) and Premium (best combined) archetypes, then optimize again. Designs that win
              several objectives merge into one card.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <Toggle id="cmpCost" checked={optimizeByCost} onChange={setOptimizeByCost} label="Cost" />
              <Toggle id="cmpCo2" checked={optimizeByCo2} onChange={setOptimizeByCo2} label="Embodied CO₂" />
              <button type="button" className="fp-btn-grad h-[24px] px-2.5 rounded-md text-[10.5px] font-bold"
                disabled={busy || (!optimizeByCost && !optimizeByCo2)} onClick={onRerun}>Optimize again</button>
            </div>
          </>
        )}
      </section>
    );
  }
  const best = (f) => Math.min(...designs.map(f).filter((x) => Number.isFinite(x)));
  const rows = designs.map((d) => {
    const det = d.details || {};
    const bit = (det.layers || []).filter((l) => BIT.test(String(l.name).toUpperCase())).reduce((s, l) => s + Number(l.thickness || 0), 0);
    return { d, det, crust: Number(d.total_thickness), bit, gov: govRatio(det), cost: d.cost, co2: d.co2 };
  });
  const minCrust = best((r) => r.crust);
  const minCost = best((r) => (r.cost == null ? NaN : Number(r.cost)));
  const minCo2 = best((r) => (r.co2 == null ? NaN : Number(r.co2)));
  const lead = (on) => (on ? 'text-[var(--ok)] font-bold' : 'text-[var(--text-bold)]');
  return (
    <section className={cn('fp-tile overflow-hidden self-start', className)} aria-label="Archetype comparison">
      <div className="fp-tile-head">
        <h3 className="fp-tile-title"><GitCompare size={12} aria-hidden="true" />Comparison</h3>
        <span className="text-[9.5px] text-[var(--text-muted)]">best in green · per 3.5 m lane-km</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] border-collapse fp-num">
          <thead>
            <tr className="text-[10px] text-[var(--text-muted)] font-semibold text-right">
              <th className="text-left px-3 py-1.5 font-semibold">Archetype</th>
              <th className="px-1.5 py-1.5 font-semibold" title="Total crust thickness (mm)">Crust</th>
              <th className="px-1.5 py-1.5 font-semibold" title="Bituminous thickness (mm)">Bit.</th>
              <th className="px-1.5 py-1.5 font-semibold" title="Governing ratio: max of the CDFs and long-life strain ratios">Gov.</th>
              <th className="px-1.5 py-1.5 font-semibold" title="Material cost, ₹ lakh per lane-km">₹ lakh</th>
              <th className="px-3 py-1.5 font-semibold" title="Embodied CO₂, tonnes per lane-km">t CO₂</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const tone = archetypeTone(r.det.strategy);
              const label = (r.det.strategy || 'Design').replace(/\s*\+\s*Premium$/, ' = Premium');
              return (
                <tr key={i} className="border-t border-[var(--hairline)] text-right align-top">
                  <td className="text-left px-3 py-1.5 font-sans font-semibold leading-tight" style={{ color: tone.color }}>
                    <span className="text-[var(--text-muted)] mr-1">#{i + 1}</span>{label}
                  </td>
                  <td className={cn('px-1.5 py-1.5', lead(r.crust === minCrust))}>{r.crust.toFixed(0)}</td>
                  <td className="px-1.5 py-1.5 text-[var(--text-main)]">{r.bit.toFixed(0)}</td>
                  <td className="px-1.5 py-1.5"><Chip tone={ratioTone(r.gov)}>{(r.gov * 100).toFixed(0)}%</Chip></td>
                  <td className={cn('px-1.5 py-1.5', lead(r.cost != null && Number(r.cost) === minCost))}>{r.cost != null ? (Number(r.cost) / 1e5).toFixed(1) : '—'}</td>
                  <td className={cn('px-3 py-1.5', lead(r.co2 != null && Number(r.co2) === minCo2))}>{r.co2 != null ? (r.co2 / 1000).toFixed(1) : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
