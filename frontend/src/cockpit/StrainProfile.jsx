// Strain–depth profile: horizontal strain (tension +) and vertical strain
// (compression +) against depth, side by side on one depth axis, over the
// layer bands. The IRC allowable strains are drawn where they apply: εt at
// the bottom of the bituminous bundle, εv at the top of the subgrade; the
// long-life limits (80 / 200 µε, §10) when that check is on.
import React, { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';

const BIT = /\b(BC|DBM|BM|SDBC|SMA)\b/;
const ue = (x) => x * 1e6;
const fmt = (x) => (Math.abs(x) >= 100 ? x.toFixed(0) : x.toFixed(1));
const fmtTick = (x) => (Math.abs(x - Math.round(x)) < 1e-9 ? String(Math.round(x)) : x.toFixed(1));

function useWidth() {
  const ref = useRef(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    setW(el.clientWidth);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/* Round axis maximum: 1, 2, 2.5 or 5 × 10^k at or above x. */
function niceMax(x) {
  if (!(x > 0)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(x)));
  const m = x / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
}

export default function StrainProfile({ profile, bands, colorOf, allow, longLife, height = 300 }) {
  const [ref, W] = useWidth();
  const [hover, setHover] = useState(null);
  const data = profile?.data;

  const H = height;
  const gutter = W < 420 ? 64 : 84;
  const gap = 18;
  const top = 24;
  const bottomPad = 26;
  const pw = Math.max(60, (W - gutter - gap - 8) / 2);
  const x0a = gutter;
  const x0b = gutter + pw + gap;
  const zMax = bands?.length ? bands[bands.length - 1].bottom : 1;
  const y = (z) => top + (z / zMax) * (H - top - bottomPad);

  const bitBottom = bands?.filter((b) => BIT.test(String(b.name).toUpperCase())).reduce((m, b) => Math.max(m, b.bottom), 0) || null;
  const subTop = bands?.find((b) => b.subgrade)?.top ?? null;

  let content = null;
  if (data && data.length && W > 0) {
    const ehs = data.map((d) => ue(d.eh));
    const evs = data.map((d) => ue(d.ev));
    const aT = allow?.epsT != null ? ue(allow.epsT) : null;
    const aV = allow?.epsV != null ? ue(allow.epsV) : null;
    const hMin = Math.min(0, ...ehs);
    const hMax = niceMax(Math.max(...ehs, aT ?? 0, longLife ? 80 : 0) * 1.08);
    const hLo = hMin < 0 ? -niceMax(-hMin * 1.08) : 0;
    const vMax = niceMax(Math.max(...evs, aV ?? 0, longLife ? 200 : 0) * 1.08);
    const vLo = Math.min(0, ...evs) < 0 ? -niceMax(-Math.min(...evs) * 1.08) : 0;
    const xa = (v) => x0a + ((v - hLo) / (hMax - hLo)) * pw;
    const xb = (v) => x0b + ((v - vLo) / (vMax - vLo)) * pw;
    const path = (xs, xf) => data.map((d, i) => `${i ? 'L' : 'M'}${xf(xs[i]).toFixed(1)},${y(d.z).toFixed(1)}`).join(' ');

    // Critical-point markers.
    const near = (z0) => data.reduce((best, d, i) => (Math.abs(d.z - z0) < Math.abs(data[best].z - z0) ? i : best), 0);
    const iT = bitBottom ? near(bitBottom - 0.1) : null;
    const iV = subTop != null ? near(subTop + 0.1) : null;

    const onMove = (e) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const zy = ((e.clientY - rect.top - top) / (H - top - bottomPad)) * zMax;
      if (zy < 0 || zy > zMax) { setHover(null); return; }
      setHover(near(zy));
    };
    const hv = hover != null ? data[hover] : null;
    const ticks = (lo, hi) => [lo, lo + (hi - lo) / 2, hi];

    content = (
      <svg width={W} height={H} className="block select-none" onMouseMove={onMove} onMouseLeave={() => setHover(null)}
           role="img"
           aria-label={`Strain–depth profile. ${iT != null ? `Horizontal strain at the bottom of the bituminous layer ${fmt(ehs[iT])} µε${aT ? ` against ${fmt(aT)} allowable` : ''}. ` : ''}${iV != null ? `Vertical strain at the top of the subgrade ${fmt(evs[iV])} µε${aV ? ` against ${fmt(aV)} allowable` : ''}.` : ''}`}>
        {/* Layer bands and labels */}
        {bands.map((b, k) => {
          const y1 = y(b.top); const y2 = y(b.bottom);
          return (
            <g key={k}>
              <rect x={x0a} y={y1} width={pw * 2 + gap} height={Math.max(0, y2 - y1)} fill={colorOf(b, k)} opacity={0.09} />
              <line x1={gutter - 6} x2={x0b + pw} y1={y1} y2={y1} stroke="var(--hairline-strong)" strokeWidth={1} />
              <rect x={6} y={y1 + 1} width={4} height={Math.max(0, y2 - y1 - 2)} rx={2} fill={colorOf(b, k)} className="fp-ink" />
              {y2 - y1 >= 11 && (
                <text x={15} y={(y1 + y2) / 2 + 4} fontSize={y2 - y1 >= 15 ? 11.5 : 10.5} fill="var(--text-main)" className="fp-num" fontWeight={600}>
                  {b.name}
                  {!b.subgrade && <tspan fill="var(--text-muted)" fontWeight={400}>{` ${Math.round(b.bottom - b.top)}`}</tspan>}
                </text>
              )}
            </g>
          );
        })}
        {/* Panel frames, titles, axes */}
        {[[x0a, 'Horizontal εh', 'tension +', hLo, hMax], [x0b, 'Vertical εv', 'compression +', vLo, vMax]].map(([x0, t, s, lo, hi]) => (
          <g key={t}>
            <text x={x0} y={14} fontSize={11.5} fontWeight={700} fill="var(--text-bold)">{t}<tspan fontWeight={400} fill="var(--text-muted)">{`  µε · ${s}`}</tspan></text>
            <rect x={x0} y={top} width={pw} height={H - top - bottomPad} fill="none" stroke="var(--hairline)" />
            {ticks(lo, hi).map((v, i) => {
              const xx = x0 + ((v - lo) / (hi - lo)) * pw;
              return (
                <g key={i}>
                  <line x1={xx} x2={xx} y1={top} y2={H - bottomPad} stroke="var(--hairline)" strokeDasharray={i === 0 || i === 2 ? undefined : '2 3'} />
                  <text x={xx} y={H - bottomPad + 15} fontSize={10.5} textAnchor={i === 0 ? 'start' : i === 2 ? 'end' : 'middle'} fill="var(--text-muted)" className="fp-num">{fmtTick(v)}</text>
                </g>
              );
            })}
          </g>
        ))}
        {hLo < 0 && <line x1={xa(0)} x2={xa(0)} y1={top} y2={H - bottomPad} stroke="var(--text-muted)" strokeWidth={1} opacity={0.6} />}
        {/* Allowable strains where they apply */}
        {aT != null && bitBottom && (
          <g>
            <line x1={xa(aT)} x2={xa(aT)} y1={top} y2={y(bitBottom)} stroke="var(--accent)" strokeWidth={1.5} strokeDasharray="5 4" />
            <text x={xa(aT) - 4} y={top + 12} fontSize={10.5} textAnchor="end" fill="var(--accent)" className="fp-num">allow {fmt(aT)}</text>
          </g>
        )}
        {aV != null && subTop != null && (
          <g>
            <line x1={xb(aV)} x2={xb(aV)} y1={y(subTop)} y2={H - bottomPad} stroke="var(--info)" strokeWidth={1.5} strokeDasharray="5 4" />
            <text x={xb(aV) - 4} y={H - bottomPad - 6} fontSize={10.5} textAnchor="end" fill="var(--info)" className="fp-num">allow {fmt(aV)}</text>
          </g>
        )}
        {longLife && bitBottom && (
          <line x1={xa(80)} x2={xa(80)} y1={top} y2={y(bitBottom)} stroke="var(--ok)" strokeWidth={1.25} strokeDasharray="1 3" strokeLinecap="round" />
        )}
        {longLife && subTop != null && (
          <line x1={xb(200)} x2={xb(200)} y1={y(subTop)} y2={H - bottomPad} stroke="var(--ok)" strokeWidth={1.25} strokeDasharray="1 3" strokeLinecap="round" />
        )}
        {/* Profiles */}
        <path d={path(ehs, xa)} fill="none" stroke="var(--accent)" strokeWidth={2.25} strokeLinejoin="round" />
        <path d={path(evs, xb)} fill="none" stroke="var(--info)" strokeWidth={2.25} strokeLinejoin="round" />
        {iT != null && (
          <g>
            <circle cx={xa(ehs[iT])} cy={y(data[iT].z)} r={4.5} fill="var(--surface-panel)" stroke="var(--accent)" strokeWidth={2} />
            <text x={xa(ehs[iT]) + 8} y={y(data[iT].z) - 6} fontSize={11.5} fontWeight={700} fill="var(--accent)" className="fp-num">{fmt(ehs[iT])}</text>
          </g>
        )}
        {iV != null && (
          <g>
            <circle cx={xb(evs[iV])} cy={y(data[iV].z)} r={4.5} fill="var(--surface-panel)" stroke="var(--info)" strokeWidth={2} />
            <text x={xb(evs[iV]) + 8} y={y(data[iV].z) + 15} fontSize={11.5} fontWeight={700} fill="var(--info)" className="fp-num">{fmt(evs[iV])}</text>
          </g>
        )}
        {/* Hover read-out */}
        {hv && (
          <g pointerEvents="none">
            <line x1={x0a} x2={x0b + pw} y1={y(hv.z)} y2={y(hv.z)} stroke="var(--text-bold)" strokeWidth={1} opacity={0.5} />
            <circle cx={xa(ue(hv.eh))} cy={y(hv.z)} r={3} fill="var(--accent)" />
            <circle cx={xb(ue(hv.ev))} cy={y(hv.z)} r={3} fill="var(--info)" />
            <g transform={`translate(${Math.min(x0b + pw - 180, Math.max(x0a, xa(ue(hv.eh)) + 10))}, ${Math.max(top + 4, Math.min(H - bottomPad - 26, y(hv.z) - 30))})`}>
              <rect width={180} height={22} rx={6} fill="var(--surface-panel)" stroke="var(--hairline-strong)" />
              <text x={8} y={15} fontSize={11} fill="var(--text-bold)" className="fp-num">
                {`z ${fmt(hv.z)} mm · εh ${fmt(ue(hv.eh))} · εv ${fmt(ue(hv.ev))}`}
              </text>
            </g>
          </g>
        )}
      </svg>
    );
  }

  return (
    <div ref={ref} className="relative w-full min-w-0" style={{ minHeight: H }}>
      {content}
      {(!data || !data.length) && (
        <div className="absolute inset-0 flex items-center justify-center text-[13px] text-[var(--text-muted)] text-center px-6">
          {profile?.loading ? (
            <span className="inline-flex items-center gap-2"><Loader2 size={15} className="animate-spin text-[var(--accent)]" aria-hidden="true" /> Solving the profile at {profile.points || 'about 60'} stations…</span>
          ) : profile?.error ? (
            <span className="text-[var(--fail)]">Profile not available: {profile.error}</span>
          ) : (
            <span>Evaluate the section, or optimize and pick a design, to see strain against depth.</span>
          )}
        </div>
      )}
      {data && profile?.loading && (
        <span className="absolute top-0 right-0 inline-flex items-center gap-1 text-[11px] text-[var(--text-muted)]">
          <Loader2 size={12} className="animate-spin" aria-hidden="true" /> updating
        </span>
      )}
    </div>
  );
}
