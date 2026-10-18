// One optimizer archetype as a bento card: section strip, layer table, IRC
// utilization bars (CDF and long-life strain ratios), critical strains against
// their allowable values, cost and carbon.
import React from 'react';
import { Layers, AlertTriangle, CornerDownLeft } from 'lucide-react';
import { Chip, UtilBar } from './primitives';
import { cn, ratioTone, archetypeTone, formatRupees } from './util';
import { allowableStrains } from '../lib/irc';

const BIT = /\b(BC|DBM|BM|SDBC|SMA)\b/;


const MODE_LABEL = {
  fatigue: 'Fatigue governs',
  rutting: 'Rutting governs',
  ctb: 'CTB fatigue governs',
  long_life: 'Long-life limit governs',
};


const pct = (x) => (x == null || !Number.isFinite(Number(x)) ? '—' : `${(Number(x) * 100).toFixed(1)}%`);
const ue = (x) => (x == null || !Number.isFinite(Number(x)) ? '—' : (Math.abs(Number(x)) * 1e6).toFixed(1));

export default function DesignCard({ d, index, colorOf, airVoids, bitumenVolume, style, onApply }) {
  const det = d.details || {};
  const strategy = (det.strategy || 'Design').replace(/\s*\+\s*Premium$/, ' = Premium');
  const tone = archetypeTone(det.strategy);
  const layers = det.layers || [];
  const structural = layers.filter((l) => Number(l.thickness) > 0);
  const total = structural.reduce((s, l) => s + Number(l.thickness), 0) || 1;
  const bottomBit = [...layers].reverse().find((l) => BIT.test(String(l.name).toUpperCase()));
  const rel = String(det.reliability || '').includes('80') ? 80 : 90;
  const allow = allowableStrains({
    msa: det.msa, reliability: rel, mrm: bottomBit?.modulus, airVoids, bitumenVolume,
  });
  const ll = det.long_life;
  const compressive = det.fatigue_compressive || (det.eps_t != null && det.eps_t < 0);
  const govRatio = Math.max(
    det.CDF_fatigue || 0, det.CDF_rutting || 0, det.CDF_ctb || 0, ll?.ratio || 0,
  );
  const reserve = govRatio > 0 ? (1 / govRatio - 1) : null;

  return (
    <article className="fp-tile fp-fade-up overflow-hidden" style={style} aria-label={`${strategy} design`}>
      {/* Header: archetype, total thickness, verdict */}
      <div className="flex items-center justify-between gap-2 px-3 pt-2.5 pb-2 border-b border-[var(--hairline)]"
           style={{ boxShadow: `inset 3px 0 0 ${tone.color}` }}>
        <div className="min-w-0">
          <div className="flex items-baseline gap-1.5">
            <span className="text-[9.5px] font-bold text-[var(--text-muted)] fp-num">#{index + 1}</span>
            <h3 className="m-0 text-[12px] font-bold leading-tight" style={{ color: tone.color }}>{strategy}</h3>
          </div>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="fp-num text-[22px] leading-none font-semibold text-[var(--text-bold)]">{Number(d.total_thickness).toFixed(0)}</span>
            <span className="text-[10px] text-[var(--text-muted)]">mm crust</span>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex items-center gap-1">
            {onApply && (
              <button type="button" onClick={() => onApply(d)}
                className="fp-tbtn h-[20px] px-1.5 text-[10px]"
                title="Copy these thicknesses into the layer table (as fixed layers) to evaluate or analyse them">
                <CornerDownLeft size={11} aria-hidden="true" /> Use
              </button>
            )}
            <Chip tone="ok" title="All applicable IRC:37-2018 criteria are within their limits (CDF ≤ 1)">IRC pass</Chip>
          </div>
          <Chip tone={det.governing_mode === 'long_life' ? 'info' : 'muted'}
                title={det.governing_mode === 'long_life' && ll ? `Long-life endurance limit (${ll.governing}) is the binding check` : 'The criterion with the highest damage ratio'}>
            {MODE_LABEL[det.governing_mode] || 'Governs: —'}
          </Chip>
        </div>
      </div>

      <div className="p-3 flex flex-col gap-2.5 flex-1">
        {/* Section strip: thickness-proportional layer bands */}
        <div className="flex h-5 rounded overflow-hidden border border-[var(--hairline)]" aria-hidden="true">
          {structural.map((l, j) => (
            <div key={j} className="h-full flex items-center justify-center text-[8.5px] font-bold text-[#fff] overflow-hidden border-r border-[var(--hairline-strong)] last:border-r-0"
                 style={{ width: `${(Number(l.thickness) / total) * 100}%`, background: colorOf(l, j) }}
                 title={`${l.name} ${Number(l.thickness).toFixed(0)} mm`}>
              {Number(l.thickness) / total > 0.12 ? l.name : ''}
            </div>
          ))}
        </div>

        {/* Layers */}
        <table className="w-full text-[10.5px] border-collapse">
          <thead>
            <tr className="text-[9.5px] text-[var(--text-muted)]">
              <th className="text-left font-semibold py-0.5">Layer</th>
              <th className="text-right font-semibold py-0.5">h (mm)</th>
              <th className="text-right font-semibold py-0.5">E (MPa)</th>
            </tr>
          </thead>
          <tbody>
            {layers.map((l, j) => (
              <tr key={j} className="border-t border-[var(--hairline)]">
                <td className="py-0.5 text-[var(--text-main)] font-medium">
                  <span className="inline-block w-2 h-2 rounded-sm mr-1.5 align-middle border border-[var(--hairline-strong)]" style={{ background: Number(l.thickness) > 0 ? colorOf(l, j) : '#7c6552' }} />
                  {l.name}
                </td>
                <td className="py-0.5 text-right fp-num font-semibold text-[var(--text-bold)]">{Number(l.thickness) > 0 ? Number(l.thickness).toFixed(0) : '∞'}</td>
                <td className="py-0.5 text-right fp-num text-[var(--text-muted)]">{Number(l.modulus).toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* IRC utilization */}
        <div className="flex flex-col gap-1.5 rounded-md bg-[var(--surface-sunken)] border border-[var(--hairline)] p-2">
          {compressive ? (
            <div className="flex items-center justify-between text-[10px]">
              <span className="font-semibold text-[var(--text-muted)] uppercase tracking-wide text-[9.5px]">Fatigue (Eq 3.4)</span>
              <Chip tone="info" title="Every horizontal strain at the bottom of the bituminous layer is compressive: fatigue need not be checked (IRC:37-2018 Annex III).">Not checked · compressive</Chip>
            </div>
          ) : (
            <UtilBar label="Fatigue CDF (Eq 3.4)" ratio={det.CDF_fatigue} display={pct(det.CDF_fatigue)}
                     note={`εt ${ue(det.eps_t)} µε · allowable ${ue(allow.epsT)} µε`}
                     title="Cumulative fatigue damage = design traffic / allowable repetitions Nf at the bottom of the bituminous layer (IRC:37-2018 §3.6.2)." />
          )}
          <UtilBar label="Rutting CDF (Eq 3.2)" ratio={det.CDF_rutting} display={pct(det.CDF_rutting)}
                   note={`εv ${ue(det.eps_v)} µε · allowable ${ue(allow.epsV)} µε`}
                   title="Cumulative rutting damage = design traffic / allowable repetitions NR at the top of the subgrade (IRC:37-2018 §3.6.1)." />
          {det.CDF_ctb != null && (
            <UtilBar label="CTB fatigue (Eq 3.5/3.6)" ratio={det.CDF_ctb} display={pct(det.CDF_ctb)}
                     note={det.CDF_ctb_strain != null && det.ctb_details?.CDF_ctb != null
                       ? `Eq 3.5 ${Number(det.CDF_ctb_strain).toFixed(3)} · spectrum Eq 3.6 ${Number(det.ctb_details.CDF_ctb).toFixed(3)}`
                       : `εt,CTB ${ue(det.eps_t_ctb)} µε · σt ${det.sigma_t_ctb != null ? Math.abs(det.sigma_t_ctb).toFixed(3) : '—'} MPa`}
                     title="Governing CTB fatigue damage: strain criterion Eq. 3.5 and, with an axle spectrum, the stress-ratio CFD Eq. 3.6 — the worse governs." />
          )}
          {ll && (
            <>
              {!compressive && (
                <UtilBar label={<>Long-life <span className="normal-case">εt / 80 µε</span> (§10)</>} ariaLabel="Long-life tensile strain ratio" ratio={ll.ratio_t} display={`${ue(det.eps_t)} µε`}
                         title="IRC:37-2018 §10 endurance limit for the bituminous tensile strain (35 °C)." />
              )}
              <UtilBar label={<>Long-life <span className="normal-case">εv / 200 µε</span> (§10)</>} ariaLabel="Long-life vertical strain ratio" ratio={ll.ratio_v} display={`${ue(det.eps_v)} µε`}
                       title="IRC:37-2018 §10 limit for the vertical strain at the top of the subgrade." />
            </>
          )}
        </div>

        {det.geogrid_credit === 'no benefit' && (
          <div className="flex gap-1.5 text-[10px] text-[var(--warn)]">
            <AlertTriangle size={12} className="flex-none mt-px" aria-hidden="true" />
            Geogrid gives no structural benefit here (IRC:SP:59 §3.1.3) — compare without it.
          </div>
        )}
        {Array.isArray(det.non_monotonic_neighbours) && det.non_monotonic_neighbours.length > 0 && (
          <div className="flex gap-1.5 text-[10px] text-[var(--warn)]"
               title="Layered-elastic responses are not always monotone in thickness. A design one constructable lift THINNER in the listed layer(s) also passes IRC with a lower governing CDF — review it before tendering the thicker section.">
            <AlertTriangle size={12} className="flex-none mt-px" aria-hidden="true" />
            <span>Non-monotonic: {det.non_monotonic_neighbours.map((n) => `${n.layer_name} −${n.thickness_drop_mm} mm ⇒ CDF ${n.neighbour_cdf}`).join('; ')}</span>
          </div>
        )}
      </div>

      {/* Footer: traffic basis, reserve, cost, carbon */}
      <div className="grid grid-cols-3 gap-2 px-3 py-2 border-t border-[var(--hairline)] bg-[var(--tile-head)]">
        <div className="fp-kpi">
          <span className="fp-kpi-label flex items-center gap-1"><Layers size={10} aria-hidden="true" />Basis</span>
          <span className="fp-num text-[11px] font-semibold text-[var(--text-bold)]">{det.msa != null ? det.msa.toFixed(1) : '—'} msa · {det.reliability || '—'}</span>
          <span className={cn('fp-kpi-sub', reserve != null && `text-[var(--${ratioTone(govRatio)})]`)}
                title="Structural reserve on the governing criterion: 1 / max(CDF, strain ratio) − 1">
            {reserve != null ? `${(reserve * 100).toFixed(0)}% reserve` : ''}
          </span>
        </div>
        <div className="fp-kpi">
          <span className="fp-kpi-label">Cost</span>
          <span className="fp-num text-[11px] font-semibold text-[var(--text-bold)]">{d.cost != null ? formatRupees(d.cost) : '—'}</span>
          <span className="fp-kpi-sub">{d.cost != null ? 'materials · 3.5 m lane' : 'enable Cost objective'}</span>
        </div>
        <div className="fp-kpi">
          <span className="fp-kpi-label">Embodied CO₂</span>
          <span className="fp-num text-[11px] font-semibold text-[var(--text-bold)]">{d.co2 != null ? `${(d.co2 / 1000).toFixed(1)} t/km` : '—'}</span>
          <span className="fp-kpi-sub">{d.co2 != null ? 'materials · 3.5 m lane' : 'enable CO₂ objective'}</span>
        </div>
      </div>
    </article>
  );
}
