import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  Save, Play, Settings, Plus, Trash2, ArrowRight, Table2, Loader2, Info, X, Download, Upload, Book, RotateCcw, Database, Layers, Zap, AlertCircle, MoreHorizontal, IndianRupee, Activity,
  Sun, Moon, Thermometer, Truck, Gauge, Crosshair, ListChecks, FileText, ChevronDown, Ruler,
} from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
import AdvancedPanel from './v2/AdvancedPanel';
import { solveAnalysis, runOptimize, onSolverStatus, getSolverMode } from './lib/solver-client';
import { useResizableTable } from './lib/useResizableTable';
import {
  subgradeModulusFromCBR, cumulativeMSA, computeGranularAutoE,
  ROAD_CATEGORIES, requiredReliabilityPercent, getMif,
  applyBundleModulus, table92Modulus, BINDER_GRADES, allowableStrains,
  LONG_LIFE_EPS_T, LONG_LIFE_EPS_V, longLifeRecommended, recommendedDesignPeriod,
  CARRIAGEWAYS, indicativeVdf, ircCriticalPoints, classifyPointRoles,
  tensileFatigueStrain, bottomBituminousModulus,
} from './lib/irc';
import { generatePdfReport } from './lib/pdf-report';
import { Tile, Kpi, FlashValue, UtilBar, Chip, Notice, Seg, Field, Toggle } from './cockpit/primitives';
import DesignCard from './cockpit/DesignCard';
import DesignCompare from './cockpit/DesignCompare';

function ColGrip({ rt, i }) {
  return (
    <span
      className="fp-col-grip"
      title="Drag to resize · double-click to reset"
      onPointerDown={(e) => rt.startColResize(i, e)}
      onDoubleClick={() => rt.resetCol(i)}
    />
  );
}

function RowGrip({ rt, rowKey }) {
  return (
    <span
      className="fp-row-grip"
      onPointerDown={(e) => rt.startRowResize(rowKey, e)}
    />
  );
}

function cn(...inputs) {
  return twMerge(clsx(inputs));
}


/* ─── Drag-to-resize hook (vertical splitter) ─── */
function useSplitter(initialValue, direction) {
  const [size, setSize] = useState(initialValue);
  const dragging = useRef(false);
  const startPos = useRef(0);
  const startSize = useRef(0);

  const onPointerDown = useCallback((e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    e.preventDefault();
    dragging.current = true;
    startPos.current = direction === 'horizontal' ? e.clientX : e.clientY;
    startSize.current = size;
    document.body.style.cursor = direction === 'horizontal' ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
    if (e.currentTarget?.setPointerCapture) {
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        // Ignore capture failures and fall back to window listeners.
      }
    }

    const onPointerMove = (ev) => {
      if (!dragging.current) return;
      const delta = direction === 'horizontal'
        ? startPos.current - ev.clientX
        : startPos.current - ev.clientY;
      const newSize = Math.max(100, startSize.current + delta);
      setSize(newSize);
    };

    const onPointerUp = () => {
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointercancel', onPointerUp);
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);
  }, [size, direction]);

  return [size, onPointerDown];
}


function normalizeCtbAxleSpectrum(text) {
  const raw = String(text || '').trim();
  if (!raw) return null;

  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed)) {
    throw new Error('CTB spectrum must be a JSON array of axle groups.');
  }

  return parsed.map((entry, index) => {
    const axleType = String(entry?.axle_type ?? '').trim();
    const loadKn = Number(entry?.load_kn);
    const repetitions = Number(entry?.expected_repetitions);

    if (!axleType) {
      throw new Error(`CTB spectrum row ${index + 1}: axle_type is required`);
    }
    if (!Number.isFinite(loadKn) || loadKn <= 0) {
      throw new Error(`CTB spectrum row ${index + 1}: load_kn must be a positive number`);
    }
    if (!Number.isFinite(repetitions) || repetitions < 0) {
      throw new Error(`CTB spectrum row ${index + 1}: expected_repetitions must be non-negative`);
    }

    return {
      axle_type: axleType,
      load_kn: loadKn,
      expected_repetitions: repetitions,
    };
  });
}

// BC/DBM default to AUTO mode: E follows IRC:37-2018 Table 9.2 for the binder
// grade and pavement temperature of the "Bituminous mix" tile (VG30 @ 35 °C =
// 2000 MPa); untick Auto to pin a tested modulus.
// The unbound granular layers default to AUTO mode: their E is derived from
// IRC:37-2018 Eq. 7.1 (with the §7.2.3 composite rule) and re-derived by the
// optimizer for every candidate thickness — the values below are just seeds
// that the auto-modulus effect recomputes on load.
const DEFAULT_LAYERS = [
  { id: '1', name: 'Layer 1', type: 'BC',  E: 2000,   nu: 0.35, fixed_h: 40,  min_h: 30,  max_h: 50,  is_fixed: true, auto_E: true },
  { id: '2', name: 'Layer 2', type: 'DBM', E: 2000,   nu: 0.35, fixed_h: 120, min_h: 50,  max_h: 250, is_fixed: false, auto_E: true },
  { id: '3', name: 'Layer 3', type: 'WMM', E: 181.6,  nu: 0.35, fixed_h: 250, min_h: 150, max_h: 300, is_fixed: true, auto_E: true },
  { id: '4', name: 'Layer 4', type: 'GSB', E: 181.6,  nu: 0.35, fixed_h: 250, min_h: 150, max_h: 300, is_fixed: true, auto_E: true },
  { id: '5', name: 'Subgrade', type: '', E: 55.4, nu: 0.35, fixed_h: 0, min_h: 0, max_h: 0, is_fixed: true },
];


// Depths follow the Evaluate convention (fixed layers use fixed_h, range
// layers use min_h): BC 40 + DBM 50 (min) = 90 mm bituminous bottom;
// + WMM 250 + GSB 250 = 590 mm top of subgrade. The advanced panels verify
// these against the live interfaces and warn when they drift.
const DEFAULT_POINTS = [
  // Fatigue: bottom of the bituminous bundle (z just inside the AC, above
  // the 90 mm BC/DBM->granular interface).
  { z: 89.9, r: 0 },
  { z: 89.9, r: 155 },
  // Rutting: TOP OF SUBGRADE. The 590 mm granular->subgrade interface must be
  // probed from just BELOW (subgrade side) per IRC:37-2018 §3.6.1 — eps_z is
  // discontinuous there; the granular side under-reports eps_v ~40%.
  { z: 590.1, r: 0 },
  { z: 590.1, r: 155 },
];

// Use-case presets. IRC-consistent: standard dual-wheel axle (20 kN per wheel,
// 0.56 MPa, 310 mm — §3.6.1); bituminous moduli from Table 9.2 (auto, by
// binder grade and temperature) unless a tested value is pinned; unbound
// granular moduli from Eq. 7.1 (auto); LDF from the carriageway (§4.5.1) and
// the indicative VDF of Table 4.2 unless an axle-survey value is stated.
// Analysis points are placed at the IRC critical locations when applied.
const SEED_E = { BC: 2000, DBM: 2000, SDBC: 2000, BM: 700, WMM: 300, WBM: 250, GSB: 200, CRL: 450 };
const B = (id, type, h, opts = {}) => ({
  id: String(id), name: type, type, E: SEED_E[type] ?? 2000, nu: 0.35, fixed_h: h, min_h: h, max_h: h,
  is_fixed: true, auto_E: true, ...opts,
});
const SUB = (id) => ({ id: String(id), name: 'Subgrade', type: '', E: 60, nu: 0.35, fixed_h: 0, min_h: 0, max_h: 0, is_fixed: true });
const DEMO_CASES = [
  {
    name: "National Highway — 4-lane divided (flexible)",
    layers: [B(1, 'BC', 50), B(2, 'DBM', 110), B(3, 'WMM', 250), B(4, 'GSB', 200), SUB(5)],
    binderGrade: 'VG40', roadCategory: 'nh', carriageway: 'dual_2',
    cvpd: 1500, vdf: 5.0, subgradeCbr: 8,
  },
  {
    name: "Semi-rigid: CTB with aggregate crack relief",
    layers: [B(1, 'BC', 50), B(2, 'DBM', 90), B(3, 'CRL', 100), B(4, 'CTB', 150, { E: 5000, nu: 0.25, auto_E: false }),
             B(5, 'CTSB', 200, { E: 600, nu: 0.25, auto_E: false }), SUB(6)],
    binderGrade: 'VG40', roadCategory: 'nh', carriageway: 'dual_2',
    cvpd: 2200, vdf: 5.0, subgradeCbr: 6,
  },
  {
    name: "Semi-rigid: CTB with SAMI (§8.3)",
    layers: [B(1, 'BC', 40), B(2, 'DBM', 60), B(3, 'CTB', 200, { E: 5000, nu: 0.25, auto_E: false }),
             B(4, 'CTSB', 250, { E: 600, nu: 0.25, auto_E: false }), SUB(5)],
    binderGrade: 'VG40', roadCategory: 'sh', carriageway: 'two_lane', hasSami: true,
    cvpd: 1500, vdf: 5.0, subgradeCbr: 8,
  },
  {
    name: "Expressway — long-life design (§10)",
    layers: [B(1, 'BC', 50), B(2, 'DBM', 250, { is_fixed: false, min_h: 200, max_h: 300 }), B(3, 'WMM', 250), B(4, 'GSB', 200), SUB(5)],
    binderGrade: 'VG40', roadCategory: 'expressway', carriageway: 'dual_3', longLife: true,
    cvpd: 4000, vdf: 5.0, subgradeCbr: 7,
  },
  {
    name: "Long-life on CTSB (Annex II.6, Solution 2)",
    layers: [B(1, 'BC', 50), B(2, 'DBM', 200), B(3, 'WMM', 150), B(4, 'CTSB', 300, { E: 600, nu: 0.25, auto_E: false }), SUB(5)],
    binderGrade: 'VG40', roadCategory: 'expressway', carriageway: 'dual_3', longLife: true,
    cvpd: 5000, vdf: 5.0, subgradeCbr: 7,
  },
  {
    name: "High-volume NH — DBM optimised",
    layers: [B(1, 'BC', 50), B(2, 'DBM', 150, { is_fixed: false, min_h: 100, max_h: 250 }), B(3, 'WMM', 200), B(4, 'GSB', 250), SUB(5)],
    binderGrade: 'VG40', roadCategory: 'nh', carriageway: 'dual_3',
    cvpd: 2800, vdf: 5.0, subgradeCbr: 10,
  },
  {
    name: "Urban arterial — 4-lane divided",
    layers: [B(1, 'BC', 50), B(2, 'DBM', 130), B(3, 'WMM', 250), B(4, 'GSB', 150), SUB(5)],
    binderGrade: 'VG40', roadCategory: 'urban', carriageway: 'dual_2',
    cvpd: 1800, vdf: 5.0, subgradeCbr: 7,
  },
  {
    name: "Industrial corridor (axle-survey VDF 6.5)",
    layers: [B(1, 'BC', 50), B(2, 'DBM', 150), B(3, 'WMM', 250), B(4, 'GSB', 250), SUB(5)],
    binderGrade: 'VG40', roadCategory: 'sh', carriageway: 'dual_2',
    cvpd: 3200, vdf: 6.5, subgradeCbr: 9,
  },
  {
    name: "Tested DBM modulus (1800 MPa, below Table 9.2)",
    layers: [B(1, 'BC', 40), B(2, 'DBM', 120, { is_fixed: false, min_h: 80, max_h: 200, E: 1800, auto_E: false }),
             B(3, 'WMM', 200), B(4, 'GSB', 200), SUB(5)],
    binderGrade: 'VG30', roadCategory: 'sh', carriageway: 'two_lane',
    cvpd: 1200, vdf: 3.9, subgradeCbr: 8,
  },
  {
    name: "Weak subgrade (CBR 3 %)",
    layers: [B(1, 'BC', 40), B(2, 'DBM', 130), B(3, 'WMM', 250), B(4, 'GSB', 300), SUB(5)],
    binderGrade: 'VG40', roadCategory: 'sh', carriageway: 'two_lane',
    cvpd: 1000, vdf: 3.9, subgradeCbr: 3,
  },
  {
    name: "CTSB economy base (§7.3.1, 200 mm CTSB)",
    layers: [B(1, 'BC', 40), B(2, 'DBM', 80), B(3, 'WMM', 150), B(4, 'CTSB', 200, { E: 600, nu: 0.25, auto_E: false }),
             B(5, 'GSB', 100), SUB(6)],
    binderGrade: 'VG40', roadCategory: 'sh', carriageway: 'two_lane',
    cvpd: 1100, vdf: 3.9, subgradeCbr: 6,
  },
  {
    name: "Geogrid-reinforced base (SP:59 MIF)",
    layers: [B(1, 'BC', 40), B(2, 'DBM', 90), B(3, 'WMM', 200, { geogrid: 'PET30' }), B(4, 'GSB', 200), SUB(5)],
    binderGrade: 'VG40', roadCategory: 'sh', carriageway: 'two_lane',
    cvpd: 900, vdf: 3.9, subgradeCbr: 5,
  },
  {
    name: "Low-volume rural road (single lane)",
    layers: [B(1, 'SDBC', 25), B(2, 'WMM', 250), B(3, 'GSB', 250), SUB(4)],
    binderGrade: 'VG30', roadCategory: 'other', carriageway: 'single', designLife: 15,
    cvpd: 150, vdf: 1.7, subgradeCbr: 5,
  },
];


const DEFAULT_MATERIAL_RATES = {
  BC: { cost_per_cum: 12500, co2_per_cum: 180 },
  DBM: { cost_per_cum: 10800, co2_per_cum: 165 },
  SMA: { cost_per_cum: 14000, co2_per_cum: 195 },
  SDBC: { cost_per_cum: 9800, co2_per_cum: 160 },
  BM: { cost_per_cum: 8500, co2_per_cum: 145 },
  WMM: { cost_per_cum: 2800, co2_per_cum: 35 },
  WBM: { cost_per_cum: 2500, co2_per_cum: 30 },
  GSB: { cost_per_cum: 1800, co2_per_cum: 25 },
  CTB: { cost_per_cum: 3500, co2_per_cum: 120 },
  RAP: { cost_per_cum: 6000, co2_per_cum: 85 },
};

// Strip blank / zero / non-finite unit-rate fields before sending to the API.
// A cleared input becomes Number('') === 0; sending 0 would make the material
// "free" (or zero-carbon) and corrupt cost/CO2 optimization. Omitting the field
// instead lets the backend apply its built-in IRC/MoRTH default for it. A
// material whose fields are all blank is dropped entirely.
function sanitizeMaterialRates(rates) {
  const out = {};
  for (const [code, r] of Object.entries(rates || {})) {
    const clean = {};
    for (const k of ['cost_per_cum', 'co2_per_cum', 'density', 'transport_co2_factor']) {
      const v = r?.[k];
      if (Number.isFinite(v) && v > 0) clean[k] = v;
    }
    if (Object.keys(clean).length) out[code] = clean;
  }
  return out;
}

// Structural equality of two computeGranularAutoE results ([{index, E, auto}])
// on the fields analysisLayers reads (index and E).
function sameEngineModuli(a, b) {
  if (a === b) return true;
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  return a.every((x, k) => x.index === b[k].index && x.E === b[k].E && x.nu === b[k].nu);
}

// Selectable pavement material types (must match backend BITUMINOUS_TYPES /
// GRANULAR_TYPES so the optimizer can classify each layer). Optional per layer.
// Full material database with IRC:37-2018 names and default properties.
const MATERIAL_DATABASE = {
  BC:   { name: 'Bituminous Concrete',           abbr: 'BC',   default_E: 2000, default_nu: 0.35, category: 'bituminous' },
  DBM:  { name: 'Dense Bituminous Macadam',       abbr: 'DBM',  default_E: 2000, default_nu: 0.35, category: 'bituminous' },
  BM:   { name: 'Bituminous Macadam',             abbr: 'BM',   default_E: 700,  default_nu: 0.35, category: 'bituminous' },
  SDBC: { name: 'Semi-Dense Bituminous Concrete', abbr: 'SDBC', default_E: 2000, default_nu: 0.35, category: 'bituminous' },
  SMA:  { name: 'Stone Matrix Asphalt',           abbr: 'SMA',  default_E: 1600, default_nu: 0.35, category: 'bituminous' },
  WMM:  { name: 'Wet Mix Macadam',                abbr: 'WMM',  default_E: 300,  default_nu: 0.35, category: 'granular' },
  WBM:  { name: 'Water Bound Macadam',            abbr: 'WBM',  default_E: 250,  default_nu: 0.35, category: 'granular' },
  GSB:  { name: 'Granular Sub-Base',              abbr: 'GSB',  default_E: 200,  default_nu: 0.35, category: 'granular' },
  CRL:  { name: 'Granular Crack Relief Layer',    abbr: 'CRL',  default_E: 450,  default_nu: 0.35, category: 'granular' },
  CTB:  { name: 'Cement Treated Base',            abbr: 'CTB',  default_E: 5000, default_nu: 0.25, category: 'cement_treated' },
  CTSB: { name: 'Cement Treated Sub-Base',        abbr: 'CTSB', default_E: 600,  default_nu: 0.25, category: 'cement_treated' },
  // Emulsion/foam bitumen stabilised RAP BASE (IRC:37-2018 §8.4): 800 MPa, not part of the bituminous bundle.
  RAP:  { name: 'Stabilised RAP Base (emulsion/foam)', abbr: 'RAP', default_E: 800, default_nu: 0.35, category: 'cold_recycled' },
};
const LAYER_TYPE_OPTIONS = Object.keys(MATERIAL_DATABASE);
// Granular layer types that accept geosynthetic (geogrid) reinforcement.
const GRANULAR_LAYER_TYPES = new Set(['WMM', 'WBM', 'GSB']);
// Unbound granular types eligible for the "Auto Eq. 7.1" derived modulus
// (CRL included — the engine assigns it the fixed IRC 450 MPa when it sits
// directly above a cement-treated base, Eq. 7.1 otherwise).
const AUTO_E_TYPES = new Set(['WMM', 'WBM', 'GSB', 'CRL']);
// Bituminous types: "Auto" takes E from IRC:37-2018 Table 9.2 (binder grade,
// pavement temperature). The engine analyses the whole bundle at the bottom
// mix's modulus (§9.2).
const BIT_TYPES = new Set(['BC', 'DBM', 'BM', 'SDBC', 'SMA']);

// Resolve the effective material type for a layer: explicit `type` wins; else
// fall back to `name` when it is itself a known type (legacy use-case data).
const layerType = (l) => typeof l.type === 'string' ? l.type : (LAYER_TYPE_OPTIONS.includes(l.name) ? l.name : '');

// What an Evaluate result depends on — compared with the current inputs to
// flag a result as stale after an edit. Auto moduli are derived from the
// other entries (thickness, CBR, binder, temperature), so they enter as 'auto'.
function inputSignature({ layers, numLayers, points, load, pressure, wheelType, wheelSpacing, subgradeCbr, binderGrade, temperature }) {
  const n = Math.min(numLayers, layers.length);
  return JSON.stringify([
    layers.slice(0, n).map((l, i) => [
      layerType(l), (l.auto_E || i === n - 1) ? 'auto' : Number(l.E), Number(l.nu),
      l.is_fixed ? Number(l.fixed_h) : Number(l.min_h), l.geogrid || '',
    ]),
    points.map((p) => [Number(p.z), Number(p.r)]),
    load, pressure, wheelType, wheelSpacing, subgradeCbr, binderGrade, temperature,
  ]);
}

// Nominal (Evaluate) thickness: fixed_h, else min_h.
const nominalH = (l) => {
  const h = l?.is_fixed ? Number(l?.fixed_h) : Number(l?.min_h);
  return Number.isFinite(h) && h > 0 ? h : 0;
};
// IRC:SP:59 / Saride et al. 2022 geogrid options (MIF approach, capped at 2.0).
const GEOGRID_OPTIONS = [
  { id: 'none', label: 'No geogrid' },
  { id: 'PP30', label: 'PP30' },
  { id: 'PET30', label: 'PET30' },
  { id: 'PET60', label: 'PET60' },
];

const DEFAULT_CTB_AXLE_SPECTRUM_TEXT = JSON.stringify([
  { axle_type: 'single', load_kn: 80, expected_repetitions: 1000000 },
  { axle_type: 'tandem', load_kn: 120, expected_repetitions: 200000 },
  { axle_type: 'tridem', load_kn: 180, expected_repetitions: 50000 },
], null, 2);

/*
 * INITIAL design assumptions. Growth rate, design life, VDF and LDF are
 * user-editable in the "Opt Target" panel (state below); these constants
 * only seed a fresh project. Both /api/optimize and every advanced panel
 * read the live state values, so they always agree.
 *
 * Defaults follow IRC 37:2018 typical values (growth ≥ 5% per §4.2.3;
 * 20-year design life for NH/SH; LDF 0.75 for dual carriageways).
 */
const DESIGN_DEFAULTS = {
  growthRate: 0.05,         // 5% per annum
  designLife: 20,           // years
  ldf: 0.75,                // lane distribution factor
  vdf: 2.5,                 // vehicle damage factor
  // IRC:37-2018 §3.7 / Eq. 3.5: road category sets the reliability (R90 for
  // Expressway/NH/SH/urban at any traffic, else R90 only at >= 20 msa) and
  // the CTB RF factor. National Highway is the conservative default.
  roadCategory: 'nh',
  constructionYears: 0,     // x in IRC Eq. 4.6 (count year -> opening year)
  carriageway: 'dual_2',    // IRC §4.5.1: dual two-lane -> LDF 0.75
  terrain: 'plain',         // IRC Table 4.2 indicative VDF column
  binderGrade: 'VG30',      // IRC Table 9.2 row of the bottom bituminous mix
  longLife: false,          // IRC §10 long-life (endurance) design
  hasSami: false,           // IRC §8.3 SAMI crack relief over a CTB
};

/* ─── Compact Cross-Section SVG ─── */
const getOverlayId = (l, isSubgrade) => {
  if (isSubgrade) return 'overlay-soil';
  const type = (l.type || l.name || '').toUpperCase();
  if (/\bBM\b/.test(type) || type.includes('BC') || type.includes('DBM') || type.includes('SMA') || type.includes('SDBC') || type.includes('PAVED') || type.includes('SURFACE')) {
    return 'overlay-asphalt';
  }
  if (type.includes('WMM') || type.includes('WBM') || type.includes('BASE')) {
    return 'overlay-granular';
  }
  if (type.includes('GSB') || type.includes('SUBBASE') || type.includes('SAND') || type.includes('GRAVEL')) {
    return 'overlay-gsb';
  }
  if (type.includes('CTB') || type.includes('CEMENT')) {
    return 'overlay-ctb';
  }
  return 'overlay-granular';
};

const getLayerColor = (l, i, isSubgrade) => {
  if (isSubgrade) return '#7c6552';
  const type = (l.type || l.name || '').toUpperCase();
  if (type.includes('BC')) return '#1e293b';
  if (type.includes('DBM')) return '#334155';
  // Whole-token BM only: 'WBM' (unbound granular) must reach its own branch.
  if (/\bBM\b/.test(type) || type.includes('SMA') || type.includes('SDBC') || type.includes('PAVED')) return '#1c1917';
  if (type.includes('WMM')) return '#475569';
  if (type.includes('WBM')) return '#5a6b7c';
  if (type.includes('GSB')) return '#78716c';
  if (type.includes('CTB')) return '#4c586a';
  
  const colors = ['#2e3b4e', '#3f4f64', '#55667d', '#6e7e96', '#8797b0'];
  return colors[i % colors.length];
};

function PavementVisualizer({ layers, points, wheelType, wheelSpacing = 310, load = 20000, pressure = 0.56, highlight = null, onHover = null }) {
  // F scales annotation text and its boxes so labels stay legible when the
  // drawing is rendered in a ~400 px tile.
  const F = 1.6;
  const surfaceY = 95;
  const svgH = 470;
  const depth = svgH - surfaceY - 25;

  const getVisualThickness = (l) => {
    if (l.is_fixed) {
      const val = Number(l.fixed_h);
      return isNaN(val) || val <= 0 ? 100 : val;
    } else {
      // Range (Opt) layers are drawn at the thickness Evaluate analyses
      // (min_h), so the analysis points sit where they are evaluated.
      const minVal = Number(l.min_h);
      if (!isNaN(minVal) && minVal > 0) return minVal;
      const maxVal = Number(l.max_h);
      if (!isNaN(maxVal) && maxVal > 0) return maxVal;
      return 100; // default fallback if both are invalid/empty
    }
  };

  const finite = layers.slice(0, -1);
  const totalH = finite.reduce((s, l) => s + getVisualThickness(l), 0);
  const maxPt = Math.max(0, ...points.map(p => p.z));
  const target = Math.max(totalH + 100, maxPt + 80);
  const scale = depth / target;

  const wSp = wheelSpacing * scale;
  const tireW = Math.max(12, Math.min(30, 160 * scale));
  const tireH = Math.max(15, Math.min(36, 200 * scale));
  const badgeY = -tireH - 30 * F;
  const badgeW = 75 * F, badgeH = 20 * F;

  // Calculate dynamic half-width of pavement block based on points and wheels
  const halfSw = Math.max(
    140, // default minimum half-width (corresponding to sw = 280)
    ...points.map(p => p.r * scale + 48 * F), // fit all points plus space for their labels
    (wheelSpacing / 2) * scale + tireW / 2 + 20 // fit the tires with some margin
  );
  const sw = halfSw * 2;

  // Calculate dynamic SVG layout width and centerline translation
  const leftPadding = 112;
  const rightPadding = 38 + 50 * F + 8;
  const minX = -halfSw - leftPadding;
  const maxX = halfSw + rightPadding;
  const svgW = maxX - minX;
  const centerX = -minX;

  const rulerX = -halfSw - 58;
  const dimX = -halfSw - 30;

  const drawWheel = (cx) => {
    const treads = [];
    const step = tireH / 6;
    for (let y = -tireH + step/2; y < 0; y += step) {
      treads.push(
        <line key={`tl-${cx}-${y}`} x1={cx - tireW/2} y1={y} x2={cx - tireW/2 + tireW*0.14} y2={y} stroke="var(--vis-border)" strokeWidth="1.2" />,
        <line key={`tr-${cx}-${y}`} x1={cx + tireW/2} y1={y} x2={cx + tireW/2 - tireW*0.14} y2={y} stroke="var(--vis-border)" strokeWidth="1.2" />
      );
    }
    
    const bolts = [];
    const rBolts = tireW * 0.16;
    for (let a = 0; a < 360; a += 60) {
      const rad = (a * Math.PI) / 180;
      const bx = cx + rBolts * Math.cos(rad);
      const by = -tireH/2 + rBolts * Math.sin(rad);
      bolts.push(<circle key={`bolt-${cx}-${a}`} cx={bx} cy={by} r={tireW * 0.025} fill="#000000" opacity="0.8" />);
    }
    
    return (
      <g key={`wheel-${cx}`}>
        <rect
          x={cx - tireW/2}
          y={-tireH}
          width={tireW}
          height={tireH}
          rx={tireW * 0.08}
          fill="url(#tire-grad)"
          stroke="#0f172a"
          strokeWidth="0.8"
        />
        {treads}
        <circle
          cx={cx}
          cy={-tireH/2}
          r={tireW * 0.28}
          fill="url(#rim-grad)"
          stroke="#1e293b"
          strokeWidth="0.6"
        />
        <circle
          cx={cx}
          cy={-tireH/2}
          r={tireW * 0.09}
          fill="#0f172a"
        />
        {bolts}
      </g>
    );
  };

  const drawAxle = () => {
    const axleThick = Math.max(3, tireW * 0.16);
    return (
      <g key="dual-axle">
        {/* Main axle shaft */}
        <rect
          x={-wSp/2}
          y={-tireH/2 - axleThick/2}
          width={wSp}
          height={axleThick}
          fill="url(#axle-grad)"
          stroke="#0f172a"
          strokeWidth="0.5"
        />
        {/* End connectors / flanges */}
        <rect x={-wSp/2 - 2} y={-tireH/2 - axleThick} width="3" height={axleThick * 2} fill="#475569" stroke="#0f172a" strokeWidth="0.4" />
        <rect x={wSp/2 - 1} y={-tireH/2 - axleThick} width="3" height={axleThick * 2} fill="#475569" stroke="#0f172a" strokeWidth="0.4" />
        {/* Center differential housing */}
        <circle
          cx="0"
          cy={-tireH/2}
          r={axleThick * 1.5}
          fill="url(#axle-grad)"
          stroke="#0f172a"
          strokeWidth="0.8"
        />
        <circle
          cx="0"
          cy={-tireH/2}
          r={axleThick * 0.7}
          fill="#1e293b"
          opacity="0.8"
        />
      </g>
    );
  };

  const drawSingleAxle = () => {
    const axleThick = Math.max(3, tireW * 0.16);
    return (
      <g key="single-axle">
        {/* Stub axle */}
        <rect
          x={-tireW*0.6}
          y={-tireH/2 - axleThick/2}
          width={tireW * 1.2}
          height={axleThick}
          fill="url(#axle-grad)"
          stroke="#0f172a"
          strokeWidth="0.5"
        />
        {/* Vertical suspension strut going upwards */}
        <rect
          x={-axleThick/2}
          y={-tireH - 10}
          width={axleThick}
          height={tireH - tireH/2 + 10}
          fill="url(#axle-grad)"
          stroke="#0f172a"
          strokeWidth="0.5"
        />
      </g>
    );
  };

  const drawStressBulb = (cx) => {
    const stressPath = `M ${cx - tireW/2} 0 
                        L ${cx - tireW/2 - depth*0.7} ${depth} 
                        L ${cx + tireW/2 + depth*0.7} ${depth} 
                        L ${cx + tireW/2} 0 Z`;
                        
    const isobars = [];
    const steps = [1.2, 2.2, 3.5];
    steps.forEach((step, idx) => {
      const radius = tireW * step;
      const startX = cx - radius * Math.cos(35 * Math.PI / 180);
      const startY = radius * Math.sin(35 * Math.PI / 180);
      const endX = cx + radius * Math.cos(35 * Math.PI / 180);
      const endY = radius * Math.sin(35 * Math.PI / 180);
      
      isobars.push(
        <path
          key={`iso-${cx}-${idx}`}
          d={`M ${startX} ${startY} A ${radius} ${radius} 0 0 1 ${endX} ${endY}`}
          fill="none"
          stroke="var(--vis-stress-outline)"
          strokeWidth="0.6"
          strokeDasharray="2,3"
        />
      );
    });
    
    return (
      <g key={`bulb-${cx}`}>
        <path
          d={stressPath}
          fill="url(#stress-grad)"
          opacity="0.85"
          pointerEvents="none"
        />
        {isobars}
      </g>
    );
  };

  return (
    <svg viewBox={`0 0 ${svgW} ${svgH}`} className="w-full h-full" preserveAspectRatio="xMidYMid meet">
      <defs>
        {/* Asphalt speckle overlay */}
        <pattern id="overlay-asphalt" width="12" height="12" patternUnits="userSpaceOnUse">
          <rect x="2" y="3" width="1" height="1" fill="#fff" opacity="0.3" />
          <rect x="8" y="9" width="1" height="1.2" fill="#000" opacity="0.4" />
          <circle cx="5" cy="7" r="0.5" fill="#fff" opacity="0.25" />
          <circle cx="10" cy="2" r="0.7" fill="#000" opacity="0.35" />
        </pattern>
        
        {/* Granular base overlay */}
        <pattern id="overlay-granular" width="24" height="24" patternUnits="userSpaceOnUse">
          <path d="M2,4 L5,2 L7,4 L4,6 Z" fill="#000" opacity="0.2" stroke="#fff" strokeWidth="0.3" strokeOpacity="0.2" />
          <path d="M12,14 L15,12 L17,14 L14,16 Z" fill="#fff" opacity="0.15" stroke="#000" strokeWidth="0.3" strokeOpacity="0.2" />
          <circle cx="6" cy="18" r="1.2" fill="#fff" opacity="0.2" />
          <circle cx="21" cy="19" r="1.5" fill="#000" opacity="0.25" />
        </pattern>
        
        {/* GSB sand overlay */}
        <pattern id="overlay-gsb" width="8" height="8" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="0.4" fill="#fff" opacity="0.35"/>
          <circle cx="6" cy="4" r="0.5" fill="#000" opacity="0.4"/>
          <circle cx="4" cy="7" r="0.3" fill="#fff" opacity="0.25"/>
        </pattern>

        {/* CTB cross-hatch overlay */}
        <pattern id="overlay-ctb" width="16" height="16" patternUnits="userSpaceOnUse">
          <path d="M 0,0 l 16,16 M 16,0 l -16,16" stroke="#fff" strokeWidth="0.5" opacity="0.15" />
          <path d="M 0,0 l 16,16 M 16,0 l -16,16" stroke="#000" strokeWidth="0.5" opacity="0.1" />
        </pattern>
        
        {/* Soil horizontal lines */}
        <pattern id="overlay-soil" width="30" height="20" patternUnits="userSpaceOnUse">
          <path d="M 0 5 Q 7.5 2, 15 5 T 30 5" fill="none" stroke="#000" strokeWidth="0.6" opacity="0.12" />
          <path d="M 0 15 Q 7.5 12, 15 15 T 30 15" fill="none" stroke="#fff" strokeWidth="0.6" opacity="0.08" />
        </pattern>

        {/* Grid pattern */}
        <pattern id="grid-pattern" width="10" height="10" patternUnits="userSpaceOnUse">
          <line x1="0" y1="0" x2="10" y2="0" stroke="var(--vis-grid)" strokeWidth="0.5" />
          <line x1="0" y1="0" x2="0" y2="10" stroke="var(--vis-grid)" strokeWidth="0.5" />
        </pattern>
        <pattern id="grid-major-pattern" width="50" height="50" patternUnits="userSpaceOnUse">
          <rect width="50" height="50" fill="var(--vis-bg)" />
          <rect width="50" height="50" fill="url(#grid-pattern)" />
          <line x1="0" y1="0" x2="50" y2="0" stroke="var(--vis-grid-major)" strokeWidth="0.8" />
          <line x1="0" y1="0" x2="0" y2="50" stroke="var(--vis-grid-major)" strokeWidth="0.8" />
        </pattern>

        {/* Tire & rim gradients */}
        <linearGradient id="tire-grad" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#1e293b" />
          <stop offset="20%" stopColor="#0f172a" />
          <stop offset="50%" stopColor="#475569" />
          <stop offset="80%" stopColor="#0f172a" />
          <stop offset="100%" stopColor="#1e293b" />
        </linearGradient>
        <radialGradient id="rim-grad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#f8fafc" />
          <stop offset="65%" stopColor="#cbd5e1" />
          <stop offset="100%" stopColor="#475569" />
        </radialGradient>
        <linearGradient id="axle-grad" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#cbd5e1" />
          <stop offset="50%" stopColor="#64748b" />
          <stop offset="100%" stopColor="#334155" />
        </linearGradient>
        
        {/* Stress distribution linear gradient */}
        <linearGradient id="stress-grad" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="var(--vis-stress-bulb)" />
          <stop offset="100%" stopColor="rgba(234, 88, 12, 0)" />
        </linearGradient>
      </defs>

      {/* Blueprint grid background */}
      <rect width={svgW} height={svgH} fill="url(#grid-major-pattern)" stroke="var(--vis-border)" strokeWidth="1" />

      <g transform={`translate(${centerX}, ${surfaceY})`}>
        {/* Center line (CL) */}
        <line x1="0" y1={-surfaceY + 12} x2="0" y2={depth + 10} stroke="var(--vis-cl)" strokeWidth="0.8" strokeDasharray="6,4,2,4" />
        <text x="0" y={-surfaceY + 14 * F} textAnchor="middle" fontSize={6.5 * F} fill="var(--vis-text-muted)" fontWeight="700" letterSpacing="0.5">CENTERLINE</text>

        {/* Stress Dispersion Cones (rendered under layers for correct blend) */}
        {wheelType === 'Dual' ? (
          <>
            {drawStressBulb(-wSp/2)}
            {drawStressBulb(wSp/2)}
          </>
        ) : (
          drawStressBulb(0)
        )}

        {/* Pavement Layers */}
        {layers.map((l, i) => {
          const sub = i === layers.length - 1;
          const hmm = sub ? target : getVisualThickness(l);
          const hpx = hmm * scale;
          const dy = layers.slice(0, i).reduce((s, p) => s + (getVisualThickness(p) * scale), 0);
          const drawH = sub ? Math.max(hpx, depth + 10 - dy) : Math.max(hpx, 4);
          
          const overlayId = getOverlayId(l, sub);
          const baseColor = getLayerColor(l, i, sub);
          
          return (
            <g key={i} className="group cursor-pointer"
               onMouseEnter={onHover ? () => onHover(i) : undefined}
               onMouseLeave={onHover ? () => onHover(null) : undefined}>
              {/* Solid layer fill */}
              <rect x={-sw/2} y={dy} width={sw} height={drawH} fill={baseColor} stroke="var(--vis-bg)" strokeWidth="0.5" />
              
              {/* Texture overlay pattern */}
              <rect x={-sw/2} y={dy} width={sw} height={drawH} fill={`url(#${overlayId})`} opacity="0.28" pointerEvents="none" />

              {/* Linked highlight: the row hovered in the layer table */}
              {highlight === i && (
                <rect x={-sw/2 + 0.75} y={dy + 0.75} width={sw - 1.5} height={Math.max(1, drawH - 1.5)}
                      fill="rgba(234, 88, 12, 0.14)" stroke="#ea580c" strokeWidth="1.5" pointerEvents="none" />
              )}
              
              {/* Inner layer labeling */}
              {(drawH > 6.5 * F + 2 || sub) && (
                <text
                  x={-sw/2 + 8}
                  y={dy + (sub ? 15 * F : drawH / 2 + 2.5 * F)}
                  fontSize={6.5 * F}
                  fill="#ffffff"
                  fontWeight="700"
                  fontFamily="Inter, system-ui, sans-serif"
                  style={{ textShadow: '0 1px 2px rgba(0,0,0,0.7)' }}
                  opacity="0.95"
                >
                  {sub ? 'Subgrade' : `${l.type || l.name || `L${i+1}`}`}
                </text>
              )}
              
              {/* Geogrid indicator */}
              {l.geogrid && l.geogrid !== 'none' && (
                <g>
                  <line x1={-sw/2} y1={dy + drawH} x2={sw/2} y2={dy + drawH} stroke="#ea580c" strokeWidth="1.8" strokeDasharray="4,2" />
                  <line x1={-sw/2} y1={dy + drawH} x2={sw/2} y2={dy + drawH} stroke="#f59e0b" strokeWidth="0.8" strokeDasharray="1,3" />
                  <rect x={sw/2 - 45 * F} y={dy + drawH - 5 * F} width={42 * F} height={10 * F} rx="1.5" fill="#ea580c" />
                  <text x={sw/2 - 24 * F} y={dy + drawH + 2.5 * F} textAnchor="middle" fontSize={5 * F} fill="#ffffff" fontWeight="bold">
                    GEOGRID: {l.geogrid}
                  </text>
                </g>
              )}
              
              <title>{`${sub ? 'Subgrade Layer' : `Layer ${i+1}: ${l.type || l.name}`}\nThickness: ${sub ? 'Infinite' : (l.is_fixed ? `${l.fixed_h} mm` : `${l.min_h}-${l.max_h} mm`)}\nElastic Modulus (E): ${l.E} MPa\nPoisson Ratio (nu): ${l.nu}`}</title>
            </g>
          );
        })}

        {/* Wheels & Axles */}
        {wheelType === 'Dual' ? (
          <>
            {drawAxle()}
            {drawWheel(-wSp/2)}
            {drawWheel(wSp/2)}
          </>
        ) : (
          <>
            {drawSingleAxle()}
            {drawWheel(0)}
          </>
        )}

        {/* Load HUD Badge */}
        {(() => {
          const displayLoad = load ? (load / 1000).toFixed(1) + ' kN' : '—';
          const displayPressure = pressure ? pressure + ' MPa' : '—';
          return (
            <g>
              {wheelType === 'Dual' ? (
                <>
                  <line x1={-25 * F} y1={badgeY + badgeH} x2={-wSp/2} y2={-tireH} stroke="var(--vis-text-muted)" strokeWidth="0.6" strokeDasharray="1,1" />
                  <line x1={25 * F} y1={badgeY + badgeH} x2={wSp/2} y2={-tireH} stroke="var(--vis-text-muted)" strokeWidth="0.6" strokeDasharray="1,1" />
                </>
              ) : (
                <line x1={0} y1={badgeY + badgeH} x2={0} y2={-tireH} stroke="var(--vis-text-muted)" strokeWidth="0.6" strokeDasharray="1,1" />
              )}
              
              <rect
                x={-badgeW/2}
                y={badgeY}
                width={badgeW}
                height={badgeH}
                rx="3"
                fill="var(--vis-bg)"
                stroke="var(--vis-border)"
                strokeWidth="0.8"
                style={{ filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.05))' }}
              />
              <text x="0" y={badgeY + 8 * F} textAnchor="middle" fontSize={5.5 * F} fill="var(--vis-text)" fontWeight="800" fontFamily="monospace">
                LOAD: {displayLoad}
              </text>
              <text x="0" y={badgeY + 15 * F} textAnchor="middle" fontSize={5 * F} fill="var(--vis-text-muted)" fontWeight="bold" fontFamily="monospace">
                PRES: {displayPressure}
              </text>
            </g>
          );
        })()}

        {/* CAD Ruler - Left side vertical cumulative depth ruler */}
        <g>
          <line x1={rulerX} y1={0} x2={rulerX} y2={target * scale} stroke="var(--vis-text)" strokeWidth="0.8" />
          <text x={rulerX} y={-6} textAnchor="middle" fontSize={5 * F} fill="var(--vis-text-muted)" fontWeight="bold" letterSpacing="0.2">DEPTH (mm)</text>
          
          {(() => {
            const ticks = [];
            const tickStep = 50;
            for (let z = 0; z <= target; z += tickStep) {
              const zy = z * scale;
              const isMajor = z % 100 === 0;
              const tickLen = isMajor ? 8 : 4;
              ticks.push(
                <g key={`ruler-tick-${z}`}>
                  <line x1={rulerX - tickLen} y1={zy} x2={rulerX} y2={zy} stroke="var(--vis-text-muted)" strokeWidth={isMajor ? 0.8 : 0.5} />
                  {isMajor && (
                    <text x={rulerX - 10} y={zy + 2.5 * F} textAnchor="end" fontSize={5.5 * F} fill="var(--vis-text-muted)" fontFamily="monospace" fontWeight="600">
                      {z}
                    </text>
                  )}
                </g>
              );
            }
            return ticks;
          })()}
        </g>

        {/* CAD Layer Dimensions - Segment brackets */}
        {layers.map((l, i) => {
          const sub = i === layers.length - 1;
          if (sub) return null;
          const hmm = getVisualThickness(l);
          const hpx = hmm * scale;
          const dy = layers.slice(0, i).reduce((s, p) => s + (getVisualThickness(p) * scale), 0);
          const dimLabel = l.is_fixed ? `${hmm}` : `${l.min_h}–${l.max_h}`;
          
          return (
            <g key={`layer-dim-${i}`}>
              <line x1={-halfSw} y1={dy} x2={-halfSw - 25} y2={dy} stroke="var(--vis-border)" strokeWidth="0.4" strokeDasharray="1,2" />
              <line x1={-halfSw} y1={dy + hpx} x2={-halfSw - 25} y2={dy + hpx} stroke="var(--vis-border)" strokeWidth="0.4" strokeDasharray="1,2" />
              <line x1={dimX} y1={dy} x2={dimX} y2={dy + hpx} stroke="var(--vis-text-muted)" strokeWidth="0.6" />
              <polygon points={`${dimX},${dy} ${dimX - 2},${dy + 3.5} ${dimX + 2},${dy + 3.5}`} fill="var(--vis-text-muted)" />
              <polygon points={`${dimX},${dy + hpx} ${dimX - 2},${dy + hpx - 3.5} ${dimX + 2},${dy + hpx - 3.5}`} fill="var(--vis-text-muted)" />
              
              {hpx > 9 * F && (
                <g>
                  <rect x={dimX - (l.is_fixed ? 15 : 24) * F} y={dy + hpx/2 - 4.5 * F} width={(l.is_fixed ? 30 : 48) * F} height={9 * F} fill="var(--vis-bg)" opacity="0.9" />
                  <text x={dimX} y={dy + hpx/2 + 1.8 * F} textAnchor="middle" fontSize={5 * F} fill={l.is_fixed ? 'var(--vis-text)' : '#ea580c'} fontWeight="700" fontFamily="monospace">
                    {dimLabel}
                  </text>
                </g>
              )}
            </g>
          );
        })}

        {/* Right side specifications callouts (with slanted leader lines) */}
        {layers.map((l, i) => {
          const sub = i === layers.length - 1;
          const hmm = sub ? 80 : getVisualThickness(l);
          const hpx = hmm * scale;
          const dy = layers.slice(0, i).reduce((s, p) => s + (getVisualThickness(p) * scale), 0);
          
          const calloutY = -15 * F + (i * 40 * F * 0.95);
          const layerMidY = dy + hpx/2;
          
          return (
            <g key={`callout-${i}`}>
              <path
                d={`M ${sw/2 - 8} ${layerMidY} L ${sw/2 + 10} ${layerMidY} L ${sw/2 + 25} ${calloutY} L ${sw/2 + 38} ${calloutY}`}
                fill="none"
                stroke="var(--vis-border)"
                strokeWidth="0.6"
              />
              <circle cx={sw/2 - 8} cy={layerMidY} r="1.5" fill="var(--vis-text-muted)" />
              
              <rect
                x={sw/2 + 38}
                y={calloutY - 11 * F}
                width={50 * F}
                height={22 * F}
                rx="2"
                fill="var(--vis-bg)"
                stroke="var(--vis-border)"
                strokeWidth="0.6"
                opacity="0.9"
              />
              <text x={sw/2 + 38 + 4 * F} y={calloutY - 3 * F} fontSize={5.2 * F} fill="var(--vis-text)" fontWeight="bold" letterSpacing="0.2">
                E: {Number(l.E).toFixed(Number(l.E) >= 100 ? 0 : 1)} MPa
              </text>
              <text x={sw/2 + 38 + 4 * F} y={calloutY + 4 * F} fontSize={5 * F} fill="var(--vis-text-muted)" fontWeight="bold" letterSpacing="0.2">
                ν: {Number(l.nu).toFixed(2)}
              </text>
              <text x={sw/2 + 38 + 46 * F} y={calloutY + 8 * F} fontSize={4 * F} fill="var(--vis-text-muted)" fontWeight="bold" textAnchor="end">
                {sub ? 'SUB' : `L${i+1}`}
              </text>
            </g>
          );
        })}

        {/* HUD Interactive Target Analysis Points */}
        {points.map((p, i) => {
          // Clamp horizontal position within the pavement block so points
          // never render outside the road cross-section.  r is a radial
          // offset in the analysis coordinate system — in this 2D depth
          // view we show it as a proportional offset from centerline,
          // capped to half the block width minus label room.
          const maxPx = halfSw - 48 * F;
          const rawPx = p.r * scale;
          const px = Math.min(rawPx, maxPx);
          const py = p.z * scale;
          
          return (
            <g key={`pt-${i}`} className="cursor-pointer group">
              {/* Radar pulse effect */}
              <circle cx={px} cy={py} r="2.5" fill="none" stroke="#10b981" strokeWidth="0.5">
                <animate attributeName="r" values="2.5;8;2.5" dur="3s" repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.8;0;0.8" dur="3s" repeatCount="indefinite" />
              </circle>
              
              {/* Target locks */}
              <circle cx={px} cy={py} r="4" fill="none" stroke="#10b981" strokeWidth="0.8" />
              <circle cx={px} cy={py} r="1.2" fill="#10b981" />
              <line x1={px - 6} y1={py} x2={px + 6} y2={py} stroke="#10b981" strokeWidth="0.6" />
              <line x1={px} y1={py - 6} x2={px} y2={py + 6} stroke="#10b981" strokeWidth="0.6" />
              
              {/* Point badge label */}
              <g>
                <rect
                  x={px + 8}
                  y={py - 6 * F}
                  width={34 * F}
                  height={11 * F}
                  rx="1.5"
                  fill="var(--vis-bg)"
                  stroke="#10b981"
                  strokeWidth="0.6"
                  opacity="0.85"
                />
                <text x={px + 8 + 2 * F} y={py + 2 * F} fontSize={5 * F} fill="#059669" fontWeight="bold" fontFamily="monospace">
                  P{i+1}: {p.z.toFixed(0)}
                </text>
              </g>
              
              <title>{`Analysis Point P${i+1}\nDepth (z): ${p.z} mm\nRadius (r): ${p.r} mm`}</title>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

export default function App() {
  // Load initial state from localStorage if available. A corrupted blob
  // (or a quota / disabled-storage exception) must NOT crash the whole
  // app — fall back to defaults instead.
  let savedData;
  try {
    // NOTE: the localStorage key intentionally keeps its legacy name
    // ('flexpave_cache') so users' previously-saved sessions survive the
    // IndoPave-37 rebrand. It is an internal key, never shown to users.
    savedData = JSON.parse(localStorage.getItem('flexpave_cache') || '{}');
    if (typeof savedData !== 'object' || savedData === null || Array.isArray(savedData)) {
      savedData = {};
    }
  } catch {
    savedData = {};
  }

  const [layers, setLayers] = useState(savedData.layers || DEFAULT_LAYERS);
  const [numLayers, setNumLayers] = useState(savedData.numLayers || 5);
  const [load, setLoad] = useState(savedData.load || 20000);
  const [pressure, setPressure] = useState(savedData.pressure || 0.56);
  const [wheelType, setWheelType] = useState(savedData.wheelType || 'Dual');
  const [wheelSpacing, setWheelSpacing] = useState(savedData.wheelSpacing || 310);
  const [points, setPoints] = useState(savedData.points || DEFAULT_POINTS);
  const [numPoints, setNumPoints] = useState(savedData.numPoints || 4);
  const [cvpd, setCvpd] = useState(savedData.cvpd || 800);
  const [subgradeCbr, setSubgradeCbr] = useState(savedData.subgradeCbr || 8);
  const [temperature, setTemperature] = useState(savedData.temperature || 35);
  // IRC:37-2018 §3.6.2 fatigue C-factor inputs for the BOTTOM bituminous mix.
  // C = 10^(4.84*(Vbe/(Va+Vbe) - 0.69)). Defaults match the IRC Annex-II
  // worked example (Va = 3.0 %, Vbe = 11.5 %). Use ?? so an explicit 0 is kept.
  const [airVoids, setAirVoids] = useState(savedData.airVoids ?? 3.0);
  const [bitumenVolume, setBitumenVolume] = useState(savedData.bitumenVolume ?? 11.5);
  // Traffic assumptions (IRC:37-2018 §4) — previously hard-coded constants;
  // now user-editable so the design traffic matches the actual project.
  const [growthRate, setGrowthRate] = useState(savedData.growthRate ?? DESIGN_DEFAULTS.growthRate);
  const [designLife, setDesignLife] = useState(savedData.designLife ?? DESIGN_DEFAULTS.designLife);
  const [vdf, setVdf] = useState(savedData.vdf ?? DESIGN_DEFAULTS.vdf);
  const [ldf, setLdf] = useState(savedData.ldf ?? DESIGN_DEFAULTS.ldf);
  const [roadCategory, setRoadCategory] = useState(savedData.roadCategory ?? DESIGN_DEFAULTS.roadCategory);
  const [constructionYears, setConstructionYears] = useState(savedData.constructionYears ?? DESIGN_DEFAULTS.constructionYears);
  const [carriageway, setCarriageway] = useState(savedData.carriageway ?? DESIGN_DEFAULTS.carriageway);
  const [terrain, setTerrain] = useState(savedData.terrain ?? DESIGN_DEFAULTS.terrain);
  const [binderGrade, setBinderGrade] = useState(savedData.binderGrade ?? DESIGN_DEFAULTS.binderGrade);
  const [longLife, setLongLife] = useState(savedData.longLife ?? DESIGN_DEFAULTS.longLife);
  const [hasSami, setHasSami] = useState(savedData.hasSami ?? DESIGN_DEFAULTS.hasSami);
  // Geometry / moduli the last Evaluate analysed, for its IRC verdict.
  const [evalContext, setEvalContext] = useState(savedData.evalContext || null);
  const [hoverLayer, setHoverLayer] = useState(null);
  // Per-viewer display preference (light is the default theme).
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('indopave_theme') === 'dark' ? 'dark' : 'light'; } catch { return 'light'; }
  });
  // Engine moduli of the non-bituminous layers ([{index, E, auto}]) — the
  // values the optimizer analyses; Evaluate and the advanced panels use them.
  const [engineGranularE, setEngineGranularE] = useState([]);
  const [autoEError, setAutoEError] = useState(null);

  const [results, setResults] = useState(savedData.results || null);
  // Advisory warnings returned by /api/optimize (reliability escalation,
  // CTB spectrum notes, infeasibility diagnostics) — previously dropped.
  const [optimizeWarnings, setOptimizeWarnings] = useState(null);
  const [error, setError] = useState(null);
  const [isSolving, setIsSolving] = useState(false);
  const [solverStatus, setSolverStatus] = useState(null);
  const [optimizationMode, setOptimizationMode] = useState(savedData.optimizationMode || false);
  const [optimizedDesigns, setOptimizedDesigns] = useState(savedData.optimizedDesigns || null);
  const [sp72Info, setSp72Info] = useState(null);
  const [reinforcementInfo, setReinforcementInfo] = useState(null);
  const [showInstructions, setShowInstructions] = useState(false);
  const [helpActiveTab, setHelpActiveTab] = useState('workflow');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [hasStarted, setHasStarted] = useState(savedData.hasStarted || false);
  // One-time notice when the workspace was restored from the browser's
  // auto-save — otherwise a returning user sees "mystery" pre-filled values
  // with no explanation of where they came from.
  const [restoredNotice, setRestoredNotice] = useState(
    !!(savedData.layers || savedData.results || savedData.optimizedDesigns)
  );
  const [materialRates, setMaterialRates] = useState(savedData.materialRates || DEFAULT_MATERIAL_RATES);
  const [showRatesPanel, setShowRatesPanel] = useState(savedData.showRatesPanel || false);
  const [showCtbPanel, setShowCtbPanel] = useState(savedData.showCtbPanel || false);
  const [useCtbSpectrum, setUseCtbSpectrum] = useState(savedData.useCtbSpectrum || false);
  const [ctbSpectrumText, setCtbSpectrumText] = useState(savedData.ctbSpectrumText || '');
  const [ctbPerClassBridgeRecompute, setCtbPerClassBridgeRecompute] = useState(savedData.ctbPerClassBridgeRecompute || false);
  const [optimizeByCost, setOptimizeByCost] = useState(savedData.optimizeByCost || false);
  const [optimizeByCo2, setOptimizeByCo2] = useState(savedData.optimizeByCo2 || false);
  const [debugMode, setDebugMode] = useState(false); // Default to off for production
  const fileInputRef = useRef(null);

  // Resizable vertical splitter (inputs ↔ preview)
  const [previewWidth, onPreviewDrag] = useSplitter(Math.max(440, savedData.previewWidth || 440), 'horizontal');


  // Auto-Save Effect
  useEffect(() => {
    const dataToSave = {
      layers, numLayers, load, pressure, wheelType, wheelSpacing, points, numPoints,
      cvpd, subgradeCbr, temperature, airVoids, bitumenVolume, results, optimizationMode,
      optimizedDesigns, hasStarted, previewWidth,
      growthRate, designLife, vdf, ldf, roadCategory, constructionYears,
      carriageway, terrain, binderGrade, longLife, hasSami, evalContext,
      materialRates, showRatesPanel,
      showCtbPanel, useCtbSpectrum, ctbSpectrumText, ctbPerClassBridgeRecompute,
      optimizeByCost, optimizeByCo2,
    };
    try {
      localStorage.setItem('flexpave_cache', JSON.stringify(dataToSave));
    } catch {
      // Storage full or disabled: the session simply is not auto-saved.
    }
  }, [
    layers, numLayers, load, pressure, wheelType, wheelSpacing, points, numPoints,
    cvpd, subgradeCbr, temperature, airVoids, bitumenVolume, results, optimizationMode,
    optimizedDesigns, hasStarted, previewWidth,
    growthRate, designLife, vdf, ldf, roadCategory, constructionYears,
    carriageway, terrain, binderGrade, longLife, hasSami, evalContext,
    materialRates, showRatesPanel, debugMode,
    showCtbPanel, useCtbSpectrum, ctbSpectrumText, ctbPerClassBridgeRecompute,
    optimizeByCost, optimizeByCo2,
  ]);

  const handleReset = () => {
    if (window.confirm("Are you sure you want to reset everything? This will clear all current input and results.")) {
      if (window.confirm("Would you like to save your project work (JSON) before resetting?")) {
        handleExport();
      }
      localStorage.removeItem('flexpave_cache');
      window.location.reload(); // Hard reset to initial states
    }
  };

  const updateLayer = (idx, f, v) => setLayers(prev => prev.map((l,i) => i===idx ? {...l,[f]:v} : l));
  const updatePoint = (idx, f, v) => setPoints(prev => prev.map((p,i) => i===idx ? {...p,[f]:v} : p));
  const updateMaterialRate = (code, field, value) => setMaterialRates(prev => ({ ...prev, [code]: { ...(prev[code]||{}), [field]: value } }));

  useEffect(() => {
    setLayers(prev => {
      const c = [...prev];
      while (c.length < numLayers) c.splice(c.length-1,0,{ id:String(c.length), name:`Layer ${c.length}`, type:'', E:500, nu:0.35, fixed_h:100, min_h:50, max_h:200, is_fixed:true });
      while (c.length > numLayers) c.splice(c.length-2,1);
      return c;
    });
  }, [numLayers]);

  useEffect(() => {
    setLayers(prev => {
      if (prev.length === 0) return prev;
      const lastIdx = prev.length - 1;
      const subgradeLayer = prev[lastIdx];
      const newE = Number(subgradeModulusFromCBR(subgradeCbr).toFixed(2));
      if (subgradeLayer && subgradeLayer.E !== newE) {
        return prev.map((l, i) => i === lastIdx ? { ...l, E: newE } : l);
      }
      return prev;
    });
  }, [subgradeCbr]);

  useEffect(() => {
    document.documentElement.classList.toggle('theme-dark', theme === 'dark');
    try { localStorage.setItem('indopave_theme', theme); } catch { /* preference only */ }
  }, [theme]);

  // Auto bituminous layers follow IRC:37-2018 Table 9.2 for the selected binder
  // grade and pavement temperature (BM: its fixed 35 °C value).
  useEffect(() => {
    setLayers(prev => {
      const n = Math.min(numLayers, prev.length);
      let changed = false;
      const next = prev.map((l, i) => {
        const t = layerType(l);
        if (i >= n - 1 || !l.auto_E || !BIT_TYPES.has(t)) return l;
        const E = Math.round(table92Modulus(binderGrade, temperature, t) * 10) / 10;
        if (Math.abs(Number(l.E) - E) <= 0.05) return l;
        changed = true;
        return { ...l, E };
      });
      return changed ? next : prev;
    });
  }, [layers, numLayers, binderGrade, temperature]);

  // Engine-consistent moduli for the non-bituminous layers (IRC Eq. 7.1 with
  // the §7.2.3 composite rule, effective support per Eq. 6.3, fixed IRC values
  // over CTB/CTSB, capped geogrid MIF). Auto-mode layers DISPLAY this value;
  // Evaluate and the advanced panels ANALYSE with it for every such layer, so
  // all three agree with the optimizer. Debounced: the effective-support case
  // needs a solver call.
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const updates = await computeGranularAutoE(layers, numLayers, subgradeCbr, solveAnalysis);
        if (cancelled) return;
        setAutoEError(null);
        // Keep the previous array when nothing changed, so analysisLayers
        // (and every panel effect that depends on it) stays referentially stable.
        setEngineGranularE(prev => (sameEngineModuli(prev, updates) ? prev : updates));
        setLayers(prev => {
          let changed = false;
          const next = prev.map((l, i) => {
            const u = updates.find(x => x.index === i && x.auto);
            if (u && Math.abs(Number(l.E) - u.E) > 0.05) {
              changed = true;
              return { ...l, E: u.E };
            }
            return l;
          });
          return changed ? next : prev;
        });
      } catch (e) {
        if (!cancelled) {
          setAutoEError(e.message);
          // Drop the stale engine moduli: they are keyed by array index, so
          // after a layer edit they would land on whatever layer now has
          // that index.
          setEngineGranularE(prev => (prev.length ? [] : prev));
        }
      }
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [layers, numLayers, subgradeCbr]);

  // Layers with the engine moduli substituted (what Evaluate / panels analyse).
  // Memoised: it is passed to the advanced panels as sharedState.layers, and
  // a fresh array on every render re-fired their effects (e.g. /reserve).
  // The bituminous bundle is analysed at the bottom mix's E and nu (§9.2).
  const analysisLayers = useMemo(() => applyBundleModulus(layers.map((l, i) => {
    const u = engineGranularE.find(x => x.index === i);
    return u ? { ...l, E: u.E, ...(u.nu != null ? { nu: u.nu } : {}) } : l;
  }), numLayers), [layers, engineGranularE, numLayers]);

  const designMsa = cumulativeMSA({ cvpd, growthRate, designLife, ldf, vdf, constructionYears });
  const reliabilityPercent = requiredReliabilityPercent(designMsa, roadCategory);

  useEffect(() => {
    setPoints(prev => {
      const c = [...prev];
      while (c.length < numPoints) c.push({ z:0, r:0 });
      return c.slice(0, numPoints);
    });
  }, [numPoints]);

  useEffect(() => {
    if (getSolverMode() === 'backend') return undefined;
    return onSolverStatus((s) => {
      setSolverStatus(s.stage === 'ready' ? null : s.message);
    });
  }, []);

  const doSingleRun = async (overrides = null) => {
    setIsSolving(true); setError(null); setResults(null); setOptimizedDesigns(null); setOptimizationMode(false);
    try {
      // If overrides is a demo object (has .layers), use it; otherwise use current state.
      const isDemo = overrides && overrides.layers;
      const targetLayers = isDemo ? overrides.layers : layers;
      const targetLoad = isDemo ? overrides.load : load;
      const targetPressure = isDemo ? overrides.pressure : pressure;
      const targetWheelType = isDemo ? overrides.wheelType : wheelType;
      const targetPoints = isDemo ? overrides.points : points;
      const targetNum = isDemo ? (overrides.numLayers ?? targetLayers.length) : numLayers;
      const targetCbr = isDemo ? (overrides.subgradeCbr ?? subgradeCbr) : subgradeCbr;
      // Analyse with the SAME non-bituminous moduli the optimizer uses
      // (computed fresh so a pending auto-E update can never race the run).
      const engineE = await computeGranularAutoE(targetLayers, targetNum, targetCbr, solveAnalysis);
      const eOf = (l, i) => engineE.find(x => x.index === i)?.E ?? l.E;
      const nuOf = (l, i) => engineE.find(x => x.index === i)?.nu ?? l.nu;
      const targetSpacing = isDemo ? (overrides.wheelSpacing ?? 310) : wheelSpacing;
      // IRC §9.2: the bituminous bundle at the bottom mix's modulus, as the optimizer.
      const analysed = applyBundleModulus(
        targetLayers.map((l, i) => ({ ...l, E: eOf(l, i), nu: nuOf(l, i) })), targetNum,
      );

      const data = await solveAnalysis({
        layers: analysed.map((l, i) => ({
          E: l.E,
          nu: l.nu,
          h: i === targetLayers.length - 1 ? 0 : (l.is_fixed ? (l.fixed_h || 0) : (l.min_h || 0)),
        })),
        wheel_load: targetLoad,
        tire_pressure: targetPressure,
        wheel_type: targetWheelType,
        wheel_spacing: targetSpacing,
        points: targetPoints.map(p => ({ z: p.z, r: p.r })),
      });
      setResults(data.results || []);
      setEvalContext({
        layers: targetLayers.map(l => ({ type: layerType(l) || l.name, is_fixed: l.is_fixed, fixed_h: l.fixed_h, min_h: l.min_h })),
        numLayers: targetNum,
        mrm: bottomBituminousModulus(analysed, targetNum),
        hasBituminous: targetLayers.slice(0, targetNum - 1).some(l => BIT_TYPES.has(layerType(l))),
        signature: inputSignature({
          layers: targetLayers, numLayers: targetNum, points: targetPoints, load: targetLoad,
          pressure: targetPressure, wheelType: targetWheelType, wheelSpacing: targetSpacing,
          subgradeCbr: targetCbr,
          binderGrade: isDemo ? (overrides.binderGrade ?? binderGrade) : binderGrade,
          temperature: isDemo ? (overrides.temperature ?? 35) : temperature,
        }),
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setIsSolving(false);
      setSolverStatus(null);
    }
  };

  const doOptimize = async () => {
    setIsSolving(true); setError(null); setOptimizedDesigns(null); setResults(null); setOptimizationMode(true);
    setOptimizeWarnings(null);
    try {
      const untyped = layers.slice(0, Math.max(0, numLayers - 1))
        .map((l, i) => ({ i, t: layerType(l) }))
        .filter(x => !x.t);
      if (untyped.length) {
        throw new Error(`Select a material type for layer(s) ${untyped.map(x => x.i + 1).join(', ')} before optimizing.`);
      }
      const parsedCtbSpectrum = useCtbSpectrum ? normalizeCtbAxleSpectrum(ctbSpectrumText) : null;
      const data = await runOptimize({
        layers: layers.map(l=>({
          layer_type: layerType(l) || l.name,
          // Auto-mode granular layers send E = null so the engine derives the
          // modulus from IRC:37-2018 Eq. 7.1 for EVERY candidate thickness
          // (a pinned number here would freeze the modulus while the
          // optimizer varies the thickness — non-IRC behaviour).
          E: (l.auto_E && AUTO_E_TYPES.has(layerType(l))) ? null : l.E,
          nu: l.nu,
          is_fixed: l.is_fixed,
          fixed_thickness: l.fixed_h || 0,
          min_thickness: l.min_h || 0,
          max_thickness: l.max_h || 0,
          geogrid: (GRANULAR_LAYER_TYPES.has(layerType(l)) && l.geogrid) ? l.geogrid : null,
        })),
        cvpd,
        subgrade_cbr: subgradeCbr,
        temperature,
        air_voids: airVoids,
        bitumen_volume: bitumenVolume,
        growth_rate: growthRate,
        design_life: designLife,
        lane_factor: ldf,
        vdf,
        reliability: `${reliabilityPercent}%`,
        road_category: roadCategory,
        construction_years: constructionYears,
        wheel_load: load,
        tire_pressure: pressure,
        wheel_type: wheelType,
        wheel_spacing: wheelSpacing,
        points: points.map(p=>({z:p.z, r:p.r})),
        // Sanitize material rates: drop any blank/zero/non-finite field so the
        // backend falls back to its built-in IRC/MoRTH default for it (a
        // cleared field must NOT be sent as 0, which would treat the material
        // as free/zero-carbon and corrupt the Economy/Sustainable/Premium cards).
        material_rates: sanitizeMaterialRates(materialRates),
        ctb_axle_spectrum: parsedCtbSpectrum && parsedCtbSpectrum.length ? parsedCtbSpectrum : undefined,
        ctb_per_class_bridge_recompute: ctbPerClassBridgeRecompute,
        optimize_by_cost: optimizeByCost,
        optimize_by_co2: optimizeByCo2,
        has_sami: hasSami,
        long_life: longLife,
      });
      setOptimizedDesigns(data.adequate_designs || []);
      setSp72Info(data.sp72 || null);
      setReinforcementInfo(data.reinforcement && data.reinforcement.length ? data.reinforcement : null);
      // Advisory warnings (reliability auto-escalation, CTB spectrum notes,
      // infeasibility diagnostics) — surface them instead of dropping them.
      setOptimizeWarnings(data.warnings && data.warnings.length ? data.warnings : null);
    } catch(e) { setError(e.message); }
    finally { setIsSolving(false); }
  };

  const handleExport = () => {
    const cfg = {
      layers, numLayers, load, pressure, wheelType, points, numPoints,
      cvpd, subgradeCbr, temperature, airVoids, bitumenVolume, materialRates, showRatesPanel,
      growthRate, designLife, vdf, ldf, roadCategory, constructionYears,
      carriageway, terrain, binderGrade, longLife, hasSami, wheelSpacing,
      useCtbSpectrum, ctbSpectrumText, ctbPerClassBridgeRecompute,
      optimizeByCost, optimizeByCo2,
    };
    const b = new Blob([JSON.stringify(cfg,null,2)],{type:'application/json'});
    const u = URL.createObjectURL(b);
    const a = document.createElement('a'); a.href=u; a.download='indopave37_config.json'; a.click();
    URL.revokeObjectURL(u);
  };

  const handlePdfExport = () => {
    // Generated entirely client-side (jsPDF) so it works on the static
    // GitHub-Pages deploy with no backend. Needs at least one optimized design.
    const designs = optimizedDesigns || [];
    if (!designs.length) {
      alert('Run the Optimizer first — the PDF report needs at least one design.');
      return;
    }
    // Was IRC Eq. 7.1 actually in force for this run? Only when every unbound
    // granular layer was in auto-E mode (the engine skips Eq. 7.1 for layers
    // with a pinned modulus) — the PDF compliance table must not over-claim.
    const structural = layers.slice(0, Math.min(numLayers, layers.length) - 1);
    const unboundGranular = structural.filter(l => AUTO_E_TYPES.has(layerType(l)));
    const granularAutoE = unboundGranular.length > 0 && unboundGranular.every(l => !!l.auto_E);
    try {
      generatePdfReport({
        projectName: `IndoPave-37 — CBR ${subgradeCbr}%, ${cvpd} CVPD`,
        trafficParams: {
          cvpd,
          growth_rate: growthRate,
          vdf,
          ldf,
          design_life: designLife,
          // x in IRC Eq. 4.6 (A = P(1+r)^x) and the §3.7 road category: both
          // enter the engine's design MSA / reliability, so the printed
          // inputs must include them to reproduce the printed result.
          construction_years: constructionYears,
          road_category: roadCategory,
          carriageway_label: (CARRIAGEWAYS.find(c => c.id === carriageway) || {}).label,
        },
        subgradeCbr,
        selectedSolution: designs[0],
        adequateDesigns: designs,
        airVoids,
        bitumenVolume,
        granularAutoE,
        binderGrade,
        temperature,
        table92: table92Modulus(binderGrade, temperature, 'DBM'),
        hasSami: hasSami && layers.slice(0, numLayers - 1).some(l => layerType(l) === 'CTB'),
      });
    } catch (e) {
      alert(`PDF export failed: ${e.message}`);
    }
  };

  const handleImport = (e) => {
    const file = e.target.files[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const d = JSON.parse(ev.target.result);
        const hasValue = (v) => v !== undefined && v !== null;

        if (Array.isArray(d.layers)) setLayers(d.layers);
        if (hasValue(d.numLayers)) setNumLayers(d.numLayers);
        if (hasValue(d.load)) setLoad(d.load);
        if (hasValue(d.pressure)) setPressure(d.pressure);
        if (hasValue(d.wheelType)) setWheelType(d.wheelType);
        if (Array.isArray(d.points)) setPoints(d.points);
        if (hasValue(d.numPoints)) setNumPoints(d.numPoints);
        if (hasValue(d.cvpd)) setCvpd(d.cvpd);
        if (hasValue(d.subgradeCbr)) setSubgradeCbr(d.subgradeCbr);
        if (hasValue(d.temperature)) setTemperature(d.temperature);
        if (hasValue(d.airVoids)) setAirVoids(d.airVoids);
        if (hasValue(d.bitumenVolume)) setBitumenVolume(d.bitumenVolume);
        if (hasValue(d.growthRate)) setGrowthRate(d.growthRate);
        if (hasValue(d.designLife)) setDesignLife(d.designLife);
        if (hasValue(d.vdf)) setVdf(d.vdf);
        if (hasValue(d.ldf)) setLdf(d.ldf);
        if (hasValue(d.roadCategory)) setRoadCategory(d.roadCategory);
        if (hasValue(d.constructionYears)) setConstructionYears(d.constructionYears);
        if (hasValue(d.carriageway)) setCarriageway(d.carriageway);
        if (hasValue(d.terrain)) setTerrain(d.terrain);
        if (hasValue(d.binderGrade)) setBinderGrade(d.binderGrade);
        if (hasValue(d.longLife)) setLongLife(d.longLife);
        if (hasValue(d.hasSami)) setHasSami(d.hasSami);
        if (hasValue(d.wheelSpacing)) setWheelSpacing(d.wheelSpacing);
        if (d.materialRates) setMaterialRates(d.materialRates);
        if (hasValue(d.showRatesPanel)) setShowRatesPanel(d.showRatesPanel);
        if (hasValue(d.useCtbSpectrum)) setUseCtbSpectrum(d.useCtbSpectrum);
        if (hasValue(d.ctbSpectrumText)) setCtbSpectrumText(d.ctbSpectrumText);
        if (hasValue(d.ctbPerClassBridgeRecompute)) setCtbPerClassBridgeRecompute(d.ctbPerClassBridgeRecompute);
        if (hasValue(d.optimizeByCost)) setOptimizeByCost(d.optimizeByCost);
        if (hasValue(d.optimizeByCo2)) setOptimizeByCo2(d.optimizeByCo2);
      } catch { alert("Invalid config."); }
      setHasStarted(true);
    };
    reader.readAsText(file); e.target.value='';
  };

  const handleApplyDemo = (demo) => {
    const n = demo.numLayers ?? demo.layers.length;
    const wt = demo.wheelType ?? 'Dual';
    const ld = demo.load ?? 20000;
    const pr = demo.pressure ?? 0.56;
    const sp = demo.wheelSpacing ?? 310;
    const grade = demo.binderGrade ?? binderGrade;
    const temp = demo.temperature ?? 35;
    const cbr = demo.subgradeCbr ?? subgradeCbr;
    // Resolve the auto bituminous moduli and the subgrade modulus now, so an
    // immediate Evaluate analyses the preset as its tiles will show it.
    const lays = demo.layers.map((l, i) => {
      if (i === demo.layers.length - 1) return { ...l, E: Number(subgradeModulusFromCBR(cbr).toFixed(2)) };
      return (l.auto_E && BIT_TYPES.has(layerType(l))) ? { ...l, E: table92Modulus(grade, temp, layerType(l)) } : l;
    });
    const pts = demo.points ?? ircCriticalPoints(lays, n, wt, sp);
    setLayers(lays);
    setNumLayers(n);
    setLoad(ld);
    setPressure(pr);
    setWheelType(wt);
    setWheelSpacing(sp);
    setPoints(pts);
    setNumPoints(pts.length);
    if (demo.cvpd) setCvpd(demo.cvpd);
    setSubgradeCbr(cbr);
    setBinderGrade(grade);
    setTemperature(temp);
    setLongLife(!!demo.longLife);
    setHasSami(!!demo.hasSami);
    if (demo.vdf) setVdf(demo.vdf);
    if (demo.roadCategory) setRoadCategory(demo.roadCategory);
    if (demo.designLife) setDesignLife(demo.designLife);
    else if (demo.roadCategory) setDesignLife(recommendedDesignPeriod(demo.roadCategory, 0));
    if (demo.carriageway) {
      const cw = CARRIAGEWAYS.find(c => c.id === demo.carriageway);
      setCarriageway(demo.carriageway);
      if (cw) setLdf(cw.ldf);
    }
    setHasStarted(true);
    // Auto-trigger evaluation if all layers are fixed
    if (lays.every(l => l.is_fixed || l.name === 'Subgrade')) {
      setTimeout(() => doSingleRun({
        ...demo, layers: lays, numLayers: n, load: ld, pressure: pr, wheelType: wt,
        wheelSpacing: sp, points: pts, subgradeCbr: cbr, binderGrade: grade, temperature: temp,
      }), 100);
    }
  };

  const [showDemos, setShowDemos] = useState(false);
  const [showMoreMenu, setShowMoreMenu] = useState(false);

  const inp = "bg-white border border-slate-300 rounded-md px-1.5 py-0.5 text-xs text-slate-800 outline-none focus:border-orange-500 focus:ring-2 focus:ring-orange-100 hover:border-slate-400 font-mono transition-colors";

  // Resizable tables — column widths (px) per data table.
  const layerRT = useResizableTable([92, 236, 62, 132, 64, 204, 150]);
  const pointsRT = useResizableTable([28, 90, 90]);
  const formatSci = (v) => {
    if (v === undefined || v === null) return '—';
    const n = Number(v);
    return Number.isFinite(n) ? n.toExponential(4) : '—';
  };

  /* ── Derived design basis (shown live in the tiles) ── */
  const nAll = Math.min(numLayers, layers.length);
  const structuralLayers = layers.slice(0, Math.max(0, nAll - 1));
  const stackHasCtb = structuralLayers.some(l => layerType(l) === 'CTB');
  const bitLayers = structuralLayers.filter(l => BIT_TYPES.has(layerType(l)));
  const bottomBitType = bitLayers.length ? layerType(bitLayers[bitLayers.length - 1]) : null;
  const crustMin = structuralLayers.reduce((s, l) => s + nominalH(l), 0);
  const crustMax = structuralLayers.reduce((s, l) => s + (l.is_fixed ? nominalH(l) : (Number(l.max_h) || 0)), 0);
  const bitMin = bitLayers.reduce((s, l) => s + nominalH(l), 0);
  const mrsNow = subgradeModulusFromCBR(subgradeCbr);
  const cwNow = CARRIAGEWAYS.find(c => c.id === carriageway) || CARRIAGEWAYS[4];
  const ldfIsCustom = Math.abs(Number(ldf) - cwNow.ldf) > 1e-9;
  const initialTwoWay = (cwNow.directional ? 2 : 1) * (Number(cvpd) || 0) * Math.pow(1 + Number(growthRate), Number(constructionYears) || 0);
  const vdfSuggest = indicativeVdf(initialTwoWay, terrain);
  const bundleE = bitLayers.length ? bottomBituminousModulus(analysisLayers, numLayers) : null;
  const t92Now = table92Modulus(binderGrade, temperature, bottomBitType || 'DBM');
  const cFactor = Math.pow(10, 4.84 * (Number(bitumenVolume) / (Number(airVoids) + Number(bitumenVolume)) - 0.69));
  const allowNow = allowableStrains({ msa: designMsa, reliability: reliabilityPercent, mrm: bundleE, airVoids, bitumenVolume });
  const llRecommended = longLifeRecommended(designMsa, roadCategory);
  const recLife = recommendedDesignPeriod(roadCategory, designMsa);
  const isStdAxle = Number(load) === 20000 && Number(pressure) === 0.56 && wheelType === 'Dual' && Number(wheelSpacing) === 310;
  const pointRoles = classifyPointRoles(layers, numLayers, points);
  // Bottom of a CTB (Evaluate thickness), for the CTB-fatigue probe role.
  const ctbBottomZ = (() => {
    let cum = 0; let z = null;
    structuralLayers.forEach((l) => { cum += nominalH(l); if (layerType(l) === 'CTB') z = cum; });
    return z;
  })();
  const pointRoleOf = (i) => (pointRoles.bit_bottom.includes(i) ? 'fatigue'
    : pointRoles.sub_top.includes(i) ? 'rutting'
    : (ctbBottomZ != null && Math.abs(Number(points[i]?.z) - ctbBottomZ) <= 5) ? 'ctb' : null);
  const currentSignature = inputSignature({
    layers, numLayers, points, load, pressure, wheelType, wheelSpacing, subgradeCbr, binderGrade, temperature,
  });

  // IRC verdict of the last Evaluate: strains at the critical points against
  // the allowable strains of the CURRENT traffic / reliability / mix.
  let evalVerdict = null;
  if (!optimizationMode && results && results.length && evalContext) {
    const roles = classifyPointRoles(evalContext.layers, evalContext.numLayers, results.map(r => ({ z: r.z, r: r.r })));
    const bitRows = roles.bit_bottom.map(i => results[i]);
    const subRows = roles.sub_top.map(i => results[i]);
    const epsT = bitRows.length ? tensileFatigueStrain(bitRows) : null;
    const epsV = subRows.length ? Math.max(...subRows.map(r => Math.abs(Number(r.eps_z) || 0))) : null;
    const allow = allowableStrains({ msa: designMsa, reliability: reliabilityPercent, mrm: evalContext.mrm, airVoids, bitumenVolume });
    const compressive = bitRows.length > 0 && epsT === 0;
    evalVerdict = {
      roles,
      epsT, epsV, allow, compressive,
      hasBituminous: evalContext.hasBituminous,
      cdfF: epsT > 0 && allow.epsT ? Math.pow(epsT / allow.epsT, 3.89) : null,
      cdfR: epsV != null && allow.epsV ? Math.pow(epsV / allow.epsV, 4.5337) : null,
      llT: longLife && epsT > 0 ? epsT / LONG_LIFE_EPS_T : null,
      llV: longLife && epsV != null ? epsV / LONG_LIFE_EPS_V : null,
      stale: evalContext.signature !== currentSignature,
    };
  }

  // Keyboard: Ctrl/⌘+Enter evaluates, Ctrl/⌘+Shift+Enter optimizes.
  useEffect(() => {
    if (!hasStarted) return undefined;
    const onKey = (e) => {
      if (e.key !== 'Enter' || !(e.ctrlKey || e.metaKey) || isSolving) return;
      e.preventDefault();
      if (e.shiftKey) doOptimize(); else doSingleRun();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // The usage guide closes on Escape.
  useEffect(() => {
    if (!showInstructions) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') setShowInstructions(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [showInstructions]);

  // Menus close on Escape and on a click outside them.
  useEffect(() => {
    if (!showDemos && !showMoreMenu) return undefined;
    const close = () => { setShowDemos(false); setShowMoreMenu(false); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    const onDown = (e) => { if (!e.target.closest?.('[data-menu]')) close(); };
    window.addEventListener('keydown', onKey);
    window.addEventListener('pointerdown', onDown);
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('pointerdown', onDown); };
  }, [showDemos, showMoreMenu]);

  // "Use" on a design card: its thicknesses become the (fixed) layer
  // thicknesses, so the section can be evaluated or analysed in the advanced
  // panels. The optimizer's layer order is the table order (subgrade last).
  const applyDesign = (d) => {
    const th = (d.optimal_layers || []).map(l => Number(l.thickness));
    if (!th.length) return;
    const next = layers.map((l, i) => (i < th.length && i < nAll - 1 && Number.isFinite(th[i]))
      ? { ...l, is_fixed: true, fixed_h: th[i] } : l);
    setLayers(next);
    const pts = ircCriticalPoints(next, numLayers, wheelType, wheelSpacing);
    if (pts.length) { setPoints(pts); setNumPoints(pts.length); }
    document.getElementById('tile-layers')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const placeIrcPoints = () => {
    const pts = ircCriticalPoints(layers, numLayers, wheelType, wheelSpacing);
    if (!pts.length) return;
    setPoints(pts);
    setNumPoints(pts.length);
  };
  const sectionW = Math.max(320, Math.min(720, previewWidth));

  // IRC:37-2018 minimum thickness of a layer (the rules the optimizer always
  // enforces; CTSB 200 mm is only recommended, §7.3.1).
  const ircMinOf = (l, i) => {
    const t = layerType(l);
    const below = i + 1 < nAll - 1 ? layerType(layers[i + 1]) : '';
    if (BIT_TYPES.has(t)) {
      const isBottom = bitLayers.length && bitLayers[bitLayers.length - 1] === l;
      return isBottom && stackHasCtb && designMsa > 20
        ? { min: 100, clause: '§9.2', what: 'bituminous bundle over a CTB above 20 msa', value: bitMin, bundle: true } : null;
    }
    if (t === 'CRL' || (AUTO_E_TYPES.has(t) && below === 'CTB')) return { min: 100, clause: '§8.3', what: 'crack-relief layer' };
    if (t === 'WMM' || t === 'WBM') return { min: 150, clause: '§8.1', what: 'unbound granular base' };
    if (t === 'GSB') return { min: 100, clause: '§7.2.2', what: 'granular sub-base' };
    if (t === 'CTB') return { min: 100, clause: '§8.2.1', what: 'cement treated base' };
    if (t === 'RAP') return { min: 100, clause: '§8.4', what: 'stabilised RAP base' };
    if (t === 'CTSB') return { min: 200, clause: '§7.3.1', what: 'cement treated sub-base (recommended)', advisory: true };
    return null;
  };
  const ircMinChip = (l, i) => {
    const m = ircMinOf(l, i);
    if (!m) return <span className="text-[10px] text-[var(--text-muted)]">—</span>;
    const lo = m.bundle ? m.value : (l.is_fixed ? Number(l.fixed_h) : Number(l.min_h));
    const hi = m.bundle ? m.value : (l.is_fixed ? Number(l.fixed_h) : Number(l.max_h));
    let tone = 'ok'; let note = '';
    if (hi < m.min) { tone = m.advisory ? 'info' : 'fail'; note = m.advisory ? ' — below recommended' : ' — below minimum'; }
    else if (lo < m.min) { tone = 'warn'; note = ' — the optimizer skips thinner lifts'; }
    return (
      <Chip tone={tone} title={`IRC:37-2018 ${m.clause}: ${m.what} ≥ ${m.min} mm${m.advisory ? '' : ' (always enforced by the optimizer)'}${note}`}>
        {m.bundle ? 'bundle ' : ''}≥ {m.min} · {m.clause}
      </Chip>
    );
  };

  /* ── SPLASH ── */
  if (!hasStarted) {
    return (
      <div className="min-h-[100svh] min-h-[100dvh] w-full flex items-center justify-center font-sans">
        <input type="file" ref={fileInputRef} onChange={handleImport} accept=".json" className="hidden"/>
        <div className="fp-fade-up fp-tile p-12 flex flex-col items-center max-w-sm w-full text-center"
             style={{ boxShadow: 'var(--elev-3)' }}>
          <div className="flex flex-col items-center mb-12">
            <div className="h-28 w-28 flex items-center justify-center mb-6">
              <img src={`${import.meta.env.BASE_URL}assets/logo_mark.png?v=3`} alt="IndoPave-37 Icon" className="h-24 w-auto object-contain" />
            </div>
            <h1 className="text-4xl font-black tracking-tight uppercase text-[var(--text-bold)]">IndoPave-37</h1>
            <p className="text-[11px] text-[var(--text-muted)] mt-1.5 tracking-wide font-medium">Mechanistic pavement design · IRC:37-2018</p>
          </div>
          <div className="flex w-full gap-3">
            <button onClick={()=>setHasStarted(true)} className="fp-btn-grad flex-1 font-bold py-3 rounded-xl text-sm flex items-center justify-center gap-1.5"><Plus size={18}/> New Project</button>
            <button onClick={()=>fileInputRef.current?.click()} className="flex-1 bg-white hover:bg-orange-50 hover:border-orange-300 text-slate-700 font-bold py-3 rounded-xl text-sm border border-slate-300 flex items-center justify-center gap-1.5 transition-all shadow-sm hover:shadow-md active:scale-95"><Upload size={18}/> Import</button>
          </div>
          <div className="mt-6 pt-4 border-t border-slate-200 w-full text-[10px] text-slate-400">
            <p className="font-semibold text-slate-500">Vikramaditya Shah Bundela</p>
            <p className="mt-0.5">Verify designs per IRC:37 before construction.</p>
          </div>
        </div>
      </div>
    );
  }

  /* ── MAIN DASHBOARD ── */
  const menuItem = "w-full text-left px-3 py-1.5 text-[11px] text-[var(--text-main)] hover:bg-[var(--surface-sunken)] hover:text-[var(--text-bold)] flex items-center gap-2 select-none no-underline";
  const menuPanel = "absolute right-0 mt-1 w-72 bg-[var(--surface-panel)] border border-[var(--hairline)] rounded-lg shadow-xl z-[60] py-1.5 max-h-[70vh] overflow-y-auto fp-fade-up";
  const menuHead = "px-3 py-1 text-[9.5px] uppercase tracking-wider text-[var(--text-muted)] font-bold";
  const usesCases = (onPick) => DEMO_CASES.map((c, i) => (
    <button key={i} type="button" onClick={() => onPick(c)} className={menuItem}>
      <ArrowRight size={10} className="text-[var(--accent)] flex-none" aria-hidden="true" />
      <span className="truncate">{c.name}</span>
    </button>
  ));
  const numIn = (extra) => cn(inp, "w-full min-w-0 py-0.5 fp-num", extra);

  return (
    <div className="min-h-[100svh] min-h-[100dvh] w-full text-[var(--text-main)] font-sans flex flex-col">

      {/* APP BAR — identity, live design basis, run actions, project menu */}
      <header className="sticky top-0 z-30 flex-none flex items-center gap-3 fp-glass-bar px-3 h-11">
        <div className="flex items-center gap-2 min-w-0">
          <img src={`${import.meta.env.BASE_URL}assets/logo_mark.png?v=3`} alt="" className="h-6 w-auto object-contain" />
          <h1 className="m-0 text-[15px] font-extrabold tracking-tight text-[var(--text-bold)] whitespace-nowrap">IndoPave-37</h1>
          <span
            className="hidden sm:inline text-[10px] text-[var(--text-muted)] cursor-help whitespace-nowrap"
            onDoubleClick={() => setDebugMode(!debugMode)}
            title="Double-click for debug mode"
          >
            IRC:37-2018 · v1.1
          </span>
        </div>

        {/* Live basis — the numbers every check is made against */}
        <div className="hidden lg:flex items-center gap-1.5 min-w-0 overflow-hidden">
          <Chip tone="info" title="Cumulative design traffic, IRC:37-2018 Eq. 4.5/4.6">
            <FlashValue value={designMsa.toFixed(1)} className="fp-num">{designMsa.toFixed(1)}</FlashValue>&nbsp;msa
          </Chip>
          <Chip tone="muted" title="Reliability per IRC:37-2018 §3.7">R{reliabilityPercent}</Chip>
          <Chip tone="muted" title="Subgrade CBR and resilient modulus (Eq. 6.1/6.2)">CBR {subgradeCbr}% · {mrsNow.toFixed(1)} MPa</Chip>
          {longLife && <Chip tone="ok" title="Long-life pavement checks on (IRC:37-2018 §10)">Long-life</Chip>}
          {getSolverMode() !== 'backend' && <Chip tone="muted" title="The solver runs in this browser (Pyodide)">In-browser solver</Chip>}
        </div>

        <div className="ml-auto flex items-center gap-1.5">
          <input type="file" ref={fileInputRef} onChange={handleImport} accept=".json" className="hidden"/>
          <button type="button" onClick={() => doSingleRun()} disabled={isSolving}
            title="Analyse the trial section at the analysis points (Ctrl+Enter)" aria-label="Evaluate"
            className="fp-tbtn">
            {isSolving && !optimizationMode ? <Loader2 size={12} className="animate-spin"/> : <Play size={12}/>}
            <span className="hidden sm:inline">Evaluate</span>
          </button>
          <button type="button" onClick={doOptimize} disabled={isSolving}
            title="Search constructable thicknesses for the IRC-adequate archetypes (Ctrl+Shift+Enter)" aria-label="Optimize"
            className="fp-btn-grad h-[26px] px-3 rounded-md text-[11px] font-bold flex items-center gap-1.5 select-none">
            {isSolving && optimizationMode ? <Loader2 size={12} className="animate-spin"/> : <ArrowRight size={12}/>}
            <span className="hidden sm:inline">Optimize</span>
          </button>

          <span className="hidden md:block w-px h-5 bg-[var(--hairline)] mx-0.5" aria-hidden="true" />

          <div className="hidden md:flex items-center gap-1">
            <div className="relative" data-menu>
              <button type="button" className="fp-tbtn" aria-expanded={showDemos} aria-haspopup="menu"
                onClick={() => { setShowDemos(v => !v); setShowMoreMenu(false); }}>
                <Database size={12}/> Use cases <ChevronDown size={11} aria-hidden="true"/>
              </button>
              {showDemos && (
                <div className={menuPanel} role="menu">
                  <div className={menuHead}>IRC-consistent scenarios</div>
                  {usesCases((c) => { handleApplyDemo(c); setShowDemos(false); })}
                </div>
              )}
            </div>
            <button type="button" className="fp-tbtn" onClick={() => fileInputRef.current?.click()} title="Open a project file (.json)">
              <Upload size={12}/> Import
            </button>
            <button type="button" className="fp-tbtn" onClick={handleExport} title="Save the project as a .json file">
              <Download size={12}/> Export
            </button>
            <button type="button" className="fp-tbtn" onClick={handlePdfExport}
              disabled={!optimizedDesigns || optimizedDesigns.length === 0}
              title={optimizedDesigns?.length ? 'Download the PDF design report' : 'Run Optimize first to generate a report'}>
              <FileText size={12}/> PDF
            </button>
            <button type="button" className="fp-tbtn" onClick={() => setShowAdvanced(true)} title="Reserve meter, sensitivity, Monte Carlo, 3D strain bulbs, corridor">
              <Zap size={12}/> Advanced
            </button>
            <button type="button" className="fp-tbtn" onClick={() => setShowInstructions(true)} title="Usage guide">
              <Info size={12}/> Help
            </button>
            <a className="fp-tbtn" href="https://law.resource.org/pub/in/bis/irc/irc.gov.in.037.2019.pdf"
               target="_blank" rel="noopener noreferrer" title="IRC:37 guideline (PDF)">
              <Book size={12}/> IRC:37
            </a>
          </div>
          <button type="button" className="fp-tbtn w-[26px] justify-center px-0"
            onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            title={theme === 'dark' ? 'Slate Engineering (light)' : 'Antigravity (dark)'}>
            {theme === 'dark' ? <Sun size={13}/> : <Moon size={13}/>}
          </button>
          <button type="button" className="fp-tbtn hidden md:inline-flex text-[var(--fail)]" onClick={handleReset} title="Clear the project (offers a JSON export first)">
            <RotateCcw size={12}/> Reset
          </button>

          {/* Narrow screens: one menu */}
          <div className="relative md:hidden" data-menu>
            <button type="button" className="fp-tbtn w-[26px] justify-center px-0" aria-label="More actions"
              aria-expanded={showMoreMenu} onClick={() => { setShowMoreMenu(v => !v); setShowDemos(false); }}>
              <MoreHorizontal size={14} />
            </button>
            {showMoreMenu && (
              <div className={menuPanel} role="menu">
                <div className={menuHead}>Project</div>
                <button type="button" className={menuItem} onClick={() => { fileInputRef.current?.click(); setShowMoreMenu(false); }}><Upload size={11}/> Import</button>
                <button type="button" className={menuItem} onClick={() => { handleExport(); setShowMoreMenu(false); }}><Download size={11}/> Export</button>
                <button type="button" className={menuItem} disabled={!optimizedDesigns?.length} onClick={() => { handlePdfExport(); setShowMoreMenu(false); }}><FileText size={11}/> PDF report</button>
                <button type="button" className={menuItem} onClick={() => { setShowAdvanced(true); setShowMoreMenu(false); }}><Zap size={11}/> Advanced</button>
                <button type="button" className={menuItem} onClick={() => { setShowInstructions(true); setShowMoreMenu(false); }}><Info size={11}/> Help</button>
                <a className={menuItem} href="https://law.resource.org/pub/in/bis/irc/irc.gov.in.037.2019.pdf" target="_blank" rel="noopener noreferrer" onClick={() => setShowMoreMenu(false)}><Book size={11}/> IRC:37</a>
                <button type="button" className={cn(menuItem, 'text-[var(--fail)]')} onClick={() => { setShowMoreMenu(false); handleReset(); }}><RotateCcw size={11}/> Reset</button>
                <div className={cn(menuHead, 'border-t border-[var(--hairline)] mt-1 pt-1.5')}>Use cases</div>
                {usesCases((c) => { handleApplyDemo(c); setShowMoreMenu(false); })}
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Auto-save restore notice — the pre-filled values are the user's own
          last session, not arbitrary defaults; say so once, dismissibly. */}
      {restoredNotice && (
        <div className="px-2 pt-2">
          <Notice tone="info" onDismiss={() => setRestoredNotice(false)}>
            <b>Session restored</b> — these inputs and results are your last session, auto-saved in this
            browser. Use <b>Reset</b> for a fresh project (it offers a JSON export first) or <b>Export</b> to file this one.
          </Notice>
        </div>
      )}

      {/* ═══ BENTO WORKSPACE ═══ */}
      <main
        className="fp-bento flex-1 grid-cols-1 md:grid-cols-2 xl:[grid-template-columns:repeat(3,minmax(0,1fr))_var(--section-w)] grid-flow-row-dense items-start"
        style={{ '--section-w': `${sectionW}px` }}
      >

        {/* ── Layer structure ── */}
        <Tile
          id="tile-layers" title="Layer structure" icon={Layers}
          className="md:col-span-2 xl:col-span-3"
          bodyClassName="p-0"
          actions={<>
            <Chip tone="muted" title="Total crust (Evaluate thickness: fixed, else minimum) and bituminous bundle">
              <span className="fp-num">{crustMin.toFixed(0)}{crustMax !== crustMin ? `–${crustMax.toFixed(0)}` : ''}</span>&nbsp;mm crust
              {bitLayers.length > 0 && <> · <span className="fp-num">{bitMin.toFixed(0)}</span>&nbsp;mm bit.</>}
            </Chip>
            {stackHasCtb && (
              <Toggle id="sami" checked={hasSami} onChange={setHasSami} label="SAMI over CTB"
                title="IRC:37-2018 §8.3: a stress-absorbing membrane interlayer as the crack-relief treatment. It is not a structural layer, so the bituminous layer sits directly on the CTB in the analysis. Without it, an aggregate crack-relief layer (100 mm WMM/CRL) must sit above the CTB." />
            )}
            <label className="text-[10px] text-[var(--text-muted)]" htmlFor="numLayers">Layers</label>
            <select id="numLayers" value={numLayers} onChange={e=>setNumLayers(parseInt(e.target.value))}
              className={cn(inp, 'w-12 font-bold cursor-pointer py-0')}>
              {[2,3,4,5,6,7,8,9,10].map(n=><option key={n} value={n}>{n}</option>)}
            </select>
          </>}
        >
          <div className="overflow-x-auto">
          <table className="fp-rt text-[11px] border-collapse" style={{ width: layerRT.total }}>
            <colgroup>{layerRT.cols.map((w,k)=><col key={k} style={{width:w}}/>)}</colgroup>
            <thead>
              <tr className="text-[10px] text-[var(--text-muted)] font-semibold border-b border-[var(--hairline)]">
                <th className="relative text-left py-1.5 px-2">Layer<ColGrip rt={layerRT} i={0}/></th>
                <th className="relative text-left py-1.5 px-1.5">Material<ColGrip rt={layerRT} i={1}/></th>
                <th className="relative text-center py-1.5 px-1">Mode<ColGrip rt={layerRT} i={2}/></th>
                <th className="relative text-left py-1.5 px-1.5">E (MPa)<ColGrip rt={layerRT} i={3}/></th>
                <th className="relative text-left py-1.5 px-1.5">ν<ColGrip rt={layerRT} i={4}/></th>
                <th className="relative text-left py-1.5 px-1.5">Thickness (mm)<ColGrip rt={layerRT} i={5}/></th>
                <th className="relative text-left py-1.5 px-1.5">IRC minimum<ColGrip rt={layerRT} i={6}/></th>
              </tr>
            </thead>
            <tbody>
              {layers.map((l,i)=>{
                const sub = i===layers.length-1;
                const hasGeogrid = !sub && !!l.geogrid && l.geogrid !== 'none';
                const t = layerType(l);
                const isBit = BIT_TYPES.has(t);
                const canAuto = !sub && (AUTO_E_TYPES.has(t) || isBit);
                const analysedE = analysisLayers[i]?.E;
                const bundleNote = !sub && isBit && Number(analysedE) !== Number(l.E);
                return (
                  <tr key={i}
                    className={cn("border-b border-[var(--hairline)] transition-colors", hoverLayer === i ? "bg-[var(--accent-soft)]" : "hover:bg-[var(--surface-sunken)]")}
                    style={layerRT.rowH[i]?{height:layerRT.rowH[i]}:undefined}
                    onMouseEnter={() => setHoverLayer(i)} onMouseLeave={() => setHoverLayer(null)}>
                    {/* Layer — positional identity, colour-linked to the cross-section */}
                    <td className="relative py-1 px-2 font-semibold text-[var(--text-main)] align-top whitespace-nowrap">
                      <span className="inline-block w-2.5 h-2.5 rounded-sm mr-1.5 align-[-1px] border border-[var(--hairline-strong)]" style={{ background: getLayerColor(l, i, sub) }} aria-hidden="true" />
                      {sub ? 'Subgrade' : `Layer ${i+1}`}
                      <RowGrip rt={layerRT} rowKey={i} getHeight={()=>layerRT.rowH[i]||0}/>
                    </td>
                    {/* Material — optional classification */}
                    <td className="py-1 px-1.5 align-top">
                      {!sub ? (
                        <>
                          <select
                            value={t}
                            aria-label={`Layer ${i+1} material`}
                            onChange={e=>{
                              const v = e.target.value;
                              setLayers(prev => prev.map((layer, j) => {
                                if (j !== i) return layer;
                                const updates = { ...layer, type: v };
                                // Auto-fill E and ν only when the current values
                                // match the *previous* material's defaults (meaning
                                // user hasn't customised them) or when switching
                                // from "— none —".  This keeps auto-fill optional.
                                if (v && MATERIAL_DATABASE[v]) {
                                  const mat = MATERIAL_DATABASE[v];
                                  const prevType = layerType(layer);
                                  const prevMat = prevType && MATERIAL_DATABASE[prevType];
                                  const ePristine = !prevMat || layer.E === prevMat.default_E;
                                  const nuPristine = !prevMat || layer.nu === prevMat.default_nu;
                                  if (ePristine) updates.E = mat.default_E;
                                  if (nuPristine) updates.nu = mat.default_nu;
                                }
                                if (!GRANULAR_LAYER_TYPES.has(v)) updates.geogrid = null;
                                // Auto modulus: Eq. 7.1 (unbound granular) or Table 9.2 (bituminous).
                                if (!AUTO_E_TYPES.has(v) && !BIT_TYPES.has(v)) updates.auto_E = false;
                                return updates;
                              }));
                            }}
                            title="Select material — auto-fills E and ν from IRC:37-2018 (optional, won't overwrite custom values)"
                            className={cn(inp, "w-full font-semibold cursor-pointer font-sans")}>
                            <option value="">— none —</option>
                            {LAYER_TYPE_OPTIONS.map(tt => {
                              const m = MATERIAL_DATABASE[tt];
                              return <option key={tt} value={tt}>{m.name} ({tt})</option>;
                            })}
                          </select>
                          {GRANULAR_LAYER_TYPES.has(t) && (
                            <select
                              value={l.geogrid || 'none'}
                              aria-label={`Layer ${i+1} geogrid`}
                              onChange={e=>updateLayer(i,'geogrid', e.target.value==='none'?null:e.target.value)}
                              title="Geosynthetic reinforcement (IRC:SP:59 / MIF) — uplifts granular modulus to trim thickness"
                              className={cn(
                                "mt-1 border rounded-md px-1.5 py-0.5 text-[9.5px] font-bold outline-none cursor-pointer w-full transition-colors",
                                l.geogrid ? "text-emerald-700 bg-emerald-50 border-emerald-300" : "text-slate-400 bg-slate-50 border-slate-200 hover:border-emerald-300"
                              )}>
                              {GEOGRID_OPTIONS.map(g=><option key={g.id} value={g.id}>{g.id==='none'?'⊘ no geogrid':`▦ ${g.label}`}</option>)}
                            </select>
                          )}
                        </>
                      ) : (
                        <span className="text-[10px] text-[var(--text-muted)]">From CBR {subgradeCbr}% (Eq. 6.{Number(subgradeCbr) <= 5 ? 1 : 2})</span>
                      )}
                    </td>
                    <td className="py-1 px-1 text-center align-top">
                      {!sub ? (
                        <button type="button" onClick={() => {
                          const nextFixed = !l.is_fixed;
                          setLayers(prev => prev.map((layer, j) => {
                            if (j !== i) return layer;
                            const updates = { ...layer, is_fixed: nextFixed };
                            if (!nextFixed) {
                              const type = layerType(layer) || layer.type || '';
                              if (updates.min_h === undefined || updates.min_h === null || updates.min_h === 0) {
                                updates.min_h = type === 'BC' ? 30 :
                                                type === 'DBM' ? 50 : 150;
                              }
                              if (updates.max_h === undefined || updates.max_h === null || updates.max_h === 0) {
                                updates.max_h = type === 'BC' ? 80 :
                                                type === 'DBM' ? 250 : 300;
                              }
                            }
                            return updates;
                          }));
                        }}
                          aria-pressed={!l.is_fixed}
                          title={l.is_fixed ? 'Fixed thickness — click to let the optimizer vary it within a range' : 'Optimized within min–max — click to fix it'}
                          className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded border min-w-[40px]",
                            l.is_fixed?"text-teal-700 bg-teal-50 border-teal-200":"text-orange-700 bg-orange-50 border-orange-200")}>
                          {l.is_fixed?'Fixed':'Opt'}
                        </button>
                      ):<span className="text-[10px] text-[var(--text-muted)]">∞</span>}
                    </td>
                    <td className="py-1 px-1 align-top">
                      <input
                        type="number"
                        value={l.E}
                        aria-label={sub ? 'Subgrade modulus' : `Layer ${i+1} modulus`}
                        onChange={e=>updateLayer(i,'E',Number(e.target.value))}
                        disabled={sub || !!l.auto_E}
                        title={sub ? "Determined by the subgrade CBR (Load & subgrade tile)"
                          : (l.auto_E && isBit) ? `Auto — IRC:37-2018 Table 9.2, ${binderGrade} at ${temperature} °C${t === 'BM' ? ' (BM: fixed 35 °C value)' : ''}`
                          : l.auto_E ? "Auto — derived from IRC:37-2018 Eq. 7.1 (0.2·h^0.45·E_support); the optimizer re-derives it for every candidate thickness"
                            + (hasGeogrid ? ". Shown value includes the SP:59 geogrid MIF." : "")
                          : hasGeogrid ? "Pinned E on a geogrid layer is the unreinforced modulus; the SP:59 MIF is applied on top."
                          : isBit ? "Pinned (tested) modulus. IRC §9.2: the design value is the smaller of the tested value and Table 9.2."
                          : ""}
                        className={numIn((sub || l.auto_E) && "bg-gray-100 text-gray-500 cursor-not-allowed font-medium")}
                      />
                      {!sub && !l.auto_E && hasGeogrid && (
                        <div className="mt-0.5 text-[8.5px] leading-tight text-emerald-700"
                             title="Pinned E on a geogrid layer is the unreinforced modulus; the SP:59 MIF is applied on top.">
                          unreinforced E · MIF on top
                        </div>
                      )}
                      {bundleNote && (
                        <div className="mt-0.5 text-[8.5px] leading-tight text-[var(--info)] fp-num"
                             title="IRC:37-2018 §9.2: all bituminous layers are analysed as one layer with the modulus of the bottom mix.">
                          analysed at {Number(analysedE).toFixed(0)} (bottom mix)
                        </div>
                      )}
                      {canAuto && (
                        <label
                          className="mt-0.5 flex items-center gap-1 cursor-pointer select-none"
                          title={isBit
                            ? "Auto: take E from IRC:37-2018 Table 9.2 for the binder grade and pavement temperature (Bituminous mix tile). Untick to pin a tested modulus."
                            : "Auto: derive this granular modulus from IRC:37-2018 Eq. 7.1 (and the §7.2.3 composite rule). Recommended — a pinned E stays constant while the optimizer varies the thickness, which deviates from IRC."}
                        >
                          <input
                            type="checkbox"
                            checked={!!l.auto_E}
                            onChange={e=>{
                              const checked = e.target.checked;
                              setLayers(prev => prev.map((layer, j) => {
                                if (j !== i) return layer;
                                const updates = { ...layer, auto_E: checked };
                                // Auto -> pinned on a geogrid layer: the auto E
                                // already includes the MIF (computeGranularAutoE),
                                // but a pinned E is the UNREINFORCED modulus that
                                // gets the MIF on top. Store E / MIF (same getMif
                                // call and subgrade MRS as computeGranularAutoE)
                                // so the MIF is not applied twice. Only when the
                                // shown E really is the engine's reinforced value:
                                // after a failed or still-pending computation it is
                                // not, and dividing would silently cancel the MIF.
                                const engine = engineGranularE.find(x => x.index === j);
                                const shownIsReinforced = !autoEError && engine && engine.auto
                                  && Math.abs(Number(layer.E) - engine.E) <= 0.05;
                                if (layer.auto_E && !checked && layer.geogrid && layer.geogrid !== 'none' && shownIsReinforced) {
                                  const mif = getMif(subgradeModulusFromCBR(subgradeCbr), layer.geogrid);
                                  const curE = Number(layer.E);
                                  if (mif > 0 && Number.isFinite(curE) && curE > 0) {
                                    updates.E = Math.round((curE / mif) * 10) / 10;
                                  }
                                }
                                return updates;
                              }));
                            }}
                            className="h-2.5 w-2.5 accent-orange-600 cursor-pointer"
                          />
                          <span className={cn("text-[9px] font-bold uppercase", l.auto_E ? "text-orange-700" : "text-slate-400")}>
                            {isBit ? 'Auto T. 9.2' : 'Auto Eq. 7.1'}
                          </span>
                        </label>
                      )}
                    </td>
                    <td className="py-1 px-1 align-top">
                      <input
                        type="number"
                        value={l.nu}
                        aria-label={sub ? 'Subgrade Poisson ratio' : `Layer ${i+1} Poisson ratio`}
                        onChange={e=>updateLayer(i,'nu',Number(e.target.value))}
                        step="0.01"
                        disabled={sub}
                        title={sub ? "Fixed to 0.35 for Subgrade" : ""}
                        className={numIn(sub && "bg-gray-100 text-gray-500 cursor-not-allowed font-medium")}
                      />
                    </td>
                    <td className="py-1 px-1.5 align-top">
                      {sub ? <span className="text-[var(--text-muted)] text-[11px]">∞ half-space</span>
                      : l.is_fixed ? <input type="number" aria-label={`Layer ${i+1} thickness`} value={l.fixed_h} onChange={e=>updateLayer(i,'fixed_h',Number(e.target.value))} className={numIn()}/>
                      : <div className="flex gap-1 items-center">
                          <input type="number" aria-label={`Layer ${i+1} minimum thickness`} value={l.min_h} onChange={e=>updateLayer(i,'min_h',Number(e.target.value))} className={numIn("flex-1")} placeholder="min"/>
                          <span className="text-[var(--text-muted)] text-xs">–</span>
                          <input type="number" aria-label={`Layer ${i+1} maximum thickness`} value={l.max_h} onChange={e=>updateLayer(i,'max_h',Number(e.target.value))} className={numIn("flex-1")} placeholder="max"/>
                        </div>}
                    </td>
                    <td className="py-1 px-1.5 align-top">{sub ? <span className="text-[10px] text-[var(--text-muted)]">—</span> : ircMinChip(l, i)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        </Tile>

        {/* ── Cross-section (resizable at xl from its left edge) ── */}
        <Tile
          id="tile-section" title="Cross-section" icon={Ruler}
          className="relative md:col-span-2 xl:col-span-1 xl:row-span-2 xl:self-stretch"
          bodyClassName="p-1.5 flex items-center justify-center min-h-[320px]"
          actions={<span className="text-[9.5px] text-[var(--text-muted)] fp-num">{wheelType === 'Dual' ? `dual · ${wheelSpacing} mm` : 'single wheel'}</span>}
        >
          <div
            onPointerDown={onPreviewDrag}
            className="hidden xl:block absolute -left-[7px] top-3 bottom-3 w-[10px] cursor-col-resize z-20 select-none touch-none group"
            title="Drag to resize"
            role="separator" aria-orientation="vertical" aria-label="Resize cross-section"
          >
            <span className="absolute left-[4px] top-1/2 -translate-y-1/2 h-10 w-[3px] rounded bg-[var(--hairline-strong)] group-hover:bg-[var(--accent)] group-active:bg-[var(--accent)] transition-colors" />
          </div>
          <PavementVisualizer
            layers={layers}
            points={points}
            wheelType={wheelType}
            wheelSpacing={wheelSpacing}
            load={load}
            pressure={pressure}
            highlight={hoverLayer}
            onHover={setHoverLayer}
          />
        </Tile>

        {/* ── Traffic & design basis ── */}
        <Tile id="tile-traffic" title="Traffic · design basis" icon={Truck}
          actions={<FlashValue value={designMsa.toFixed(1)} className="fp-num text-[11px] font-bold text-[var(--text-bold)] px-1 rounded">{designMsa.toFixed(1)} msa</FlashValue>}>
          <div className="flex flex-col gap-1">
            <Field label="Road" htmlFor="road" title="Road category (IRC:37-2018 §3.7 and Eq. 3.5): Expressway / NH / SH / urban roads use 90% reliability and CTB RF = 1 at any traffic.">
              <select id="road" value={roadCategory} onChange={e=>setRoadCategory(e.target.value)} className={cn(inp, "w-full min-w-0 py-0.5 cursor-pointer font-sans")}>
                {ROAD_CATEGORIES.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </Field>
            <Field label="Carriageway" htmlFor="cw" title="IRC:37-2018 §4.5.1 lateral distribution: sets the LDF. Divided carriageways take the CVPD of one direction (§4.6.1).">
              <select id="cw" value={carriageway} onChange={e => {
                const c = CARRIAGEWAYS.find(x => x.id === e.target.value);
                setCarriageway(e.target.value);
                if (c) setLdf(c.ldf);
              }} className={cn(inp, "w-full min-w-0 py-0.5 cursor-pointer font-sans")}>
                {CARRIAGEWAYS.map(c => <option key={c.id} value={c.id}>{c.label} — LDF {c.ldf}</option>)}
              </select>
            </Field>
            <Field label={cwNow.directional ? 'CVPD / dir.' : 'CVPD 2-way'} htmlFor="cvpd"
              title="Commercial vehicles per day at the last count (P in IRC Eq. 4.6). Directional volume for a divided carriageway, two-way volume otherwise (IRC:37-2018 §4.6.1); the LDF is applied to it.">
              <input id="cvpd" type="number" value={cvpd} onChange={e=>setCvpd(Number(e.target.value))} className={numIn()}/>
            </Field>
            <div className="grid grid-cols-2 gap-x-2 gap-y-1">
              <Field label="Growth %" htmlFor="grw" className="grid-cols-[52px_minmax(0,1fr)]" title="Annual traffic growth rate, % (IRC:37-2018 §4.2.3: at least 5%).">
                <input id="grw" type="number" step="0.5" min="-5" max="20" value={Math.round(growthRate*1000)/10} onChange={e=>setGrowthRate(Number(e.target.value)/100)} className={numIn(growthRate < 0.05 && 'border-amber-400')}/>
              </Field>
              <Field label="Yrs→open" htmlFor="yrs" className="grid-cols-[52px_minmax(0,1fr)]" title="Years from the traffic count to completion of construction (x in IRC:37-2018 Eq. 4.6, A = P(1+r)^x). 0 if the CVPD is already the opening-year traffic.">
                <input id="yrs" type="number" step="0.5" min="0" max="30" value={constructionYears} onChange={e=>setConstructionYears(Math.max(0, Number(e.target.value)))} className={numIn()}/>
              </Field>
              <Field label="Life (yr)" htmlFor="life" className="grid-cols-[52px_minmax(0,1fr)]" title={`Design period (IRC:37-2018 §4.3.1): ${recLife} years recommended for this road${recLife === 30 ? ' unless designed as a long-life pavement' : ''}.`}>
                <input id="life" type="number" step="1" min="1" max="40" value={designLife} onChange={e=>setDesignLife(Number(e.target.value))} className={numIn(designLife < recLife && !longLife && 'border-amber-400')}/>
              </Field>
              <Field label="LDF" htmlFor="ldf" className="grid-cols-[52px_minmax(0,1fr)]" title="Lane distribution factor (IRC:37-2018 §4.5.1); set by the carriageway type, editable.">
                <input id="ldf" type="number" step="0.05" min="0.05" max="1" value={ldf} onChange={e=>setLdf(Number(e.target.value))} className={numIn(ldfIsCustom && 'border-amber-400')}/>
              </Field>
            </div>
            <Field label="VDF" htmlFor="vdf" title="Vehicle damage factor — standard axles per commercial vehicle. From an axle-load survey (IRC:37-2018 §4.4); Table 4.2 gives indicative values when no survey exists.">
              <input id="vdf" type="number" step="0.1" min="0.1" max="12" value={vdf} onChange={e=>setVdf(Number(e.target.value))} className={numIn("w-16 flex-none")}/>
              <Seg label="Terrain" value={terrain} onChange={setTerrain}
                options={[{ id: 'plain', label: 'Plain', title: 'Rolling / plain terrain (Table 4.2)' }, { id: 'hilly', label: 'Hilly', title: 'Hilly terrain (Table 4.2)' }]} />
              <button type="button"
                className={cn("text-[10px] font-semibold px-1.5 h-[22px] rounded border transition-colors whitespace-nowrap",
                  Number(vdf) === vdfSuggest ? "border-[var(--hairline)] text-[var(--text-muted)]" : "border-orange-300 text-orange-700 hover:bg-orange-50")}
                onClick={() => setVdf(vdfSuggest)}
                title={`IRC:37-2018 Table 4.2 indicative VDF for ${Math.round(initialTwoWay)} initial two-way CVPD (${terrain})${cwNow.directional ? ', taking the two-way volume as twice the directional CVPD' : ''}. Use only without an axle-load survey (§4.4.6).`}>
                T 4.2: {vdfSuggest}
              </button>
            </Field>
            {(designLife < recLife && !longLife) && (
              <div className="text-[10px] text-[var(--warn)]">§4.3.1 recommends {recLife} years for this road{recLife === 30 ? ' (or a long-life design)' : ''}.</div>
            )}
          </div>
        </Tile>

        {/* ── Bituminous mix & climate (Table 9.2) ── */}
        <Tile id="tile-mix" title="Bituminous mix · climate" icon={Thermometer}
          actions={bundleE != null && <FlashValue value={bundleE} className="fp-num text-[11px] font-bold text-[var(--text-bold)] px-1 rounded">{Number(bundleE).toFixed(0)} MPa</FlashValue>}>
          <div className="flex flex-col gap-1.5">
            <Field label="Binder" title="Binder of the bottom (DBM/BM) mix — IRC:37-2018 Table 9.2 row. VG10 is for snow-bound locations (§9.1). Modified binders are not recommended for DBM (§9.2).">
              <Seg label="Binder grade" value={binderGrade} onChange={setBinderGrade}
                options={BINDER_GRADES.map(g => ({ id: g.id, label: g.id, title: g.label }))} />
            </Field>
            <Field label="Temp °C" htmlFor="temp" title="Average annual pavement temperature (IRC:37-2018 Table 9.2: 20–40 °C; about 35 °C in the plains of India).">
              <input id="temp-range" type="range" min="20" max="40" step="1" value={temperature}
                onChange={e => setTemperature(Number(e.target.value))} aria-label="Pavement temperature"
                className="flex-1 min-w-0 accent-orange-600 cursor-pointer" />
              <input id="temp" type="number" min="20" max="40" step="0.5" value={temperature}
                onChange={e => setTemperature(Math.min(40, Math.max(20, Number(e.target.value))))} className={numIn("w-14 flex-none")} />
            </Field>
            <div className="grid grid-cols-2 gap-x-2">
              <Field label="Va %" htmlFor="va" className="grid-cols-[40px_minmax(0,1fr)]" title="Air voids of the bottom bituminous mix (IRC:37-2018 §3.6.2 fatigue C-factor). Annex II uses 3%.">
                <input id="va" type="number" step="0.5" min="1" max="12" value={airVoids} onChange={e=>setAirVoids(Number(e.target.value))} className={numIn()}/>
              </Field>
              <Field label="Vbe %" htmlFor="vbe" className="grid-cols-[40px_minmax(0,1fr)]" title="Effective bitumen volume of the bottom bituminous mix (IRC:37-2018 §3.6.2). Annex II uses 11.5%.">
                <input id="vbe" type="number" step="0.5" min="5" max="20" value={bitumenVolume} onChange={e=>setBitumenVolume(Number(e.target.value))} className={numIn()}/>
              </Field>
            </div>
            <div className="grid grid-cols-3 gap-2 pt-1.5 border-t border-[var(--hairline)]">
              <Kpi label="Table 9.2" value={t92Now.toFixed(0)} unit="MPa" sub={`${binderGrade} · ${temperature} °C${bottomBitType === 'BM' ? ' · BM' : ''}`}
                   title="Indicative maximum resilient modulus of the bottom mix (IRC:37-2018 Table 9.2)." />
              <Kpi label="Bundle E" value={bundleE != null ? Number(bundleE).toFixed(0) : '—'} unit={bundleE != null ? 'MPa' : ''}
                   tone={bundleE != null && bundleE > t92Now + 0.5 ? 'warn' : undefined}
                   sub={bundleE == null ? 'no bituminous layer' : bundleE > t92Now + 0.5 ? 'above Table 9.2' : 'analysed (§9.2)'}
                   title="Modulus the whole bituminous bundle is analysed with: the bottom mix (IRC:37-2018 §9.2). It may not exceed Table 9.2." />
              <Kpi label="C factor" value={cFactor.toFixed(2)} sub="Eq. 3.3 / 3.4"
                   title="C = 10^(4.84 (Vbe/(Va+Vbe) − 0.69)), IRC:37-2018 §3.6.2." />
            </div>
          </div>
        </Tile>

        {/* ── Load & subgrade ── */}
        <Tile id="tile-load" title="Load · subgrade" icon={Gauge}
          actions={isStdAxle
            ? <Chip tone="ok" title="IRC:37-2018 §3.6.1 standard axle: 80 kN dual-wheel single axle — 20 kN per wheel, 0.56 MPa, 310 mm spacing">IRC standard axle</Chip>
            : <button type="button" className="fp-chip fp-chip-warn cursor-pointer" title="Restore the IRC:37-2018 standard axle (20 kN per wheel, 0.56 MPa, dual at 310 mm)"
                onClick={() => { setLoad(20000); setPressure(0.56); setWheelType('Dual'); setWheelSpacing(310); }}>Non-standard · reset</button>}>
          <div className="flex flex-col gap-1">
            <Field label="CBR %" htmlFor="cbr" title="Effective subgrade CBR (IRC:37-2018 §6.3); the resilient modulus follows Eq. 6.1 (≤ 5%) or Eq. 6.2.">
              <input id="cbr" type="number" step="0.5" value={subgradeCbr} onChange={e=>setSubgradeCbr(Number(e.target.value))} className={numIn("w-16 flex-none")}/>
              <span className="text-[10px] text-[var(--text-muted)] fp-num whitespace-nowrap">M<sub>RS</sub> <FlashValue value={mrsNow.toFixed(1)} className="font-semibold text-[var(--text-bold)] px-0.5 rounded">{mrsNow.toFixed(1)}</FlashValue> MPa</span>
            </Field>
            <Field label="Wheel" title="IRC:37-2018 §3.6.1 analyses a dual-wheel set; the optimizer always uses the dual set for the CTB spectrum.">
              <Seg label="Wheel type" value={wheelType} onChange={setWheelType}
                options={[{ id: 'Dual', label: 'Dual' }, { id: 'Single', label: 'Single' }]} />
            </Field>
            <Field label="Load (N)" htmlFor="load" title="Load per wheel (IRC standard: 20 000 N).">
              <input id="load" type="number" value={load} onChange={e=>setLoad(Number(e.target.value))} className={numIn()}/>
              <span className="text-[10px] text-[var(--text-muted)] fp-num whitespace-nowrap">{(Number(load)/1000).toFixed(1)} kN</span>
            </Field>
            <Field label="Tyre (MPa)" htmlFor="tyre" title="Contact pressure (IRC: 0.56 MPa; 0.80 MPa is used only for the CTB checks).">
              <input id="tyre" type="number" step="0.01" value={pressure} onChange={e=>setPressure(Number(e.target.value))} className={numIn()}/>
            </Field>
            <Field label="Spacing (mm)" htmlFor="sp" title="Centre-to-centre spacing of the dual wheels (IRC: 310 mm).">
              <input id="sp" type="number" step="1" value={wheelSpacing} disabled={wheelType !== 'Dual'} onChange={e=>setWheelSpacing(Number(e.target.value))} className={numIn(wheelType !== 'Dual' && 'opacity-50')} />
            </Field>
            {debugMode && (
              <Field label="Debug" className="text-[var(--fail)]">
                <input type="checkbox" checked={debugMode} onChange={e=>setDebugMode(e.target.checked)} className="cursor-pointer" />
              </Field>
            )}
          </div>
        </Tile>

        {/* ── Design limits (allowable strains for this traffic) ── */}
        <Tile id="tile-limits" title="Design limits" icon={ListChecks} className="md:col-span-2 xl:col-span-2"
          actions={<span className="text-[9.5px] text-[var(--text-muted)]">IRC:37-2018 §3.6 · §10</span>}>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-2.5">
            <Kpi label="Design traffic" value={designMsa.toFixed(1)} unit="msa"
                 sub={`${Math.round(Number(cvpd) * Math.pow(1 + Number(growthRate), Number(constructionYears) || 0)).toLocaleString('en-IN')} CVPD · LDF ${ldf} · VDF ${vdf}`}
                 title="N = 365 · A · LDF · VDF · ((1+r)^n − 1)/r, A = P(1+r)^x (IRC:37-2018 Eq. 4.5/4.6)" />
            <Kpi label="Reliability" value={`R${reliabilityPercent}`}
                 sub={`§3.7 · ${(ROAD_CATEGORIES.find(c => c.id === roadCategory) || {}).label || roadCategory}`}
                 title="90% for Expressway / NH / SH / urban roads at any traffic and for other roads at ≥ 20 msa; else 80% (IRC:37-2018 §3.7)" />
            <Kpi label={<>Allowable <span className="normal-case">εt</span></>} value={allowNow.epsT != null ? (allowNow.epsT * 1e6).toFixed(0) : '—'} unit={allowNow.epsT != null ? 'µε' : ''}
                 sub={bundleE != null ? `Eq. 3.${reliabilityPercent === 90 ? 4 : 3} · MRm ${Number(bundleE).toFixed(0)} MPa` : 'no bituminous layer'}
                 title="Bituminous tensile strain giving Nf = design traffic (IRC:37-2018 Eq. 3.3/3.4 solved for εt)." />
            <Kpi label={<>Allowable <span className="normal-case">εv</span></>} value={allowNow.epsV != null ? (allowNow.epsV * 1e6).toFixed(0) : '—'} unit={allowNow.epsV != null ? 'µε' : ''}
                 sub={`Eq. 3.${reliabilityPercent === 90 ? 2 : 1} · top of subgrade`}
                 title="Subgrade vertical strain giving NR = design traffic (IRC:37-2018 Eq. 3.1/3.2 solved for εv)." />
          </div>
          <div className={cn("mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-2 py-1.5",
                             longLife ? "border-[color-mix(in_oklab,var(--ok)_35%,transparent)] bg-[var(--ok-soft)]" : "border-[var(--hairline)] bg-[var(--surface-sunken)]")}>
            <Toggle id="longlife" checked={longLife} onChange={setLongLife}
              label={<span>Long-life pavement <span className="text-[var(--text-muted)]">(§10)</span></span>}
              title="IRC:37-2018 §10 / Annex II.6: also keep the bituminous tensile strain ≤ 80 µε (endurance limit at 35 °C) and the subgrade strain ≤ 200 µε. Recommended from 300 msa and for expressways (§4.3.1)." />
            <span className="text-[10.5px] fp-num text-[var(--text-main)]">εt ≤ {(LONG_LIFE_EPS_T * 1e6).toFixed(0)} µε · εv ≤ {(LONG_LIFE_EPS_V * 1e6).toFixed(0)} µε</span>
            {llRecommended && !longLife && <Chip tone="warn" title="IRC:37-2018 §4.3.1: corridors over 300 msa and expressways should preferably be designed as long-life pavements (else for at least 30 years).">Recommended here</Chip>}
            {longLife && temperature !== 35 && <Chip tone="info" title="IRC states the 80 µε endurance limit for 35 °C.">80 µε is the 35 °C value</Chip>}
          </div>
        </Tile>

        {/* ── Optimizer objectives & checks ── */}
        <Tile id="tile-objectives" title="Optimizer" icon={Settings}>
          <div className="flex flex-col gap-2">
            <div className="text-[9.5px] font-bold uppercase tracking-wide text-[var(--text-muted)]">Objectives</div>
            <div className="flex flex-col gap-1.5">
              <Toggle id="optByThk" checked disabled label="Thickness (Structural)" title="Always ranked: the thinnest IRC-adequate section." />
              <Toggle id="optByCost" checked={optimizeByCost} onChange={setOptimizeByCost} label="Cost (Economy)" title="Adds the cheapest adequate design, from the material unit rates." />
              <Toggle id="optByCo2" checked={optimizeByCo2} onChange={setOptimizeByCo2} label="Embodied CO₂ (Sustainable)" title="Adds the lowest-carbon adequate design." />
            </div>
            <div className="flex flex-wrap gap-1 pt-1.5 border-t border-[var(--hairline)]">
              <button type="button" className="fp-tbtn" aria-pressed={showRatesPanel} disabled={!optimizeByCost && !optimizeByCo2}
                onClick={() => setShowRatesPanel(v => !v)} title={optimizeByCost || optimizeByCo2 ? 'Edit material unit rates' : 'Enable Cost or CO₂ to edit rates'}>
                <IndianRupee size={12}/> Rates
              </button>
              <button type="button" className="fp-tbtn" aria-pressed={showCtbPanel}
                onClick={() => setShowCtbPanel(v => !v)} title="CTB axle-load spectrum for the IRC:37-2018 Eq. 3.6 cumulative damage check">
                <Activity size={12}/> CTB spectrum{useCtbSpectrum ? ' · on' : ''}
              </button>
            </div>
          </div>
        </Tile>

        {/* ── Analysis points (Evaluate) ── */}
        <Tile id="tile-points" title="Analysis points" icon={Crosshair}
          actions={<>
            <button type="button" className="fp-tbtn h-[22px]" onClick={placeIrcPoints}
              title="Place the IRC critical points for this stack: bottom of the bituminous layer and of a CTB (just above), top of the subgrade (just below); r = 0 and between the duals.">
              <Crosshair size={11}/> IRC points
            </button>
            <select value={numPoints} onChange={e=>setNumPoints(parseInt(e.target.value))} aria-label="Number of analysis points"
              className={cn(inp, 'w-11 py-0 font-bold cursor-pointer')}>
              {[1,2,3,4,5,6,7,8,9,10].map(n=><option key={n} value={n}>{n}</option>)}
            </select>
          </>}>
          <div className="overflow-x-auto">
          <table className="fp-rt text-[11px] border-collapse" style={{ width: pointsRT.total + 64 }}>
            <colgroup>{pointsRT.cols.map((w,k)=><col key={k} style={{width:w}}/>)}<col style={{ width: 64 }}/></colgroup>
            <thead>
              <tr className="text-[10px] text-[var(--text-muted)] font-semibold">
                <th className="relative text-left py-0.5">#<ColGrip rt={pointsRT} i={0}/></th>
                <th className="relative text-left py-0.5">z (mm)<ColGrip rt={pointsRT} i={1}/></th>
                <th className="relative text-left py-0.5">r (mm)<ColGrip rt={pointsRT} i={2}/></th>
                <th className="text-left py-0.5 pl-1">Role</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p,i)=>{
                const role = pointRoleOf(i);
                return (
                  <tr key={i} style={pointsRT.rowH[i]?{height:pointsRT.rowH[i]}:undefined}>
                    <td className="relative py-0.5 font-bold text-[var(--text-muted)] text-[10px] fp-num">P{i+1}<RowGrip rt={pointsRT} rowKey={i} getHeight={()=>pointsRT.rowH[i]||0}/></td>
                    <td className="py-0.5 pr-1"><input type="number" aria-label={`Point ${i+1} depth`} value={p.z} onChange={e=>updatePoint(i,'z',Number(e.target.value))} className={numIn("py-0")}/></td>
                    <td className="py-0.5"><input type="number" aria-label={`Point ${i+1} radius`} value={p.r} onChange={e=>updatePoint(i,'r',Number(e.target.value))} className={numIn("py-0")}/></td>
                    <td className="py-0.5 pl-1">
                      {role === 'fatigue' ? <Chip tone="info" title="Bottom of the bituminous layer: fatigue strain">εt</Chip>
                        : role === 'rutting' ? <Chip tone="info" title="Top of the subgrade: rutting strain">εv</Chip>
                        : role === 'ctb' ? <Chip tone="info" title="Bottom of the CTB: CTB fatigue (checked by Optimize at 0.80 MPa)">CTB</Chip>
                        : <Chip tone="muted" title="Not at a critical interface of the current stack (±5 mm)">—</Chip>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
          {!pointRoles.ok && (
            <div className="mt-1.5 text-[10px] text-[var(--warn)]">
              Points miss the critical interfaces of this stack — use <b>IRC points</b>.
            </div>
          )}
        </Tile>

        {/* ── Material rates (cost / CO₂ objectives) ── */}
        {(optimizeByCost || optimizeByCo2) && showRatesPanel && (
          <Tile id="tile-rates" title="Material rates" icon={IndianRupee} className="md:col-span-1 xl:col-span-2 fp-fade-up"
            actions={<span className="text-[9.5px] text-[var(--text-muted)]">blank = IRC/MoRTH default</span>}>
            <div className="grid grid-cols-[48px_repeat(2,minmax(0,1fr))] gap-x-2 gap-y-1 items-center">
              <span />
              <span className="text-[9.5px] font-semibold text-[var(--text-muted)]">{optimizeByCost ? '₹ / m³' : ''}</span>
              <span className="text-[9.5px] font-semibold text-[var(--text-muted)]">{optimizeByCo2 ? 'kg CO₂ / m³' : ''}</span>
              {Object.keys(materialRates).map((m) => (
                <React.Fragment key={m}>
                  <span className="text-[11px] font-bold text-[var(--text-main)]">{m}</span>
                  {optimizeByCost ? <input type="number" step="1" aria-label={`${m} cost per cubic metre`} value={materialRates[m].cost_per_cum || ''} placeholder={DEFAULT_MATERIAL_RATES[m] ? `${DEFAULT_MATERIAL_RATES[m].cost_per_cum}` : 'default'} onChange={e=>updateMaterialRate(m,'cost_per_cum', Number(e.target.value))} className={numIn()} title="Blank = use the built-in IRC/MoRTH default rate"/> : <span />}
                  {optimizeByCo2 ? <input type="number" step="1" aria-label={`${m} CO2 per cubic metre`} value={materialRates[m].co2_per_cum || ''} placeholder={DEFAULT_MATERIAL_RATES[m] ? `${DEFAULT_MATERIAL_RATES[m].co2_per_cum}` : 'default'} onChange={e=>updateMaterialRate(m,'co2_per_cum', Number(e.target.value))} className={numIn()} title="Blank = use the built-in IRC/MoRTH default rate"/> : <span />}
                </React.Fragment>
              ))}
            </div>
          </Tile>
        )}

        {/* ── CTB axle spectrum ── */}
        {showCtbPanel && (
          <Tile id="tile-ctb" title="CTB axle-load spectrum" icon={Activity} className="md:col-span-1 xl:col-span-2 fp-fade-up"
            actions={<>
              <Toggle id="ctbOn" checked={useCtbSpectrum} label="Use"
                onChange={(enabled) => {
                  setUseCtbSpectrum(enabled);
                  if (enabled && !ctbSpectrumText.trim()) setCtbSpectrumText(DEFAULT_CTB_AXLE_SPECTRUM_TEXT);
                }} title="Run the stress-ratio cumulative damage check (IRC:37-2018 Eq. 3.6/3.7) in addition to Eq. 3.5" />
              <Toggle id="ctbPerClass" checked={ctbPerClassBridgeRecompute} onChange={setCtbPerClassBridgeRecompute} label="All designs"
                title="Spectrum-check every design, not only those that pass the other criteria (slower)" />
            </>}>
            <div className="flex flex-col gap-1">
              <div className="flex items-start justify-between gap-2">
                <p className="m-0 text-[10px] text-[var(--text-muted)] leading-snug">
                  Axle groups for the CTB fatigue damage check; tandems and tridems are split into single axles
                  (Annex II.4). Without a spectrum only the strain criterion (Eq. 3.5) is applied.
                </p>
                <button type="button" className="fp-tbtn h-[22px] flex-none"
                  onClick={() => { setUseCtbSpectrum(true); setCtbSpectrumText(DEFAULT_CTB_AXLE_SPECTRUM_TEXT); }}>
                  Load example
                </button>
              </div>
              <textarea
                value={ctbSpectrumText}
                onChange={e => setCtbSpectrumText(e.target.value)}
                rows={6}
                spellCheck={false}
                aria-label="CTB axle-load spectrum (JSON)"
                placeholder={DEFAULT_CTB_AXLE_SPECTRUM_TEXT}
                className={cn(inp, "w-full min-h-24 resize-y text-[10px] leading-4")}
              />
              <p className="m-0 text-[9.5px] text-[var(--text-muted)]">
                JSON array of <code>{'{ axle_type, load_kn, expected_repetitions }'}</code>.
              </p>
            </div>
          </Tile>
        )}

        {/* ═══ RESULTS ═══ */}
        <Tile id="tile-results" title="Results" icon={Table2} className="md:col-span-2 xl:col-span-4"
          actions={<>
            {optimizationMode && optimizedDesigns && <Chip tone={optimizedDesigns.length ? 'ok' : 'fail'}>{optimizedDesigns.length} IRC-adequate</Chip>}
            {!optimizationMode && results && <Chip tone="muted"><span className="fp-num">{results.length}</span>&nbsp;point(s) · Evaluate</Chip>}
            {evalVerdict?.stale && <Chip tone="warn" title="An input changed after this evaluation — run Evaluate again">Inputs changed</Chip>}
            <button type="button" className="fp-tbtn h-[22px]" onClick={handlePdfExport} disabled={!optimizedDesigns?.length}
              title={optimizedDesigns?.length ? 'Download the PDF design report' : 'Run Optimize first'}>
              <FileText size={11}/> PDF
            </button>
          </>}>
          <div className="flex flex-col gap-2">
            {error && <Notice tone="fail" title="Run failed">{error}</Notice>}
            {autoEError && <Notice tone="warn" title="Layer moduli">{autoEError}</Notice>}

            {isSolving ? (
              <div className="flex flex-col gap-2" aria-live="polite">
                <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
                  <Loader2 size={14} className="animate-spin text-[var(--accent)]"/>
                  <span>{optimizationMode ? 'Searching constructable thicknesses and checking IRC criteria…' : (solverStatus || 'Computing stresses and strains…')}</span>
                  {solverStatus && !optimizationMode && <span className="text-[10px]">(the in-browser solver loads once per session)</span>}
                </div>
                <div className={cn("grid gap-2", optimizationMode ? "grid-cols-1 md:grid-cols-2 xl:grid-cols-4" : "grid-cols-1")}>
                  {(optimizationMode ? [0, 1, 2, 3] : [0]).map(k => (
                    <div key={k} className="fp-skeleton" style={{ height: optimizationMode ? 260 : 120, animationDelay: `${k * 120}ms` }} />
                  ))}
                </div>
              </div>
            ) : optimizationMode && optimizedDesigns ? (
              <>
                {sp72Info && sp72Info.is_low_volume && (
                  <Notice tone="warn" title={`IRC:SP:72 low-volume road — ${sp72Info.traffic_category || '—'}`}>
                    {Number(sp72Info.esal).toLocaleString('en-IN')} ESAL (~{sp72Info.msa} msa) · subgrade {sp72Info.subgrade_class} ({sp72Info.subgrade_class_name})
                    {sp72Info.surfacing_hint && <> · surfacing: {sp72Info.surfacing_hint}</>}
                    {sp72Info.advisory && sp72Info.advisory.length > 0 && (
                      <ul className="mt-0.5 mb-0 list-disc ml-4 space-y-0.5 text-[10.5px]">
                        {sp72Info.advisory.map((a, ai) => <li key={ai}>{a}</li>)}
                      </ul>
                    )}
                  </Notice>
                )}
                {reinforcementInfo && (
                  <Notice tone="ok" title="Geosynthetic reinforcement (MIF, IRC:SP:59)">
                    {reinforcementInfo.map((r,ri)=>(
                      <span key={ri} className="mr-3 fp-num">{r.layer} + {r.geogrid} → modulus ×{r.mif}</span>
                    ))}
                  </Notice>
                )}
                {optimizeWarnings && optimizeWarnings.length > 0 && (
                  <details className="group rounded-md border border-[var(--hairline)] bg-[var(--surface-sunken)]" open={optimizedDesigns.length === 0}>
                    <summary className="cursor-pointer select-none list-none flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-semibold text-[var(--text-main)]">
                      <ChevronDown size={12} className="transition-transform group-open:rotate-180" aria-hidden="true"/>
                      Engine advisories <span className="fp-num text-[var(--text-muted)]">({optimizeWarnings.length})</span>
                    </summary>
                    <ul className="m-0 px-2.5 pb-2 pl-7 list-disc space-y-0.5 text-[10.5px] text-[var(--text-main)]">
                      {optimizeWarnings.map((w, wi) => <li key={wi}>{w}</li>)}
                    </ul>
                  </details>
                )}
                {optimizedDesigns.length > 0 ? (
                  <div className="grid gap-2 grid-cols-1 md:grid-cols-2 xl:grid-cols-4 items-start">
                    {optimizedDesigns.slice(0, 12).map((d, i) => (
                      <DesignCard key={i} d={d} index={i} colorOf={(l, j) => getLayerColor(l, j, false)}
                        airVoids={airVoids} bitumenVolume={bitumenVolume} onApply={applyDesign}
                        style={{ animationDelay: `${Math.min(i, 8) * 60}ms` }} />
                    ))}
                    <DesignCompare
                      designs={optimizedDesigns.slice(0, 12)}
                      className={cn(
                        { 1: 'xl:col-span-3', 2: 'xl:col-span-2', 3: 'xl:col-span-1' }[Math.min(optimizedDesigns.length, 12) % 4] || 'xl:col-span-4',
                        optimizedDesigns.length % 2 === 1 ? 'md:col-span-1' : 'md:col-span-2',
                      )}
                      optimizeByCost={optimizeByCost} optimizeByCo2={optimizeByCo2}
                      setOptimizeByCost={setOptimizeByCost} setOptimizeByCo2={setOptimizeByCo2}
                      onRerun={doOptimize} busy={isSolving}
                    />
                  </div>
                ) : (
                  <Notice tone="fail" title="No IRC-adequate design within the current bounds">
                    The advisories above name the governing failure mode and the closest-to-passing CDF. Typical remedies:
                    raise the layer max-thickness bounds, revisit the subgrade CBR, or revisit the traffic inputs (CVPD / VDF / growth / design life).
                  </Notice>
                )}
              </>
            ) : !optimizationMode && results ? (
              <>
                {/* IRC verdict of the evaluated section */}
                {evalVerdict && (
                  <div className="grid gap-x-4 gap-y-2 grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 rounded-md border border-[var(--hairline)] bg-[var(--surface-sunken)] p-2.5">
                    {evalVerdict.hasBituminous && (
                      evalVerdict.compressive ? (
                        <div className="fp-kpi">
                          <span className="fp-kpi-label">Fatigue (Eq. 3.{reliabilityPercent === 90 ? 4 : 3})</span>
                          <Chip tone="info" title="Every horizontal strain at the bottom of the bituminous layer is compressive: fatigue need not be checked (IRC:37-2018 Annex III).">Not checked · compressive</Chip>
                        </div>
                      ) : (
                        <UtilBar label={`Fatigue CDF (Eq. 3.${reliabilityPercent === 90 ? 4 : 3})`} ratio={evalVerdict.cdfF}
                          display={evalVerdict.cdfF != null ? `${(evalVerdict.cdfF * 100).toFixed(1)}%` : 'no εt point'}
                          note={evalVerdict.epsT != null ? `εt ${(evalVerdict.epsT * 1e6).toFixed(1)} µε · allowable ${(evalVerdict.allow.epsT * 1e6).toFixed(1)} µε` : 'place a point at the bituminous bottom'}
                          title="(εt / allowable)^3.89 = design traffic / Nf at the bottom of the bituminous layer, for the current traffic and reliability." />
                      )
                    )}
                    <UtilBar label={`Rutting CDF (Eq. 3.${reliabilityPercent === 90 ? 2 : 1})`} ratio={evalVerdict.cdfR}
                      display={evalVerdict.cdfR != null ? `${(evalVerdict.cdfR * 100).toFixed(1)}%` : 'no εv point'}
                      note={evalVerdict.epsV != null ? `εv ${(evalVerdict.epsV * 1e6).toFixed(1)} µε · allowable ${(evalVerdict.allow.epsV * 1e6).toFixed(1)} µε` : 'place a point at the top of the subgrade'}
                      title="(εv / allowable)^4.5337 = design traffic / NR at the top of the subgrade." />
                    {longLife && evalVerdict.hasBituminous && !evalVerdict.compressive && (
                      <UtilBar label={<>Long-life <span className="normal-case">εt / 80 µε</span></>} ariaLabel="Long-life tensile strain ratio" ratio={evalVerdict.llT}
                        display={evalVerdict.epsT != null ? `${(evalVerdict.epsT * 1e6).toFixed(1)} µε` : '—'}
                        title="IRC:37-2018 §10 endurance limit for the bituminous tensile strain (35 °C)." />
                    )}
                    {longLife && (
                      <UtilBar label={<>Long-life <span className="normal-case">εv / 200 µε</span></>} ariaLabel="Long-life vertical strain ratio" ratio={evalVerdict.llV}
                        display={evalVerdict.epsV != null ? `${(evalVerdict.epsV * 1e6).toFixed(1)} µε` : '—'}
                        title="IRC:37-2018 §10 limit for the subgrade vertical strain." />
                    )}
                    {(() => {
                      const ratios = [evalVerdict.cdfF, evalVerdict.cdfR, evalVerdict.llT, evalVerdict.llV].filter(x => x != null);
                      const worst = ratios.length ? Math.max(...ratios) : null;
                      if (worst == null) return null;
                      return (
                        <div className="fp-kpi justify-center">
                          <span className="fp-kpi-label">Verdict ({designMsa.toFixed(1)} msa · R{reliabilityPercent})</span>
                          <span>
                            <Chip tone={worst > 1 ? 'fail' : 'ok'}>{worst > 1 ? 'Fails IRC' : 'Passes IRC'}</Chip>
                            <span className="text-[10px] text-[var(--text-muted)] ml-1.5">{stackHasCtb ? 'CTB fatigue: run Optimize' : 'bituminous fatigue + subgrade rutting'}</span>
                          </span>
                        </div>
                      );
                    })()}
                  </div>
                )}
                {evalVerdict && !evalVerdict.roles.ok && (
                  <Notice tone="warn" title="Analysis points are off the critical interfaces">
                    The verdict needs a point at the bottom of the bituminous layer and one at the top of the subgrade.{' '}
                    <button type="button" className="underline font-semibold" onClick={placeIrcPoints}>Place IRC points</button> and evaluate again.
                  </Notice>
                )}
                {/* Peak responses: the solve response's governing maxima.
                    ε_h is the largest TENSILE horizontal strain, max of the
                    signed ε_t, ε_r (tension +), floored at 0 — the quantity the
                    IRC fatigue criterion takes (Annex III: an all-compressive
                    strain is not checked). */}
                {(() => {
                  const maxDisp = Math.max(0, ...results.map(r => Math.abs(r.disp_z || 0)));
                  const maxEpsH = Math.max(0, ...results.map(r => Math.max(Number(r.eps_t) || 0, Number(r.eps_r) || 0)));
                  const maxEpsZ = Math.max(0, ...results.map(r => Math.abs(r.eps_z || 0)));
                  return (
                    <div className="grid grid-cols-3 gap-3 px-1">
                      <Kpi label={<><span className="normal-case">δz</span> max</>} value={maxDisp.toFixed(3)} unit="mm" title="Maximum |δ_z| across the evaluated points" />
                      <Kpi label={<><span className="normal-case">εh</span> max (tensile)</>} value={(maxEpsH * 1e6).toFixed(1)} unit="µε"
                        title="Largest TENSILE horizontal strain across the points — max of the signed ε_t, ε_r (tension positive), 0 when every value is compressive (IRC:37-2018 Annex III)." />
                      <Kpi label={<><span className="normal-case">εz</span> max</>} value={(maxEpsZ * 1e6).toFixed(1)} unit="µε" title="Maximum |ε_z| across the points — rutting-governing at the top of the subgrade" />
                    </div>
                  );
                })()}
                <div className="overflow-auto rounded-md border border-[var(--hairline)]">
                <table className="w-full min-w-[1050px] text-[11px] text-left fp-num border-collapse leading-5">
                <thead className="text-[10px] text-[var(--text-muted)] font-semibold sticky top-0 z-20 bg-[var(--tile-head)]">
                  <tr className="tracking-wide">
                    <th colSpan={3} className="py-1 px-3 border-b border-[var(--hairline)]">Location</th>
                    <th colSpan={4} className="py-1 px-3 border-b border-[var(--hairline)]">Stress state (MPa)</th>
                    <th className="py-1 px-3 border-b border-[var(--hairline)]">Deflection</th>
                    <th colSpan={3} className="py-1 px-3 border-b border-[var(--hairline)] text-[var(--accent)]">Strains (failure checks)</th>
                  </tr>
                  <tr>
                    <th className="py-1.5 px-3 border-b border-[var(--hairline)]">Role</th>
                    <th className="py-1.5 px-3 border-b border-[var(--hairline)]">z (mm)</th>
                    <th className="py-1.5 px-3 border-b border-[var(--hairline)]">r (mm)</th>
                    <th className="py-1.5 px-3 border-b border-[var(--hairline)]">σ_z</th>
                    <th className="py-1.5 px-3 border-b border-[var(--hairline)]">σ_t</th>
                    <th className="py-1.5 px-3 border-b border-[var(--hairline)]">σ_r</th>
                    <th
                      className="py-1.5 px-3 border-b border-[var(--hairline)] cursor-help"
                      title={"τ_rz — vertical shear stress (MPa). Not used by any IRC:37 design criterion (fatigue uses ε_t/ε_r, rutting uses ε_z, CTB uses σ_t).\n\nIITPAVE convention note: for a dual wheel evaluated on the symmetry axis (R = spacing/2), the two wheels' shear contributions cancel, so the physically-correct elastic value is ≈ 0 — which is what this solver reports. The original IITPAVE instead reports ≈ 2× the single-wheel shear here, because it superimposes the two wheels without the symmetry sign-flip. The two agree on all design quantities (σ, ε, δ) to <1%; only this non-design shear differs."}
                    >τ_rz<span className="align-super text-[7px] ml-0.5">&#9432;</span></th>
                    <th className="py-1.5 px-3 border-b border-[var(--hairline)]">δ_z (mm)</th>
                    <th
                      className="py-1.5 px-3 border-b border-[var(--hairline)] border-l text-[var(--accent)] cursor-help"
                      title="ε_r — radial horizontal strain (tension positive). The IRC:37 fatigue criterion uses the largest TENSILE horizontal strain, max of the signed ε_t, ε_r at the bottom of the bituminous layer; under dual wheels at R = 155 mm, ε_r can govern over ε_t. If both are compressive, fatigue is not checked (IRC:37-2018 Annex III)."
                    >ε_r<span className="align-super text-[7px] ml-0.5">&#9432;</span></th>
                    <th className="py-1.5 px-3 border-b border-[var(--hairline)] border-l text-[var(--fail)] sticky right-24 z-20 bg-[var(--tile-head)]">ε_z</th>
                    <th className="py-1.5 px-3 border-b border-[var(--hairline)] border-l text-[var(--accent)] sticky right-0 z-20 bg-[var(--tile-head)]">ε_t</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r,i)=>{
                    const role = evalVerdict?.roles.bit_bottom.includes(i) ? 'εt' : evalVerdict?.roles.sub_top.includes(i) ? 'εv' : null;
                    return (
                      <tr key={i} className="border-b border-[var(--hairline)] hover:bg-[var(--surface-sunken)]">
                        <td className="py-1 px-3">{role ? <Chip tone="info">{role}</Chip> : <span className="text-[var(--text-muted)]">—</span>}</td>
                        <td className="py-1 px-3 text-[var(--text-bold)]">{r.z.toFixed(1)}</td>
                        <td className="py-1 px-3 text-[var(--text-bold)]">{r.r.toFixed(1)}</td>
                        <td className="py-1 px-3">{formatSci(r.sigma_z)}</td>
                        <td className="py-1 px-3">{formatSci(r.sigma_t)}</td>
                        <td className="py-1 px-3">{formatSci(r.sigma_r)}</td>
                        <td className="py-1 px-3 text-[var(--text-muted)]">{formatSci(r.tau_rz)}</td>
                        <td className="py-1 px-3">{formatSci(r.disp_z)}</td>
                        <td className="py-1 px-3 border-l border-[var(--hairline)] text-[var(--text-bold)]">{formatSci(r.eps_r)}</td>
                        <td className="py-1 px-3 font-semibold text-[var(--fail)] border-l border-[var(--hairline)] sticky right-24 z-10 bg-[var(--surface-panel)]">{formatSci(r.eps_z)}</td>
                        <td className="py-1 px-3 font-semibold text-[var(--accent)] border-l border-[var(--hairline)] sticky right-0 z-10 bg-[var(--surface-panel)]">{formatSci(r.eps_t)}</td>
                      </tr>
                    );
                  })}
                </tbody>
                </table>
                </div>
              </>
            ) : (
              <div className="grid gap-2 sm:grid-cols-3 text-[11px] text-[var(--text-main)] py-2">
                {[
                  ['1', 'Set the section', 'Layer materials and thicknesses; mark layers Opt to let the optimizer vary them within min–max.'],
                  ['2', 'Evaluate', 'Ctrl+Enter — stresses and strains at the analysis points, with the IRC fatigue and rutting verdict.'],
                  ['3', 'Optimize', 'Ctrl+Shift+Enter — exhaustive search of constructable lifts; up to four IRC-adequate archetypes.'],
                ].map(([n, h, t]) => (
                  <div key={n} className="flex gap-2 rounded-md border border-dashed border-[var(--hairline-strong)] p-2.5">
                    <span className="flex-none h-5 w-5 rounded-full bg-[var(--accent-soft)] text-[var(--accent)] text-[10px] font-bold flex items-center justify-center">{n}</span>
                    <div><div className="font-bold text-[var(--text-bold)]">{h}</div><div className="text-[var(--text-muted)] leading-snug">{t}</div></div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Tile>
      </main>

      {/* Help Modal */}
      {showInstructions && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-6 backdrop-blur-[2px]" onClick={() => setShowInstructions(false)}>
          <div role="dialog" aria-modal="true" aria-label="Usage guide" onClick={e => e.stopPropagation()}
               className="fp-fade-up bg-[var(--surface-panel)] rounded-[var(--radius-tile)] shadow-2xl w-full max-w-4xl overflow-hidden flex flex-col h-[80vh] max-h-[750px] border border-[var(--hairline)]">
            <div className="flex justify-between items-center px-4 py-3 border-b border-[var(--hairline)] bg-[var(--surface-sunken)]">
              <h2 className="text-sm font-bold text-[var(--text-bold)] flex items-center gap-2">
                <Info size={16} className="text-orange-600"/> 
                <span>IndoPave-37 Operations Manual & Usage Guide</span>
              </h2>
              <button onClick={()=>setShowInstructions(false)} className="text-[var(--text-muted)] hover:text-[var(--text-bold)] p-1 rounded hover:bg-slate-200/50 dark:hover:bg-slate-700/50 transition-colors">
                <X size={18}/>
              </button>
            </div>
            
            <div className="flex-1 flex overflow-hidden min-h-0">
              {/* Sidebar Tabs */}
              <div className="w-56 flex-none border-r border-[var(--hairline)] bg-[var(--surface-sunken)] p-3 flex flex-col gap-1 overflow-y-auto">
                <button 
                  onClick={() => setHelpActiveTab('workflow')}
                  className={cn(
                    "w-full text-left px-3 py-2 rounded-lg text-xs font-semibold flex items-center gap-2.5 transition-all select-none",
                    helpActiveTab === 'workflow' 
                      ? "bg-orange-600 text-white shadow-sm" 
                      : "text-[var(--text-main)] hover:bg-[var(--surface-panel)] hover:text-[var(--text-bold)]"
                  )}
                >
                  <Layers size={13}/>
                  <span>Overview & Workflow</span>
                </button>
                <button 
                  onClick={() => setHelpActiveTab('solver')}
                  className={cn(
                    "w-full text-left px-3 py-2 rounded-lg text-xs font-semibold flex items-center gap-2.5 transition-all select-none",
                    helpActiveTab === 'solver' 
                      ? "bg-orange-600 text-white shadow-sm" 
                      : "text-[var(--text-main)] hover:bg-[var(--surface-panel)] hover:text-[var(--text-bold)]"
                  )}
                >
                  <Book size={13}/>
                  <span>IITPave Solver & IRC</span>
                </button>
                <button 
                  onClick={() => setHelpActiveTab('optimizer')}
                  className={cn(
                    "w-full text-left px-3 py-2 rounded-lg text-xs font-semibold flex items-center gap-2.5 transition-all select-none",
                    helpActiveTab === 'optimizer' 
                      ? "bg-orange-600 text-white shadow-sm" 
                      : "text-[var(--text-main)] hover:bg-[var(--surface-panel)] hover:text-[var(--text-bold)]"
                  )}
                >
                  <Settings size={13}/>
                  <span>Smart Search Optimizer</span>
                </button>
                <button 
                  onClick={() => setHelpActiveTab('advanced')}
                  className={cn(
                    "w-full text-left px-3 py-2 rounded-lg text-xs font-semibold flex items-center gap-2.5 transition-all select-none",
                    helpActiveTab === 'advanced' 
                      ? "bg-orange-600 text-white shadow-sm" 
                      : "text-[var(--text-main)] hover:bg-[var(--surface-panel)] hover:text-[var(--text-bold)]"
                  )}
                >
                  <Zap size={13}/>
                  <span>Advanced Features</span>
                </button>
              </div>

              {/* Tab Content */}
              <div className="flex-1 p-6 overflow-y-auto bg-[var(--surface-panel)] text-[var(--text-main)] text-xs leading-relaxed">
                {helpActiveTab === 'workflow' && (
                  <div className="flex flex-col gap-5 fp-fade-up">
                    <div>
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-1.5 flex items-center gap-1.5">
                        <span className="h-5 w-5 rounded-full bg-orange-100 dark:bg-orange-950/30 text-orange-700 dark:text-orange-400 flex items-center justify-center text-[10px] font-bold">1</span>
                        Cockpit layout
                      </h3>
                      <p className="mb-2">
                        The cockpit is a grid of tiles; each tile holds one part of the design and shows its result live:
                      </p>
                      <ul className="list-disc ml-5 space-y-1.5 mb-3 text-[11px]">
                        <li><strong>App bar:</strong> design traffic and reliability, <strong>Evaluate</strong> (Ctrl+Enter) and <strong>Optimize</strong> (Ctrl+Shift+Enter), use cases, Import/Export, PDF report, Advanced panels and the light/dark theme.</li>
                        <li><strong>Layer structure:</strong> material, Fixed/Opt mode, modulus (Auto Eq. 7.1 for unbound granular layers, Auto Table 9.2 for bituminous layers), Poisson's ratio and thickness or range. Hovering a row highlights the layer in the cross-section.</li>
                        <li><strong>Traffic · design basis:</strong> road category, carriageway (sets the LDF, IRC §4.5.1), CVPD, growth, years to opening, design period, VDF with the Table 4.2 indicative value.</li>
                        <li><strong>Bituminous mix · climate:</strong> binder grade and pavement temperature (Table 9.2 modulus), Va and Vbe (fatigue C factor).</li>
                        <li><strong>Load · subgrade:</strong> subgrade CBR (resilient modulus by Eq. 6.1/6.2) and the wheel load; the IRC standard axle is flagged.</li>
                        <li><strong>Design limits:</strong> allowable fatigue and rutting strains for the design traffic, and the long-life (§10) option.</li>
                        <li><strong>Cross-section:</strong> live section with loads, dimensions and analysis points; drag its left edge to resize.</li>
                      </ul>
                    </div>

                    <div className="border-t border-[var(--hairline)] pt-4">
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-2 flex items-center gap-1.5">
                        <span className="h-5 w-5 rounded-full bg-orange-100 dark:bg-orange-950/30 text-orange-700 dark:text-orange-400 flex items-center justify-center text-[10px] font-bold">2</span>
                        Step-by-Step Pavement Design Workflow
                      </h3>
                      <ol className="list-decimal ml-5 space-y-2 text-[11px]">
                        <li>
                          <strong>Define the trial structure:</strong> in the Layer structure tile, set the materials, thicknesses <i>h</i> (mm), resilient moduli <i>E</i> (MPa) and Poisson's ratios <i>ν</i>.
                        </li>
                        <li>
                          <strong>Set the traffic and the subgrade:</strong> enter the CVPD, growth, design period, VDF and carriageway in the Traffic tile (the design traffic in msa follows from IRC Eq. 4.5/4.6) and the subgrade CBR in the Load · subgrade tile. The resilient modulus M<sub>RS</sub> is computed from:
                          <div className="bg-[var(--surface-sunken)] p-2 rounded-md font-mono my-1.5 text-[10px] text-[var(--text-bold)] border border-[var(--hairline)]">
                            CBR ≤ 5%: MR = 10 × CBR (MPa) <br />
                            CBR &gt; 5%: MR = 17.6 × CBR^0.64 (MPa)
                          </div>
                        </li>
                        <li>
                          <strong>Check the load:</strong> IRC:37-2018 analyses the standard axle — a dual-wheel set of 20 kN per wheel at 0.56 MPa, 310 mm centre to centre. Other loads can be studied, and are flagged as non-standard.
                        </li>
                        <li>
                          <strong>Position Analysis Coordinates:</strong> Add coordinates in the Analysis Points Grid where you want to calculate stresses/strains (e.g., bottom of bituminous layer or top of subgrade).
                        </li>
                        <li>
                          <strong>Evaluate or Optimize:</strong> Click <strong>Evaluate</strong> for a single analysis of the current thicknesses, or check <strong>Opt</strong> on layers and click <strong>Optimize</strong> to search range-based adequate designs.
                        </li>
                      </ol>
                    </div>

                    <div className="border-t border-[var(--hairline)] pt-4 bg-orange-50/50 dark:bg-orange-950/10 p-3 rounded-lg border border-orange-100/50 dark:border-orange-900/20">
                      <h4 className="font-bold text-orange-900 dark:text-orange-300 mb-1">Local Session Sync & Portability</h4>
                      <p className="text-[11px] text-orange-800 dark:text-orange-400">
                        All configuration parameters, custom layer properties, cost catalogs, and layout selections are synchronized to `localStorage` automatically on every keystroke. 
                        Use <strong>Export</strong> to download the project as a <code>.json</code> file, and <strong>Import</strong> to open it again.
                      </p>
                    </div>
                  </div>
                )}

                {helpActiveTab === 'solver' && (
                  <div className="flex flex-col gap-5 fp-fade-up">
                    <div>
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-2 flex items-center gap-1.5">
                        <Activity size={15} className="text-orange-600" />
                        Mechanistic Linear Elastic Layer Engine
                      </h3>
                      <p className="mb-2">
                        IndoPave-37 runs the mechanistic elastic layer solver (in-browser via Pyodide or via backend API) to compute stress, strain, and displacement fields at designated coordinates (<i>r</i>, <i>z</i>) under circular load patches. The soil subgrade is modeled as an infinitely deep elastic half-space.
                      </p>
                    </div>

                    <div className="border-t border-[var(--hairline)] pt-4">
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-2">Primary Design Criteria (IRC:37-2019)</h3>
                      <p className="mb-3">
                        The solver validates structural adequacy against fatigue and rutting performance transfer functions defined by <strong>IRC:37-2018</strong>:
                      </p>
                      
                      <div className="grid grid-cols-2 gap-4">
                        <div className="bg-[var(--surface-sunken)] p-3 rounded-lg border border-[var(--hairline)]">
                          <span className="font-bold text-red-600 dark:text-red-400 block mb-1">1. Bituminous Fatigue Cracking (ε_t)</span>
                          <p className="text-[10px] text-[var(--text-muted)] leading-relaxed">
                            Horizontal tensile strain at the bottom of the lowest bituminous layer. High strain causes premature cracking under repeated traffic loads.
                          </p>
                        </div>
                        <div className="bg-[var(--surface-sunken)] p-3 rounded-lg border border-[var(--hairline)]">
                          <span className="font-bold text-orange-600 dark:text-orange-400 block mb-1">2. Subgrade Rutting (ε_v)</span>
                          <p className="text-[10px] text-[var(--text-muted)] leading-relaxed">
                            Vertical compressive strain at the top of the subgrade. High strain values propagate shear deformation to the surface, creating ruts.
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="border-t border-[var(--hairline)] pt-4">
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-2">IRC:37-2018 design basis in the cockpit</h3>
                      <ul className="list-disc ml-5 space-y-1.5 text-[11px]">
                        <li><strong>Bituminous modulus (§9.2, Table 9.2):</strong> with Auto, BC/DBM take the Table 9.2 value for the binder grade and average annual pavement temperature (20–40 °C; about 35 °C in the plains). All bituminous layers are analysed as one layer with the modulus of the bottom mix, in Evaluate, the advanced panels and the optimizer alike. A pinned (tested) value must not exceed the table value.</li>
                        <li><strong>Allowable strains:</strong> the Design limits tile solves Eq. 3.1–3.4 for the strain that uses up the design traffic, so the evaluated strains can be compared directly (Annex II.6: 145 µε and 292 µε at 150 msa for VG40).</li>
                        <li><strong>Long-life pavements (§10, §4.3.1, Annex II.6):</strong> recommended from 300 msa and for expressways. The optimizer then also keeps the bituminous tensile strain within 80 µε and the subgrade strain within 200 µε.</li>
                        <li><strong>Traffic (§4.4–4.6):</strong> the carriageway type sets the lane distribution factor (§4.5.1); Table 4.2 gives the indicative VDF when no axle-load survey exists.</li>
                        <li><strong>Crack relief over CTB (§8.3):</strong> either a 100 mm aggregate layer (450 MPa) or a SAMI. A SAMI is not a structural layer, so the bituminous layer sits directly on the CTB in the analysis.</li>
                      </ul>
                    </div>

                    <div className="border-t border-[var(--hairline)] pt-4">
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-2">Solver Verification & Benchmarks</h3>
                      <p className="mb-2">
                        To guarantee numerical accuracy and conformance, the solver's strain output has been regression-tested against classical benchmarks:
                      </p>
                      <div className="bg-[var(--surface-sunken)] p-3 rounded-lg border border-[var(--hairline)] font-mono text-[10px] text-[var(--text-bold)] space-y-1.5">
                        <div className="flex justify-between border-b border-[var(--hairline)] pb-1">
                          <span className="font-bold">Benchmark Case</span>
                          <span className="font-bold text-teal-600 dark:text-teal-400">Verification Status</span>
                        </div>
                        <div className="flex justify-between">
                          <span>• rps1 (Thin Bituminous)</span>
                          <span>Passed (error &lt; 1.0%)</span>
                        </div>
                        <div className="flex justify-between">
                          <span>• case2 (Thick Highway Mix)</span>
                          <span>Passed (error &lt; 1.2%)</span>
                        </div>
                        <div className="flex justify-between">
                          <span>• IRC:37-2018 Annex-II (II.3 / II.4)</span>
                          <span>Passed (ε_t 146 vs 146 µε; σ_t 0.699 vs 0.700 MPa)</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {helpActiveTab === 'optimizer' && (
                  <div className="flex flex-col gap-5 fp-fade-up">
                    <div>
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-2 flex items-center gap-1.5">
                        <Settings size={15} className="text-orange-600" />
                        Smart Pavement Search Optimizer
                      </h3>
                      <p className="mb-2">
                        IndoPave-37 runs a deterministic brute-force search over constructable layer thicknesses <i>h</i> within the specified min/max bounds — it is exhaustive over a small, buildable design space, so it is fully reproducible with no local-minimum risk:
                      </p>
                      <ul className="list-disc ml-5 space-y-1.5 text-[11px] mb-3">
                        <li><strong>Enumerate &amp; pre-filter:</strong> builds every combination of MoRTH-aligned construction lift sizes within bounds, then drops those failing the IRC:37 / MoRTH minimum-thickness rules before any solver call.</li>
                        <li><strong>Evaluate:</strong> runs each design through the multi-layer elastic solver (ε_t at the bottom of the bottom bituminous layer, ε_v at the top of the subgrade), keeping designs with all IRC CDFs ≤ 1.0.</li>
                        <li><strong>Select archetypes:</strong> from the IRC-adequate designs it returns four optima — <strong>Structural</strong> (thinnest), <strong>Economy</strong> (cheapest), <strong>Sustainable</strong> (lowest CO₂) and <strong>Premium</strong> (best combined thickness + cost + CO₂). When one design wins several, its labels merge onto a single card.</li>
                      </ul>
                    </div>

                    <div className="border-t border-[var(--hairline)] pt-4">
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-2">Multi-Objective Optimization Focus</h3>
                      <p className="mb-2 text-[11px]">
                        The search checks targets specified under "Opt Target":
                      </p>
                      <ul className="list-disc ml-5 space-y-1 text-[11px]">
                        <li><strong>Thickness:</strong> Minimizes total structural height to save excavation depth.</li>
                        <li><strong>Cost:</strong> Computes cost based on material volumetric rates to find the cheapest structural alternative.</li>
                        <li><strong>Carbon Footprint:</strong> Uses material-specific CO₂ footprints to identify low-carbon designs.</li>
                      </ul>
                    </div>

                    <div className="border-t border-[var(--hairline)] pt-4">
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-2">Deterministic Engineering Archetypes</h3>
                      <p className="mb-3">
                        The optimizer returns up to four distinct archetype designs, each shown as a card with its IRC utilization bars:
                      </p>
                      
                      <div className="grid grid-cols-2 gap-3 text-[11px]">
                        <div className="border border-[var(--hairline)] p-2.5 rounded-lg">
                          <strong className="text-sky-600 dark:text-sky-400 block mb-1">🔵 Structural</strong>
                          <span>The thinnest IRC-adequate section — the minimum-material result straight from the solver. Saves excavation depth and crust volume.</span>
                        </div>
                        <div className="border border-[var(--hairline)] p-2.5 rounded-lg">
                          <strong className="text-emerald-600 dark:text-emerald-400 block mb-1">💰 Economy</strong>
                          <span>The cheapest IRC-adequate design (lowest ₹/km) using the material unit rates — the best capital-cost bargain.</span>
                        </div>
                        <div className="border border-[var(--hairline)] p-2.5 rounded-lg">
                          <strong className="text-teal-600 dark:text-teal-400 block mb-1">🍀 Sustainable</strong>
                          <span>The lowest embodied-carbon design (kg CO₂ per lane-km) — the most sustainable adequate section.</span>
                        </div>
                        <div className="border border-[var(--hairline)] p-2.5 rounded-lg">
                          <strong className="text-indigo-600 dark:text-indigo-400 block mb-1">🏆 Premium</strong>
                          <span>The best <em>combined</em> optimum — jointly minimizes thickness, cost <em>and</em> CO₂ (closest to the ideal corner in normalized space).</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {helpActiveTab === 'advanced' && (
                  <div className="flex flex-col gap-5 fp-fade-up">
                    <div>
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-2 flex items-center gap-1.5">
                        <Zap size={15} className="text-orange-600" />
                        Advanced Cockpit Engineering Features
                      </h3>
                      <p className="mb-3">
                        IndoPave-37 includes advanced modules to support modern mechanistic pavement design and materials stabilization:
                      </p>

                      <div className="space-y-4">
                        <div className="border-b border-[var(--hairline)] pb-3">
                          <h4 className="font-bold text-[var(--text-bold)] text-[11px] mb-1">📊 3D Strain Bulbs Viewer</h4>
                          <p className="text-[11px]">
                            Visualizes 3D stress dissipation and pressure cones underneath circular load patches. It helps identify localized shear stress concentrations and structural interfaces that could result in delamination.
                          </p>
                        </div>

                        <div className="border-b border-[var(--hairline)] pb-3">
                          <h4 className="font-bold text-[var(--text-bold)] text-[11px] mb-1">🎲 Monte Carlo Sensitivity Analysis</h4>
                          <p className="text-[11px]">
                            Runs probabilistic simulations by applying standard deviations to layer thicknesses <i>h</i> and resilient moduli <i>E</i>. Executing 200+ runs computes structural life distribution, evaluating failure risks against material and construction variability.
                          </p>
                        </div>

                        <div className="border-b border-[var(--hairline)] pb-3">
                          <h4 className="font-bold text-[var(--text-bold)] text-[11px] mb-1">🌾 Low-Volume Roads (IRC:SP:72-2015)</h4>
                          <p className="text-[11px]">
                            Switches structural guidelines to low-volume pavement rules. Categorizes traffic into SP:72 standard MSA bands (T1 to T9) and designs gravel sub-bases, soil stabilizers, and thin bituminous seals accordingly.
                          </p>
                        </div>

                        <div className="border-b border-[var(--hairline)] pb-3">
                          <h4 className="font-bold text-[var(--text-bold)] text-[11px] mb-1">🕸️ Geosynthetic Base Reinforcement (Geogrids)</h4>
                          <p className="text-[11px]">
                            Enables geogrid interlayers inside granular bases. Applies a <strong>Modulus Improvement Factor (MIF)</strong> from the Saride et al. (2022) research table, depending on geogrid type and subgrade modulus, <strong>capped at 2.0</strong> — the IRC:SP:59-2019 §3.1.3 design maximum for geogrids. The reinforced layer is modelled separately, resting on the effective modulus of the layers below (IRC:37-2018 §8.1). SP:59 requires third-party-validated MIF for the actual product.
                          </p>
                        </div>

                        <div>
                          <h4 className="font-bold text-[var(--text-bold)] text-[11px] mb-1">🚒 Cement Treated Base (CTB) Axle Spectrum Analysis</h4>
                          <p className="text-[11px]">
                            CTB fatigue is always checked with the strain-based IRC:37-2018 Eq. 3.5 criterion against the design traffic. Supplying an axle load spectrum additionally runs the stress-ratio cumulative damage analysis (Eq. 3.6, CFD ≤ 1.0) against the CTB Modulus of Rupture (M<sub>rup</sub> = 1.4 MPa) — the worse of the two governs.
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="px-4 py-3 border-t border-[var(--hairline)] bg-[var(--surface-sunken)] flex justify-end">
              <button 
                onClick={()=>setShowInstructions(false)} 
                className="px-4 py-1.5 bg-orange-600 hover:bg-orange-700 text-white font-bold rounded-lg text-xs shadow-md transition-all active:scale-95"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}



      {showAdvanced && (
        <AdvancedPanel
          sharedState={{
            numLayers, load, pressure, wheelType, wheelSpacing,
            temperature, points, numPoints, cvpd, subgradeCbr,
            airVoids, bitumenVolume,
            results, optimizedDesigns, materialRates,
            // Single source of truth for design assumptions used by every
            // advanced module — the SAME editable state /api/optimize uses.
            growthRate,
            designLife,
            ldf,
            vdf,
            reliabilityPercent,
            roadCategory,
            constructionYears,
            // Analysis moduli (engine-consistent) replace the displayed ones.
            layers: analysisLayers,
          }}
          onClose={() => setShowAdvanced(false)}
          onUpdateLayer={(idx, props) => {
            if (props.E !== undefined) {
              updateLayer(idx, 'E', props.E);
              // Applying a specific material modulus PINS it — otherwise the
              // Auto Eq. 7.1 effect would silently overwrite the applied value
              // on the next render.
              updateLayer(idx, 'auto_E', false);
            }
            if (props.nu !== undefined) updateLayer(idx, 'nu', props.nu);
          }}
        />
      )}
    </div>
  );
}
