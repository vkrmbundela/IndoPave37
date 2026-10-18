// IRC:37-2018 design helpers in irc.js, checked against the printed values
// of the guideline (Table 9.2, Table 4.2, §4.3.1, §4.5.1, Annex II.6).
//
// Run: npm test

import { describe, it, expect } from 'vitest';
import {
  table92Modulus, allowableStrains, indicativeVdf, CARRIAGEWAYS,
  recommendedDesignPeriod, longLifeRecommended, applyBundleModulus,
  LONG_LIFE_EPS_T, LONG_LIFE_EPS_V,
} from './irc';

describe('table92Modulus (IRC:37-2018 Table 9.2)', () => {
  it('returns the tabulated values', () => {
    expect(table92Modulus('VG30', 35)).toBe(2000);
    expect(table92Modulus('VG40', 35)).toBe(3000);
    expect(table92Modulus('VG40', 20)).toBe(6000);
    expect(table92Modulus('VG10', 40)).toBe(800);
    expect(table92Modulus('VG30', 25)).toBe(3000);
  });
  it('interpolates linearly between temperatures, as get_bituminous_modulus', () => {
    expect(table92Modulus('VG40', 32.5)).toBeCloseTo(3500, 9);
    expect(table92Modulus('VG30', 37)).toBeCloseTo(2000 + 0.4 * (1250 - 2000), 9);
  });
  it('holds the end values outside 20-40 °C', () => {
    expect(table92Modulus('VG30', 15)).toBe(3500);
    expect(table92Modulus('VG30', 45)).toBe(1250);
  });
  it('gives BM its fixed 35 °C value at any temperature', () => {
    expect(table92Modulus('VG30', 25, 'BM')).toBe(700);
    expect(table92Modulus('VG10', 40, 'BM')).toBe(500);
  });
});

describe('allowableStrains (IRC:37-2018 Eq. 3.1-3.4)', () => {
  it('reproduces the Annex II.6 conventional design: 145 / 292 µε at 150 msa', () => {
    const { epsT, epsV } = allowableStrains({ msa: 150, reliability: 90, mrm: 3000, airVoids: 3, bitumenVolume: 11.5 });
    expect(Math.round(epsT * 1e6)).toBe(145);
    expect(Math.round(epsV * 1e6)).toBe(292);
  });
  it('inverts the fatigue and rutting equations exactly', () => {
    const msa = 50; const mrm = 2000; const va = 3.5; const vb = 11;
    for (const rel of [80, 90]) {
      const { epsT, epsV } = allowableStrains({ msa, reliability: rel, mrm, airVoids: va, bitumenVolume: vb });
      const kf = rel === 90 ? 0.5161e-4 : 1.6064e-4;
      const kr = rel === 90 ? 1.41e-8 : 4.1656e-8;
      const C = 10 ** (4.84 * (vb / (va + vb) - 0.69));
      expect(kf * C * (1 / epsT) ** 3.89 * (1 / mrm) ** 0.854).toBeCloseTo(msa * 1e6, -2);
      expect(kr * (1 / epsV) ** 4.5337).toBeCloseTo(msa * 1e6, -2);
    }
  });
  it('R90 allows less strain than R80', () => {
    const a = allowableStrains({ msa: 30, reliability: 80, mrm: 2000 });
    const b = allowableStrains({ msa: 30, reliability: 90, mrm: 2000 });
    expect(b.epsT).toBeLessThan(a.epsT);
    expect(b.epsV).toBeLessThan(a.epsV);
  });
  it('returns nulls without traffic', () => {
    expect(allowableStrains({ msa: 0, mrm: 2000 })).toEqual({ epsT: null, epsV: null });
  });
});

describe('long-life pavements (IRC:37-2018 §10 / §4.3.1)', () => {
  it('uses the 80 / 200 µε endurance limits', () => {
    expect(LONG_LIFE_EPS_T).toBe(80e-6);
    expect(LONG_LIFE_EPS_V).toBe(200e-6);
  });
  it('is recommended from 300 msa and for expressways', () => {
    expect(longLifeRecommended(299, 'nh')).toBe(false);
    expect(longLifeRecommended(300, 'nh')).toBe(true);
    expect(longLifeRecommended(10, 'expressway')).toBe(true);
  });
  it('recommends the §4.3.1 design period', () => {
    expect(recommendedDesignPeriod('nh', 50)).toBe(20);
    expect(recommendedDesignPeriod('urban', 50)).toBe(20);
    expect(recommendedDesignPeriod('other', 5)).toBe(15);
    expect(recommendedDesignPeriod('sh', 400)).toBe(30);
  });
});

describe('IRC:37-2018 §4.5.1 lane distribution and Table 4.2 VDF', () => {
  it('lists the §4.5.1 factors', () => {
    const f = Object.fromEntries(CARRIAGEWAYS.map(c => [c.id, c.ldf]));
    expect(f).toEqual({ single: 1, intermediate: 0.75, two_lane: 0.5, four_single: 0.4,
                        dual_2: 0.75, dual_3: 0.6, dual_4: 0.45 });
    expect(CARRIAGEWAYS.filter(c => c.directional).map(c => c.id)).toEqual(['dual_2', 'dual_3', 'dual_4']);
  });
  it('returns the Table 4.2 indicative VDF by band and terrain', () => {
    expect(indicativeVdf(150, 'plain')).toBe(1.7);
    expect(indicativeVdf(151, 'plain')).toBe(3.9);
    expect(indicativeVdf(1500, 'plain')).toBe(3.9);
    expect(indicativeVdf(1501, 'plain')).toBe(5.0);
    expect(indicativeVdf(100, 'hilly')).toBe(0.6);
    expect(indicativeVdf(800, 'hilly')).toBe(1.7);
    expect(indicativeVdf(4000, 'hilly')).toBe(2.8);
  });
});

describe('applyBundleModulus (IRC:37-2018 §9.2)', () => {
  const stack = [
    { type: 'SMA', E: 1600, nu: 0.35 },
    { type: 'DBM', E: 3000, nu: 0.35 },
    { type: 'WBM', E: 250, nu: 0.35 },
    { type: '', E: 60, nu: 0.35 },
  ];
  it('analyses every bituminous layer with the bottom-mix modulus', () => {
    const out = applyBundleModulus(stack, 4);
    expect(out.map(l => l.E)).toEqual([3000, 3000, 250, 60]);
  });
  it('returns the same array when nothing changes', () => {
    const same = [{ type: 'BC', E: 3000, nu: 0.35 }, { type: 'DBM', E: 3000, nu: 0.35 }, { E: 60, nu: 0.35 }];
    expect(applyBundleModulus(same, 3)).toBe(same);
  });
  it('does not take WBM for a bituminous layer', () => {
    const s = [{ type: 'BC', E: 2000, nu: 0.35 }, { type: 'WBM', E: 250, nu: 0.35 }, { E: 60, nu: 0.35 }];
    expect(applyBundleModulus(s, 3)).toBe(s);
  });
});

import { ircCriticalPoints, classifyPointRoles } from './irc';

describe('ircCriticalPoints', () => {
  const stack = [
    { type: 'BC', fixed_h: 40, is_fixed: true },
    { type: 'DBM', min_h: 50, max_h: 250, is_fixed: false },
    { type: 'WMM', fixed_h: 250, is_fixed: true },
    { type: 'GSB', fixed_h: 250, is_fixed: true },
    { type: '', fixed_h: 0, is_fixed: true },
  ];
  it('places fatigue and rutting probes at the Evaluate interfaces (dual wheel)', () => {
    expect(ircCriticalPoints(stack, 5, 'Dual', 310)).toEqual([
      { z: 89.9, r: 0 }, { z: 89.9, r: 155 }, { z: 590.1, r: 0 }, { z: 590.1, r: 155 },
    ]);
  });
  it('uses r = 0 only for a single wheel and adds the CTB bottom', () => {
    const ctb = [
      { type: 'BC', fixed_h: 40, is_fixed: true }, { type: 'DBM', fixed_h: 100, is_fixed: true },
      { type: 'CRL', fixed_h: 100, is_fixed: true }, { type: 'CTB', fixed_h: 150, is_fixed: true },
      { type: '', fixed_h: 0, is_fixed: true },
    ];
    expect(ircCriticalPoints(ctb, 5, 'Single')).toEqual([{ z: 139.9, r: 0 }, { z: 389.9, r: 0 }, { z: 390.1, r: 0 }]);
  });
  it('produces points that classifyPointRoles accepts', () => {
    const pts = ircCriticalPoints(stack, 5, 'Dual', 310);
    const roles = classifyPointRoles(stack, 5, pts);
    expect(roles.ok).toBe(true);
    expect(roles.bit_bottom).toEqual([0, 1]);
    expect(roles.sub_top).toEqual([2, 3]);
  });
});
