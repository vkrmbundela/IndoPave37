// Strain–depth profile of a layered section (the profile tile).
//
// Stations: the surface, three interior points in every layer, 0.1 mm either
// side of each interface (the offset of the IRC critical points), and four
// depths into the subgrade. Radii: r = 0 and, for a dual wheel, s/2 (the two
// positions IRC Annex II examines). Per depth the profile keeps
//   eh = max over radii of max(εt, εr)   horizontal, tension positive — the
//        quantity the fatigue criterion takes at the bituminous bottom;
//   ev = max over radii of (−εz)          vertical, compression positive — the
//        rutting strain at the top of the subgrade.

const round1 = (x) => Math.round(x * 10) / 10;

/** @param {{h:number}[]} stack  finite layers then the subgrade (h ignored) */
export function profileDepths(stack) {
  const finite = stack.slice(0, -1).map((l) => Number(l.h) || 0).filter((h) => h > 0);
  const z = new Set([0]);
  let cum = 0;
  finite.forEach((h, k) => {
    const top = cum;
    const bot = cum + h;
    if (k > 0) z.add(round1(top + 0.1));
    [0.25, 0.5, 0.75].forEach((f) => z.add(round1(top + f * h)));
    if (h > 0.2) z.add(round1(bot - 0.1));
    cum = bot;
  });
  const sub = Math.max(150, Math.min(400, 0.5 * cum));
  [0.1, sub / 3, (2 * sub) / 3, sub].forEach((d) => z.add(round1(cum + d)));
  return { depths: [...z].sort((a, b) => a - b), crust: cum, bottom: round1(cum + sub) };
}

/**
 * @param {{stack: {name?:string,h:number,E:number,nu:number}[], load: {wheel_load:number,tire_pressure:number,wheel_type:string,wheel_spacing:number}}} src
 */
export function buildProfileRequest(src) {
  const rows = src.stack.filter((l, i) => i === src.stack.length - 1 || Number(l.h) > 0);
  const { depths, crust, bottom } = profileDepths(rows);
  const dual = String(src.load.wheel_type).toLowerCase() === 'dual';
  const radii = dual ? [0, round1((Number(src.load.wheel_spacing) || 310) / 2)] : [0];
  const request = {
    layers: rows.map((l, i) => ({ E: Number(l.E), nu: Number(l.nu), h: i === rows.length - 1 ? 0 : Number(l.h) })),
    wheel_load: src.load.wheel_load,
    tire_pressure: src.load.tire_pressure,
    wheel_type: src.load.wheel_type,
    wheel_spacing: src.load.wheel_spacing,
    points: depths.flatMap((zz) => radii.map((r) => ({ z: zz, r }))),
  };
  const bands = [];
  let cum = 0;
  rows.slice(0, -1).forEach((l) => {
    bands.push({ name: l.name || '', top: cum, bottom: cum + Number(l.h), E: Number(l.E) });
    cum += Number(l.h);
  });
  bands.push({ name: rows[rows.length - 1]?.name || 'Subgrade', top: cum, bottom, E: Number(rows[rows.length - 1]?.E), subgrade: true });
  return { request, depths, radii, crust, bottom, bands };
}

/** Reduce the solve results (depth-major, radius-minor) to one row per depth. */
export function reduceProfile(results, depths, radii) {
  const out = [];
  depths.forEach((z, i) => {
    let eh = -Infinity;
    let ev = -Infinity;
    radii.forEach((_, j) => {
      const r = results?.[i * radii.length + j];
      if (!r) return;
      eh = Math.max(eh, Number(r.eps_t), Number(r.eps_r));
      ev = Math.max(ev, -Number(r.eps_z));
    });
    if (Number.isFinite(eh) && Number.isFinite(ev)) out.push({ z, eh, ev });
  });
  return out;
}
