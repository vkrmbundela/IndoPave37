// One optimizer archetype as a bento card: section strip, layer table, IRC
// utilization bars (CDF and long-life strain ratios), critical strains against
// their allowable values, cost and carbon.
import React from 'react';
import { Layers, AlertTriangle, CornerDownLeft, Eye } from 'lucide-react';
import { Chip, UtilBar, RingGauge } from './primitives';
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

export default function DesignCard({ d, index, colorOf, airVoids, bitumenVolume, style, onApply, selected, onSelect, className }) {
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
    <article className={cn('fp-tile fp-fade-up overflow-hidden', onSelect && 'cursor-pointer', className)} style={style} aria-label={`${strategy} design`}
             data-selected={selected ? 'true' : undefined}
             onClick={onSelect ? (e) => { if (!e.target.closest('button, a, input, select, textarea')) onSelect(index); } : undefined}>
      {/* Header: archetype, total thickness, governing ratio */}
      <div className="flex items-start justify-between gap-3 px-4 pt-4 pb-3 border-b border-[var(--hairline)]">
        <div className="min-w-0 flex flex-col gap-1">
          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] font-bold text-[var(--text-muted)] fp-num">#{index + 1}</span>
            <h3 className="m-0 text-[14px] font-bold leading-tight" style={{ color: tone.color }}>{strategy}</h3>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="fp-num text-[34px] leading-none font-semibold text-[var(--text-bold)] tracking-tight">{Number(d.total_thickness).toFixed(0)}</span>
            <span className="text-[12.5px] text-[var(--text-muted)]">mm crust</span>
          </div>
          <div className="flex flex-wrap items-center gap-1 mt-1">
            <Chip tone="ok" title="All applicable IRC:37-2018 criteria are within their limits (CDF ≤ 1)">IRC-adequate</Chip>
            <Chip tone={det.governing_mode === 'long_life' ? 'info' : 'muted'}
                  title={det.governing_mode === 'long_life' && ll ? `Long-life endurance limit (${ll.governing}) is the binding check` : 'The criterion with the highest damage ratio'}>
              {MODE_LABEL[det.governing_mode] || 'Governs: —'}
            </Chip>
          </div>
        </div>
        <RingGauge ratio={govRatio} size={72} stroke={8} className="flex-none"
          title="Governing demand/capacity ratio: max of the CDFs and long-life strain ratios" />
      </div>
      <div className="flex items-center gap-1.5 px-4 pt-3">
        {onSelect && (
          <button type="button" onClick={() => onSelect(index)} aria-pressed={!!selected}
            className="fp-tbtn h-[28px] px-2.5 text-[12px]"
            title="Show this design in the verdict, strain profile and crust tiles">
            <Eye size={13} aria-hidden="true" /> {selected ? 'Inspecting' : 'Inspect'}
          </button>
        )}
        {onApply && (
          <button type="button" onClick={() => onApply(d)}
            className="fp-tbtn h-[28px] px-2.5 text-[12px]"
            title="Copy these thicknesses into the layer list (as fixed layers) to evaluate or analyse them">
            <CornerDownLeft size={13} aria-hidden="true" /> Use
          </button>
        )}
      </div>

      <div className="px-4 pt-3 pb-4 flex flex-col gap-3 flex-1">
        {/* Section strip: thickness-proportional layer bands */}
        <div className="flex h-7 rounded-md overflow-hidden border border-[var(--hairline)]" aria-hidden="true">
          {structural.map((l, j) => (
            <div key={j} className="h-full flex items-center justify-center text-[10.5px] font-bold text-[#fff] overflow-hidden border-r border-[var(--hairline-strong)] last:border-r-0"
                 style={{ width: `${(Number(l.thickness) / total) * 100}%`, background: colorOf(l, j) }}
                 title={`${l.name} ${Number(l.thickness).toFixed(0)} mm`}>
              {Number(l.thickness) / total > 0.12 ? l.name : ''}
            </div>
          ))}
        </div>

        {/* Layers */}
        <table className="w-full text-[12.5px] border-collapse">
          <thead>
            <tr className="text-[11px] text-[var(--text-muted)]">
              <th className="text-left font-semibold py-0.5">Layer</th>
              <th className="text-right font-semibold py-0.5">h (mm)</th>
              <th className="text-right font-semibold py-0.5">E (MPa)</th>
            </tr>
          </thead>
          <tbody>
            {layers.map((l, j) => (
              <tr key={j} className="border-t border-[var(--hairline)]">
                <td className="py-1 text-[var(--text-main)] font-medium">
                  <span className="inline-block w-2 h-2 rounded-sm mr-1.5 align-middle border border-[var(--hairline-strong)]" style={{ background: Number(l.thickness) > 0 ? colorOf(l, j) : '#7c6552' }} />
                  {l.name}
                </td>
                <td className="py-1 text-right fp-num font-semibold text-[var(--text-bold)]">{Number(l.thickness) > 0 ? Number(l.thickness).toFixed(0) : '∞'}</td>
                <td className="py-1 text-right fp-num text-[var(--text-muted)]">{Number(l.modulus).toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* IRC utilization */}
        <div className="flex flex-col gap-2.5 rounded-[var(--radius-control)] bg-[var(--surface-sunken)] border border-[var(--hairline)] p-3">
          {compressive ? (
            <div className="flex items-center justify-between text-[12px]">
              <span className="fp-kpi-label">Fatigue (Eq. 3.{rel === 90 ? 4 : 3})</span>
              <Chip tone="info" title="Every horizontal strain at the bottom of the bituminous layer is compressive: fatigue need not be checked (IRC:37-2018 Annex III).">Not checked · compressive</Chip>
            </div>
          ) : (
            <UtilBar label={`Fatigue CDF (Eq. 3.${rel === 90 ? 4 : 3})`} ratio={det.CDF_fatigue} display={pct(det.CDF_fatigue)}
                     note={`εt ${ue(det.eps_t)} µε · allowable ${ue(allow.epsT)} µε`}
                     title="Cumulative fatigue damage = design traffic / allowable repetitions Nf at the bottom of the bituminous layer (IRC:37-2018 §3.6.2)." />
          )}
          <UtilBar label={`Rutting CDF (Eq. 3.${rel === 90 ? 2 : 1})`} ratio={det.CDF_rutting} display={pct(det.CDF_rutting)}
                   note={`εv ${ue(det.eps_v)} µε · allowable ${ue(allow.epsV)} µε`}
                   title="Cumulative rutting damage = design traffic / allowable repetitions NR at the top of the subgrade (IRC:37-2018 §3.6.1)." />
          {det.CDF_ctb != null && (
            <UtilBar label="CTB fatigue (Eq. 3.5/3.6)" ratio={det.CDF_ctb} display={pct(det.CDF_ctb)}
                     note={det.CDF_ctb_strain != null && det.ctb_details?.CDF_ctb != null
                       ? `Eq. 3.5 ${Number(det.CDF_ctb_strain).toFixed(3)} · spectrum Eq. 3.6 ${Number(det.ctb_details.CDF_ctb).toFixed(3)}`
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
          <div className="flex gap-1.5 text-[12px] text-[var(--warn)]">
            <AlertTriangle size={12} className="flex-none mt-px" aria-hidden="true" />
            Geogrid gives no structural benefit here (IRC:SP:59 §3.1.3) — compare without it.
          </div>
        )}
        {Array.isArray(det.non_monotonic_neighbours) && det.non_monotonic_neighbours.length > 0 && (
          <div className="flex gap-1.5 text-[12px] text-[var(--warn)]"
               title="Layered-elastic responses are not always monotone in thickness. A design one constructable lift THINNER in the listed layer(s) also passes IRC with a lower governing CDF — review it before tendering the thicker section.">
            <AlertTriangle size={12} className="flex-none mt-px" aria-hidden="true" />
            <span>Non-monotonic: {det.non_monotonic_neighbours.map((n) => `${n.layer_name} −${n.thickness_drop_mm} mm ⇒ CDF ${n.neighbour_cdf}`).join('; ')}</span>
          </div>
        )}
      </div>

      {/* Footer: traffic basis, reserve, cost, carbon */}
      <dl className="m-0 flex flex-col gap-1 px-4 py-3 border-t border-[var(--hairline)] bg-[var(--tile-head)] text-[12.5px]">
        <div className="flex items-baseline justify-between gap-2">
          <dt className="flex items-center gap-1 text-[var(--text-muted)]"><Layers size={12} aria-hidden="true" />Basis</dt>
          <dd className="m-0 fp-num text-right text-[var(--text-bold)] font-semibold truncate">
            {det.msa != null ? det.msa.toFixed(1) : '—'} msa · {det.reliability || '—'}
            {reserve != null && (
              <span className={cn('ml-1.5 font-medium', `text-[var(--${ratioTone(govRatio)})]`)}
                    title="Structural reserve on the governing criterion: 1 / max(CDF, strain ratio) − 1">
                · {(reserve * 100).toFixed(0)}% reserve
              </span>
            )}
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-2" title="Materials only, per km of a 3.5 m lane">
          <dt className="text-[var(--text-muted)]">Cost</dt>
          <dd className="m-0 fp-num text-[var(--text-bold)] font-semibold">{d.cost != null ? formatRupees(d.cost) : <span className="font-normal text-[var(--text-muted)]">enable the Cost objective</span>}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-2" title="Embodied CO₂ of the materials, per km of a 3.5 m lane">
          <dt className="text-[var(--text-muted)]">Embodied CO₂</dt>
          <dd className="m-0 fp-num text-[var(--text-bold)] font-semibold">{d.co2 != null ? `${(d.co2 / 1000).toFixed(1)} t/km` : <span className="font-normal text-[var(--text-muted)]">enable the CO₂ objective</span>}</dd>
        </div>
      </dl>
    </article>
  );
}
