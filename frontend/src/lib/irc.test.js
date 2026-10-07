// Regression tests for the bituminous-layer detection in irc.js.
//
// Both helpers used a substring test, so 'WBM'.includes('BM') made Water
// Bound Macadam (an unbound granular layer) the "bottom bituminous layer":
// the fatigue mix modulus became the WBM modulus and the fatigue probe depth
// moved to the bottom of the WBM.
//
// Run: npm test

import { describe, it, expect } from 'vitest';
import { bottomBituminousModulus, classifyPointRoles, computeGranularAutoE } from './irc';

// BC 40 / DBM 100 / WBM 200 / GSB 200 / subgrade (fixed thicknesses).
const STACK = [
  { type: 'BC',  E: 3000, nu: 0.35, fixed_h: 40,  is_fixed: true },
  { type: 'DBM', E: 2000, nu: 0.35, fixed_h: 100, is_fixed: true },
  { type: 'WBM', E: 250,  nu: 0.35, fixed_h: 200, is_fixed: true },
  { type: 'GSB', E: 200,  nu: 0.35, fixed_h: 200, is_fixed: true },
  { type: '',    E: 60,   nu: 0.35, fixed_h: 0,   is_fixed: true },
];

describe('bottomBituminousModulus', () => {
  it('picks the DBM modulus for a BC/DBM/WBM/GSB stack (WBM is not bituminous)', () => {
    expect(bottomBituminousModulus(STACK, STACK.length)).toBe(2000);
  });

  it('still recognises legacy layers that carry the type only in `name`', () => {
    const legacy = STACK.map(({ type, ...l }) => ({ ...l, name: type || 'Subgrade' }));
    expect(bottomBituminousModulus(legacy, legacy.length)).toBe(2000);
  });

  it('matches whole tokens in free-text names but not substrings', () => {
    const named = [
      { name: 'BC (VG40)', E: 3000 },
      { name: 'DBM-2', E: 1800 },
      { name: 'WBM grade III', E: 250 },
      { name: 'Subgrade', E: 60 },
    ];
    expect(bottomBituminousModulus(named, named.length)).toBe(1800);
  });
});

describe('classifyPointRoles', () => {
  it('puts the fatigue probe at the DBM bottom, not the WBM bottom', () => {
    const points = [
      { z: 139.9, r: 0 }, { z: 139.9, r: 155 },   // bottom of DBM (40 + 100)
      { z: 540.1, r: 0 }, { z: 540.1, r: 155 },   // top of subgrade
    ];
    const roles = classifyPointRoles(STACK, STACK.length, points);
    expect(roles.bitBottomZ).toBe(140);
    expect(roles.subTopZ).toBe(540);
    expect(roles.bit_bottom).toEqual([0, 1]);
    expect(roles.sub_top).toEqual([2, 3]);
    expect(roles.ok).toBe(true);
  });
});

describe('computeGranularAutoE composite (IRC:37-2018 §7.2.3)', () => {
  // The engine analyses WMM + GSB as ONE layer with the thickness-weighted
  // Poisson's ratio; every sub-layer must get that same E and nu so the
  // cockpit Evaluate reproduces the engine's row exactly.
  const comp = [
    { type: 'BC',  E: 2000, nu: 0.35, fixed_h: 40,  is_fixed: true },
    { type: 'WMM', E: 300,  nu: 0.45, fixed_h: 250, is_fixed: true, auto_E: true },
    { type: 'GSB', E: 200,  nu: 0.40, fixed_h: 200, is_fixed: true, auto_E: true },
    { type: '',    E: 66,   nu: 0.35, fixed_h: 0,   is_fixed: true },
  ];
  it('returns one composite E and the thickness-weighted nu for every granular layer', async () => {
    const out = await computeGranularAutoE(comp, comp.length, 8, async () => { throw new Error('no solve'); });
    expect(out.map((u) => u.index)).toEqual([1, 2]);
    expect(out[0].E).toBe(out[1].E);
    const nu = (0.45 * 250 + 0.40 * 200) / 450;
    expect(out[0].nu).toBeCloseTo(nu, 12);
    expect(out[1].nu).toBeCloseTo(nu, 12);
  });
});
