import { describe, it, expect } from 'vitest';
import { sectionCostCo2 } from '../lib/cost';
import { profileDepths, buildProfileRequest, reduceProfile } from './profile';

describe('sectionCostCo2 mirrors mep_opt.cost.estimate_cost', () => {
  const stack = [
    { type: 'BC', h: 40 }, { type: 'DBM', h: 110 }, { type: 'WMM', h: 250 },
    { type: 'GSB', h: 200 }, { type: 'CTSB', h: 200 }, { type: 'XYZ', h: 100 },
  ];
  it('matches the backend totals (₹13 468 000 and 234 850 kg per lane-km)', () => {
    // python: estimate_cost([LayerCostSpec('BC',40), …, LayerCostSpec('XYZ',100)])
    expect(sectionCostCo2(stack)).toEqual({ cost: 13468000, co2: 234850 });
  });
  it('a positive user rate replaces the default; blank or zero keeps it', () => {
    const r = sectionCostCo2([{ type: 'BC', h: 40 }], { BC: { cost_per_cum: 20000, co2_per_cum: 0 } });
    expect(r.cost).toBe(3.5 * 40 * 20000);
    expect(r.co2).toBe(3.5 * 40 * 180);
  });
  it('ignores zero-thickness layers', () => {
    expect(sectionCostCo2([{ type: 'BC', h: 0 }])).toEqual({ cost: 0, co2: 0 });
  });
});

describe('strain–depth profile', () => {
  const stack = [
    { name: 'BC', h: 40, E: 3000, nu: 0.35 },
    { name: 'DBM', h: 110, E: 3000, nu: 0.35 },
    { name: 'GSB', h: 200, E: 200, nu: 0.35 },
    { name: 'Subgrade', h: 0, E: 76.8, nu: 0.35 },
  ];
  it('samples the surface and 0.1 mm either side of every interface', () => {
    const { depths, crust } = profileDepths(stack);
    expect(crust).toBe(350);
    for (const z of [0, 39.9, 40.1, 149.9, 150.1, 349.9, 350.1]) expect(depths).toContain(z);
    expect([...depths].sort((a, b) => a - b)).toEqual(depths);
    expect(Math.max(...depths)).toBeGreaterThan(350);
  });
  it('builds one point per depth and radius (r = 0 and s/2 for duals)', () => {
    const b = buildProfileRequest({ stack, load: { wheel_load: 20000, tire_pressure: 0.56, wheel_type: 'Dual', wheel_spacing: 310 } });
    expect(b.radii).toEqual([0, 155]);
    expect(b.request.points.length).toBe(b.depths.length * 2);
    expect(b.request.layers[b.request.layers.length - 1].h).toBe(0);
    expect(b.bands.map((x) => x.name)).toEqual(['BC', 'DBM', 'GSB', 'Subgrade']);
  });
  it('keeps the largest tensile (else most compressive) horizontal and the largest compressive vertical strain', () => {
    const results = [
      { eps_t: -1e-4, eps_r: -2e-4, eps_z: 3e-5 }, { eps_t: -0.5e-4, eps_r: -1e-4, eps_z: 1e-5 },
      { eps_t: 1.2e-4, eps_r: 0.9e-4, eps_z: -2e-4 }, { eps_t: 1.0e-4, eps_r: 1.4e-4, eps_z: -2.4e-4 },
    ];
    expect(reduceProfile(results, [0, 150], [0, 155])).toEqual([
      { z: 0, eh: -2e-4, ev: -1e-5 },
      { z: 150, eh: 1.4e-4, ev: 2.4e-4 },
    ]);
  });
});
