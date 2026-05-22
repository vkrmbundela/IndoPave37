import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Save, Play, Settings, Plus, Trash2, ArrowRight, Table2, Loader2, Info, X, Download, Upload, Book, RotateCcw, Database, Layers, Zap, AlertCircle, MoreHorizontal, IndianRupee, Activity
} from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
import AdvancedPanel from './v2/AdvancedPanel';
import { solveAnalysis, runOptimize, onSolverStatus, getSolverMode } from './lib/solver-client';
import { useResizableTable } from './lib/useResizableTable';

function ColGrip({ rt, i }) {
  return (
    <span
      className="fp-col-grip"
      onPointerDown={(e) => rt.startColResize(i, e)}
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


const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

const DEFAULT_LAYERS = [
  { id: '1', name: 'Layer 1', type: 'BC',  E: 1250,   nu: 0.35, fixed_h: 40,  min_h: 30,  max_h: 50,  is_fixed: true },
  { id: '2', name: 'Layer 2', type: 'DBM', E: 1250,   nu: 0.35, fixed_h: 120, min_h: 50,  max_h: 250, is_fixed: false },
  { id: '3', name: 'Layer 3', type: 'WMM', E: 371.37, nu: 0.35, fixed_h: 250, min_h: 150, max_h: 300, is_fixed: true },
  { id: '4', name: 'Layer 4', type: 'GSB', E: 143.43, nu: 0.35, fixed_h: 250, min_h: 150, max_h: 300, is_fixed: true },
  { id: '5', name: 'Subgrade', type: '', E: 55.4, nu: 0.40, fixed_h: 0, min_h: 0, max_h: 0, is_fixed: true },
];


const DEFAULT_POINTS = [
  { z: 159.9, r: 0 },
  { z: 159.9, r: 155 },
  { z: 659.9, r: 0 },
  { z: 659.9, r: 155 },
];

const DEMO_CASES = [
  {
    name: "National Highway (IRC-37)",
    numLayers: 5,
    layers: [
      { id: '1', name: 'BC', E: 3000, nu: 0.35, fixed_h: 40, is_fixed: true },
      { id: '2', name: 'DBM', E: 3000, nu: 0.35, fixed_h: 120, is_fixed: true },
      { id: '3', name: 'WMM', E: 450, nu: 0.35, fixed_h: 250, is_fixed: true },
      { id: '4', name: 'GSB', E: 150, nu: 0.35, fixed_h: 200, is_fixed: true },
      { id: '5', name: 'Subgrade', E: 60, nu: 0.40, is_fixed: true },
    ],
    load: 20000,
    pressure: 0.56,
    wheelType: 'Dual',
    numPoints: 4,
    points: [
      { z: 160, r: 0 },
      { z: 160, r: 155 },
      { z: 610, r: 0 },
      { z: 610, r: 155 },
    ],
    cvpd: 1500,
    subgradeCbr: 8
  },
  {
    name: "Rural Road (PMGSY)",
    numLayers: 3,
    layers: [
      { id: '1', name: 'Paved Surface', E: 1500, nu: 0.35, fixed_h: 20, is_fixed: true },
      { id: '2', name: 'WMM/GSB', E: 200, nu: 0.35, fixed_h: 225, is_fixed: true },
      { id: '3', name: 'Subgrade', E: 45, nu: 0.40, is_fixed: true },
    ],
    load: 10000,
    pressure: 0.45,
    wheelType: 'Single',
    numPoints: 2,
    points: [
      { z: 20, r: 0 },
      { z: 245, r: 0 },
    ],
    cvpd: 150,
    subgradeCbr: 5
  },
  {
    name: "Expressway (Optimization)",
    numLayers: 5,
    layers: [
      { id: '1', name: 'BC', E: 4500, nu: 0.35, fixed_h: 50, is_fixed: true },
      { id: '2', name: 'DBM', E: 4500, nu: 0.35, fixed_h: 150, min_h: 100, max_h: 250, is_fixed: false },
      { id: '3', name: 'WMM', E: 500, nu: 0.35, fixed_h: 200, is_fixed: true },
      { id: '4', name: 'GSB', E: 200, nu: 0.35, fixed_h: 250, is_fixed: true },
      { id: '5', name: 'Subgrade', E: 70, nu: 0.40, is_fixed: true },
    ],
    load: 20000,
    pressure: 0.56,
    wheelType: 'Dual',
    numPoints: 4,
    points: [
      { z: 200, r: 0 },
      { z: 200, r: 155 },
      { z: 650, r: 0 },
      { z: 650, r: 155 },
    ],
    cvpd: 2500,
    subgradeCbr: 10
  }
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

// Selectable pavement material types (must match backend BITUMINOUS_TYPES /
// GRANULAR_TYPES so the optimizer can classify each layer). Optional per layer.
const LAYER_TYPE_OPTIONS = ['BC', 'DBM', 'BM', 'SDBC', 'SMA', 'WMM', 'WBM', 'GSB', 'CTB'];
// Granular layer types that accept geosynthetic (geogrid) reinforcement.
const GRANULAR_LAYER_TYPES = new Set(['WMM', 'WBM', 'GSB']);

// Resolve the effective material type for a layer: explicit `type` wins; else
// fall back to `name` when it is itself a known type (legacy use-case data).
const layerType = (l) => l.type || (LAYER_TYPE_OPTIONS.includes(l.name) ? l.name : '');
// IRC:SP:59 / Saride 2021 geogrid options (MIF approach).
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
 * Design assumptions used across the main cockpit AND the advanced modules.
 * Keeping them here makes this the single source of truth — when the user
 * changes (or the UI eventually surfaces) any of these, both /api/optimize
 * and every advanced panel see the same values automatically.
 *
 * Defaults follow IRC 37:2018 typical values.
 */
const DESIGN_DEFAULTS = {
  growthRate: 0.05,         // 5% per annum
  designLife: 20,           // years
  ldf: 0.75,                // lane distribution factor
  vdf: 2.5,                 // vehicle damage factor
  reliabilityPercent: 80,   // R80 (low-volume) — switch to 90 for ≥30 MSA
};

/* ─── Compact Cross-Section SVG ─── */
const getOverlayId = (l, isSubgrade) => {
  if (isSubgrade) return 'overlay-soil';
  const type = (l.type || l.name || '').toUpperCase();
  if (type.includes('BC') || type.includes('DBM') || type.includes('SMA') || type.includes('SDBC') || type.includes('BM') || type.includes('PAVED') || type.includes('SURFACE')) {
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
  if (type.includes('BM') || type.includes('SMA') || type.includes('SDBC') || type.includes('PAVED')) return '#1c1917';
  if (type.includes('WMM')) return '#475569';
  if (type.includes('WBM')) return '#5a6b7c';
  if (type.includes('GSB')) return '#78716c';
  if (type.includes('CTB')) return '#4c586a';
  
  const colors = ['#2e3b4e', '#3f4f64', '#55667d', '#6e7e96', '#8797b0'];
  return colors[i % colors.length];
};

function PavementVisualizer({ layers, points, wheelType, wheelSpacing = 310, load = 20000, pressure = 0.56 }) {
  const surfaceY = 65;
  const svgW = 540, svgH = 320;
  const depth = svgH - surfaceY - 25;
  const sw = 280; // width of pavement block

  const finite = layers.slice(0, -1);
  const totalH = finite.reduce((s, l) => s + (l.is_fixed ? l.fixed_h : l.max_h), 0);
  const maxPt = Math.max(0, ...points.map(p => p.z));
  const target = Math.max(totalH + 100, maxPt + 80);
  const scale = depth / target;

  const wSp = wheelSpacing * scale;
  const tireW = Math.max(12, Math.min(30, 160 * scale));
  const tireH = Math.max(15, Math.min(36, 200 * scale));
  const badgeY = -tireH - 30;
  const badgeW = 75, badgeH = 20;

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

      <g transform={`translate(270, ${surfaceY})`}>
        {/* Center line (CL) */}
        <line x1="0" y1={-surfaceY + 12} x2="0" y2={depth + 10} stroke="var(--vis-cl)" strokeWidth="0.8" strokeDasharray="6,4,2,4" />
        <text x="0" y={-surfaceY + 22} textAnchor="middle" fontSize="6.5" fill="var(--vis-text-muted)" fontWeight="700" letterSpacing="0.5">CENTERLINE</text>

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
          const hmm = sub ? target : (l.is_fixed ? l.fixed_h : l.max_h);
          const hpx = hmm * scale;
          const dy = layers.slice(0, i).reduce((s, p) => s + ((p.is_fixed ? p.fixed_h : p.max_h) * scale), 0);
          const drawH = sub ? Math.max(hpx, depth + 10 - dy) : Math.max(hpx, 4);
          
          const overlayId = getOverlayId(l, sub);
          const baseColor = getLayerColor(l, i, sub);
          
          return (
            <g key={i} className="group cursor-pointer">
              {/* Solid layer fill */}
              <rect x={-sw/2} y={dy} width={sw} height={drawH} fill={baseColor} stroke="var(--vis-bg)" strokeWidth="0.5" />
              
              {/* Texture overlay pattern */}
              <rect x={-sw/2} y={dy} width={sw} height={drawH} fill={`url(#${overlayId})`} opacity="0.28" pointerEvents="none" />
              
              {/* Inner layer labeling */}
              {(drawH > 13 || sub) && (
                <text
                  x={-sw/2 + 8}
                  y={dy + (sub ? 15 : drawH / 2 + 2.5)}
                  fontSize="6.5"
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
                  <rect x={sw/2 - 45} y={dy + drawH - 5} width={42} height={10} rx="1.5" fill="#ea580c" />
                  <text x={sw/2 - 24} y={dy + drawH + 2.5} textAnchor="middle" fontSize="5" fill="#ffffff" fontWeight="bold">
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
                  <line x1={-25} y1={badgeY + badgeH} x2={-wSp/2} y2={-tireH} stroke="var(--vis-text-muted)" strokeWidth="0.6" strokeDasharray="1,1" />
                  <line x1={25} y1={badgeY + badgeH} x2={wSp/2} y2={-tireH} stroke="var(--vis-text-muted)" strokeWidth="0.6" strokeDasharray="1,1" />
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
              <text x="0" y={badgeY + 8} textAnchor="middle" fontSize="5.5" fill="var(--vis-text)" fontWeight="800" fontFamily="monospace">
                LOAD: {displayLoad}
              </text>
              <text x="0" y={badgeY + 15} textAnchor="middle" fontSize="5" fill="var(--vis-text-muted)" fontWeight="bold" fontFamily="monospace">
                PRES: {displayPressure}
              </text>
            </g>
          );
        })()}

        {/* CAD Ruler - Left side vertical cumulative depth ruler */}
        <g>
          <line x1={-185} y1={0} x2={-185} y2={target * scale} stroke="var(--vis-text)" strokeWidth="0.8" />
          <text x={-185 - 12} y={-4} textAnchor="end" fontSize="5" fill="var(--vis-text-muted)" fontWeight="bold" letterSpacing="0.2">DEPTH (mm)</text>
          
          {(() => {
            const ticks = [];
            const tickStep = 50;
            for (let z = 0; z <= target; z += tickStep) {
              const zy = z * scale;
              const isMajor = z % 100 === 0;
              const tickLen = isMajor ? 8 : 4;
              ticks.push(
                <g key={`ruler-tick-${z}`}>
                  <line x1={-185 - tickLen} y1={zy} x2={-185} y2={zy} stroke="var(--vis-text-muted)" strokeWidth={isMajor ? 0.8 : 0.5} />
                  {isMajor && (
                    <text x={-185 - 12} y={zy + 2} textAnchor="end" fontSize="5.5" fill="var(--vis-text-muted)" fontFamily="monospace" fontWeight="600">
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
          const hmm = l.is_fixed ? l.fixed_h : l.max_h;
          const hpx = hmm * scale;
          const dy = layers.slice(0, i).reduce((s, p) => s + ((p.is_fixed ? p.fixed_h : p.max_h) * scale), 0);
          
          return (
            <g key={`layer-dim-${i}`}>
              <line x1={-sw/2} y1={dy} x2={-165} y2={dy} stroke="var(--vis-border)" strokeWidth="0.4" strokeDasharray="1,2" />
              <line x1={-sw/2} y1={dy + hpx} x2={-165} y2={dy + hpx} stroke="var(--vis-border)" strokeWidth="0.4" strokeDasharray="1,2" />
              <line x1={-163} y1={dy} x2={-163} y2={dy + hpx} stroke="var(--vis-text-muted)" strokeWidth="0.6" />
              <polygon points={`-163,${dy} -165,${dy + 3.5} -161,${dy + 3.5}`} fill="var(--vis-text-muted)" />
              <polygon points={`-163,${dy + hpx} -165,${dy + hpx - 3.5} -161,${dy + hpx - 3.5}`} fill="var(--vis-text-muted)" />
              
              {hpx > 10 && (
                <g>
                  <rect x={-178} y={dy + hpx/2 - 4.5} width={30} height={9} fill="var(--vis-bg)" opacity="0.9" />
                  <text x={-163} y={dy + hpx/2 + 1.8} textAnchor="middle" fontSize="5" fill="var(--vis-text)" fontWeight="700" fontFamily="monospace">
                    {hmm}
                  </text>
                </g>
              )}
            </g>
          );
        })}

        {/* Right side specifications callouts (with slanted leader lines) */}
        {layers.map((l, i) => {
          const sub = i === layers.length - 1;
          const hmm = sub ? 80 : (l.is_fixed ? l.fixed_h : l.max_h);
          const hpx = hmm * scale;
          const dy = layers.slice(0, i).reduce((s, p) => s + ((p.is_fixed ? p.fixed_h : p.max_h) * scale), 0);
          
          const calloutY = -15 + (i * 38);
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
                y={calloutY - 11}
                width={50}
                height={22}
                rx="2"
                fill="var(--vis-bg)"
                stroke="var(--vis-border)"
                strokeWidth="0.6"
                opacity="0.9"
              />
              <text x={sw/2 + 42} y={calloutY - 3} fontSize="5.2" fill="var(--vis-text)" fontWeight="bold" letterSpacing="0.2">
                E: {l.E} MPa
              </text>
              <text x={sw/2 + 42} y={calloutY + 4} fontSize="5" fill="var(--vis-text-muted)" fontWeight="bold" letterSpacing="0.2">
                ν: {l.nu.toFixed(2)}
              </text>
              <text x={sw/2 + 82} y={calloutY + 8} fontSize="4" fill="var(--vis-text-muted)" fontWeight="bold" textAnchor="end">
                {sub ? 'SUB' : `L${i+1}`}
              </text>
            </g>
          );
        })}

        {/* HUD Interactive Target Analysis Points */}
        {points.map((p, i) => {
          const px = p.r * scale;
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
                  y={py - 6}
                  width={34}
                  height={11}
                  rx="1.5"
                  fill="var(--vis-bg)"
                  stroke="#10b981"
                  strokeWidth="0.6"
                  opacity="0.85"
                />
                <text x={px + 10} y={py + 2} fontSize="5" fill="#047857" fontWeight="bold" fontFamily="monospace">
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

  const [results, setResults] = useState(savedData.results || null);
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
  const [previewWidth, onPreviewDrag] = useSplitter(savedData.previewWidth || 300, 'horizontal');


  // Auto-Save Effect
  useEffect(() => {
    const dataToSave = {
      layers, numLayers, load, pressure, wheelType, wheelSpacing, points, numPoints,
      cvpd, subgradeCbr, temperature, results, optimizationMode,
      optimizedDesigns, hasStarted, previewWidth,
      materialRates, showRatesPanel,
      showCtbPanel, useCtbSpectrum, ctbSpectrumText, ctbPerClassBridgeRecompute,
      optimizeByCost, optimizeByCo2,
    };
    localStorage.setItem('flexpave_cache', JSON.stringify(dataToSave));
  }, [
    layers, numLayers, load, pressure, wheelType, wheelSpacing, points, numPoints,
    cvpd, subgradeCbr, temperature, results, optimizationMode,
    optimizedDesigns, hasStarted, previewWidth,
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

      const data = await solveAnalysis({
        layers: targetLayers.map((l, i) => ({
          E: l.E,
          nu: l.nu,
          h: i === targetLayers.length - 1 ? 0 : (l.is_fixed ? (l.fixed_h || 0) : (l.min_h || 0)),
        })),
        wheel_load: targetLoad,
        tire_pressure: targetPressure,
        wheel_type: targetWheelType,
        wheel_spacing: wheelSpacing,
        points: targetPoints.map(p => ({ z: p.z, r: p.r })),
      });
      setResults(data.results || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setIsSolving(false);
      setSolverStatus(null);
    }
  };

  const doOptimize = async () => {
    setIsSolving(true); setError(null); setOptimizedDesigns(null); setResults(null); setOptimizationMode(true);
    try {
      const parsedCtbSpectrum = useCtbSpectrum ? normalizeCtbAxleSpectrum(ctbSpectrumText) : null;
      const data = await runOptimize({
        layers: layers.map(l=>({
          layer_type: layerType(l) || l.name,
          E: l.E,
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
        growth_rate: DESIGN_DEFAULTS.growthRate,
        design_life: DESIGN_DEFAULTS.designLife,
        lane_factor: DESIGN_DEFAULTS.ldf,
        vdf: DESIGN_DEFAULTS.vdf,
        reliability: `${DESIGN_DEFAULTS.reliabilityPercent}%`,
        wheel_load: load,
        tire_pressure: pressure,
        wheel_type: wheelType,
        wheel_spacing: wheelSpacing,
        points: points.map(p=>({z:p.z, r:p.r})),
        material_rates: materialRates,
        ctb_axle_spectrum: parsedCtbSpectrum && parsedCtbSpectrum.length ? parsedCtbSpectrum : undefined,
        ctb_per_class_bridge_recompute: ctbPerClassBridgeRecompute,
        optimize_by_cost: optimizeByCost,
        optimize_by_co2: optimizeByCo2,
      });
      setOptimizedDesigns(data.adequate_designs || []);
      setSp72Info(data.sp72 || null);
      setReinforcementInfo(data.reinforcement && data.reinforcement.length ? data.reinforcement : null);
    } catch(e) { setError(e.message); }
    finally { setIsSolving(false); }
  };

  const handleExport = () => {
    const cfg = {
      layers, numLayers, load, pressure, wheelType, points, numPoints,
      cvpd, subgradeCbr, temperature, materialRates, showRatesPanel,
      useCtbSpectrum, ctbSpectrumText, ctbPerClassBridgeRecompute,
      optimizeByCost, optimizeByCo2,
    };
    const b = new Blob([JSON.stringify(cfg,null,2)],{type:'application/json'});
    const u = URL.createObjectURL(b);
    const a = document.createElement('a'); a.href=u; a.download='flexpave_config.json'; a.click();
    URL.revokeObjectURL(u);
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
    setLayers(demo.layers);
    setNumLayers(demo.numLayers);
    setLoad(demo.load);
    setPressure(demo.pressure);
    setWheelType(demo.wheelType);
    setPoints(demo.points);
    setNumPoints(demo.numPoints);
    if(demo.cvpd) setCvpd(demo.cvpd);
    if(demo.subgradeCbr) setSubgradeCbr(demo.subgradeCbr);
    setHasStarted(true);
    // Auto-trigger evaluation if all layers are fixed
    if (demo.layers.every(l => l.is_fixed || l.name === 'Subgrade')) {
      setTimeout(() => doSingleRun(demo), 100);
    }
  };

  const [showDemos, setShowDemos] = useState(false);
  const [showMoreMenu, setShowMoreMenu] = useState(false);

  const inp = "bg-white border border-slate-300 rounded-md px-1.5 py-0.5 text-xs text-slate-800 outline-none focus:border-orange-500 focus:ring-2 focus:ring-orange-100 hover:border-slate-400 font-mono transition-colors";

  // Resizable tables — column widths (px) per data table.
  const layerRT = useResizableTable([60, 116, 54, 90, 60, 170]);
  const pointsRT = useResizableTable([28, 90, 90]);
  const formatSci = (v) => {
    if (v === undefined || v === null) return '—';
    const n = Number(v);
    return Number.isFinite(n) ? n.toExponential(4) : '—';
  };

  /* ── SPLASH ── */
  if (!hasStarted) {
    return (
      <div className="min-h-[100svh] min-h-[100dvh] w-full flex items-center justify-center font-sans">
        <input type="file" ref={fileInputRef} onChange={handleImport} accept=".json" className="hidden"/>
        <div className="fp-fade-up bg-white/90 backdrop-blur-xl border border-white/60 rounded-3xl p-12 flex flex-col items-center max-w-sm w-full text-center"
             style={{ boxShadow: 'var(--elev-3)' }}>
          <div className="flex flex-col items-center mb-12">
            <div className="h-28 w-28 flex items-center justify-center mb-6">
              <img src={`${import.meta.env.BASE_URL}assets/logo_mark.png`} alt="FlexPave Icon" className="h-24 w-auto object-contain" />
            </div>
            <h1 className="text-4xl font-black tracking-tight uppercase bg-gradient-to-r from-slate-900 via-slate-800 to-orange-700 bg-clip-text text-transparent">FLEXPAVE</h1>
            <p className="text-[11px] text-slate-400 mt-1.5 tracking-wide font-medium">Mechanistic Pavement Design · IRC:37</p>
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
  return (
    <div className="min-h-[100svh] min-h-[100dvh] w-full bg-transparent text-gray-800 font-sans flex flex-col">

      {/* TOOLBAR */}
      <div className="flex-none flex items-center justify-between fp-glass-bar px-3 py-1.5 relative z-30">
        <div className="flex items-center gap-2.5">
          <span className="h-7 w-7 flex items-center justify-center overflow-hidden">
            <img src={`${import.meta.env.BASE_URL}assets/logo_mark.png`} alt="FlexPave" className="h-6 w-auto object-contain" />
          </span>
          <span className="text-[15px] font-extrabold tracking-tight bg-gradient-to-r from-slate-900 via-slate-800 to-orange-700 bg-clip-text text-transparent">FlexPave</span>
          <span
            className="text-[10px] text-gray-400 ml-0.5 cursor-help"
            onDoubleClick={() => setDebugMode(!debugMode)}
            title="Double-click for debug mode"
          >
            v1.0
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <input type="file" ref={fileInputRef} onChange={handleImport} accept=".json" className="hidden"/>

          {/* Always-visible primary actions */}
          <button
            onClick={()=>fileInputRef.current?.click()}
            className="px-2 py-1 text-[11px] text-gray-700 hover:bg-gray-100 rounded border border-gray-200 font-medium flex items-center gap-1 select-none"
          >
            <Upload size={11}/> Import
          </button>
          <button
            onClick={() => setShowCtbPanel(!showCtbPanel)}
            className={cn(
              "px-2 py-1 text-[11px] rounded border font-medium flex items-center gap-1 select-none transition-colors",
              showCtbPanel ? "bg-orange-50 border-orange-200 text-orange-700" : "text-gray-700 hover:bg-gray-100 border-gray-200"
            )}
            title="Toggle CTB Axle Spectrum Analysis"
          >
            <Activity size={12} />
            CTB Analysis
          </button>

          <button
            onClick={()=>setShowAdvanced(true)}
            className="px-2 py-1 text-[11px] text-orange-700 hover:bg-orange-50 rounded border border-orange-200 font-medium flex items-center gap-1 select-none"
          >
            <Zap size={11}/> Advanced
          </button>
          <button
            onClick={handleReset}
            className="px-2 py-1 text-[11px] text-red-600 hover:bg-red-50 rounded border border-red-200 font-medium flex items-center gap-1 select-none"
          >
            <RotateCcw size={11}/> Reset
          </button>

          {/* Desktop secondary actions */}
          <div className="hidden md:flex items-center gap-1">
            <button
              onClick={handleExport}
              className="px-2 py-1 text-[11px] text-gray-600 hover:bg-gray-100 rounded border border-gray-200 font-medium flex items-center gap-1 select-none"
            >
              <Download size={11}/> Export
            </button>
            <a
              href="https://law.resource.org/pub/in/bis/irc/irc.gov.in.037.2019.pdf"
              target="_blank"
              rel="noopener noreferrer"
              className="px-2 py-1 text-[11px] text-gray-600 hover:bg-gray-100 rounded border border-gray-200 font-medium flex items-center gap-1 no-underline select-none"
            >
              <Book size={11}/> IRC:37
            </a>
            <div className="relative">
              <button
                onClick={()=>{ setShowDemos(v=>!v); setShowMoreMenu(false); }}
                className="px-2 py-1 text-[11px] text-orange-700 hover:bg-orange-50 rounded border border-orange-200 font-medium flex items-center gap-1 transition-colors select-none"
              >
                <Database size={11}/> Use Cases
              </button>
              {showDemos && (
                <div className="absolute right-0 mt-1 w-48 bg-white border border-gray-300 rounded shadow-lg z-[60] py-1 overflow-hidden">
                  <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-gray-400 font-bold border-b border-gray-100 mb-1">Select Scenario</div>
                  {DEMO_CASES.map((c,i) => (
                    <button key={i} onClick={() => { handleApplyDemo(c); setShowDemos(false); }} className="w-full text-left px-3 py-1.5 text-[11px] text-gray-700 hover:bg-orange-50 hover:text-orange-800 transition-colors flex items-center gap-2 select-none">
                      <ArrowRight size={10} className="text-orange-500 opacity-50"/> {c.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={()=>setShowInstructions(true)}
              className="px-2 py-1 text-[11px] text-orange-700 hover:bg-orange-50 rounded border border-orange-200 font-medium flex items-center gap-1 select-none"
            >
              <Info size={11}/> Help
            </button>
          </div>

          {/* Mobile secondary actions */}
          <div className="relative md:hidden">
            <button
              onClick={() => { setShowMoreMenu(v => !v); setShowDemos(false); }}
              className="h-7 w-7 rounded border border-gray-200 hover:bg-gray-100 text-gray-700 flex items-center justify-center select-none"
              title="More actions"
            >
              <MoreHorizontal size={14} />
            </button>
            {showMoreMenu && (
              <div className="absolute right-0 mt-1 w-56 bg-white border border-gray-300 rounded shadow-lg z-[60] py-1 overflow-hidden">
                <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-gray-400 font-bold border-b border-gray-100 mb-1">More Actions</div>
                <button
                  onClick={() => { handleExport(); setShowMoreMenu(false); }}
                  className="w-full text-left px-3 py-1.5 text-[11px] text-gray-700 hover:bg-gray-50 flex items-center gap-2 select-none"
                >
                  <Download size={11} className="text-gray-500" /> Export
                </button>
                <a
                  href="https://law.resource.org/pub/in/bis/irc/irc.gov.in.037.2019.pdf"
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => setShowMoreMenu(false)}
                  className="w-full no-underline text-left px-3 py-1.5 text-[11px] text-gray-700 hover:bg-gray-50 flex items-center gap-2 select-none"
                >
                  <Book size={11} className="text-gray-500" /> IRC:37
                </a>
                <button
                  onClick={() => { setShowInstructions(true); setShowMoreMenu(false); }}
                  className="w-full text-left px-3 py-1.5 text-[11px] text-gray-700 hover:bg-gray-50 flex items-center gap-2 select-none"
                >
                  <Info size={11} className="text-gray-500" /> Help
                </button>
                <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-gray-400 font-bold border-y border-gray-100 mt-1 mb-1">Use Cases</div>
                {DEMO_CASES.map((c, i) => (
                  <button
                    key={i}
                    onClick={() => { handleApplyDemo(c); setShowMoreMenu(false); }}
                    className="w-full text-left px-3 py-1.5 text-[11px] text-gray-700 hover:bg-orange-50 hover:text-orange-800 transition-colors flex items-center gap-2 select-none"
                  >
                    <ArrowRight size={10} className="text-orange-500 opacity-50"/> {c.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* WORKSPACE: inputs, preview, and results flow in a scrollable column */}
      <div className="flex-1 flex flex-col">

        {/* ═══ TOP: Inputs + Preview ═══ */}
        <div className="flex min-h-0">

          {/* ── Left: All inputs ── */}
          <div className="flex-1 flex flex-col bg-white min-w-0 overflow-y-auto">

            {/* Layer Table */}
            <div className="px-3 pt-2 pb-1.5 border-b border-gray-100">
              <div className="flex justify-between items-center mb-1">
                <span className="text-[11px] font-bold uppercase text-slate-600 tracking-wide flex items-center gap-1.5">
                  <span className="inline-block w-1 h-3.5 rounded-full" style={{background:'var(--accent-grad)'}}></span>
                  Layer Structure
                </span>
                <div className="flex items-center gap-1">
                  <label className="text-[10px] text-gray-400">Layers:</label>
                  <select value={numLayers} onChange={e=>setNumLayers(parseInt(e.target.value))}
                    className="border border-slate-300 rounded-md px-1 py-0.5 text-[11px] font-bold text-slate-700 bg-white outline-none cursor-pointer hover:border-orange-400 focus:border-orange-500 focus:ring-2 focus:ring-orange-100">
                    {[2,3,4,5,6,7,8,9,10].map(n=><option key={n} value={n}>{n}</option>)}
                  </select>
                </div>
              </div>
              <table className="fp-rt text-[11px] border-collapse">
                <colgroup>{layerRT.cols.map((w,k)=><col key={k} style={{width:w}}/>)}</colgroup>
                <thead>
                  <tr className="fp-head-strip text-[10px] text-slate-500 uppercase font-semibold tracking-wide">
                    <th className="relative text-left py-1.5 px-1.5">Layer<ColGrip rt={layerRT} i={0}/></th>
                    <th className="relative text-left py-1.5 px-1.5">Type <span className="normal-case font-normal text-slate-400">(opt)</span><ColGrip rt={layerRT} i={1}/></th>
                    <th className="relative text-center py-1.5 px-1">Mode<ColGrip rt={layerRT} i={2}/></th>
                    <th className="relative text-left py-1.5 px-1.5">E (MPa)<ColGrip rt={layerRT} i={3}/></th>
                    <th className="relative text-left py-1.5 px-1.5">ν<ColGrip rt={layerRT} i={4}/></th>
                    <th className="relative text-left py-1.5 px-1.5">Thickness (mm)<ColGrip rt={layerRT} i={5}/></th>
                  </tr>
                </thead>
                <tbody>
                  {layers.map((l,i)=>{
                    const sub = i===layers.length-1;
                    return (
                      <tr key={i} className="border-b border-gray-100 hover:bg-orange-50/30" style={layerRT.rowH[i]?{height:layerRT.rowH[i]}:undefined}>
                        {/* Layer — positional identity */}
                        <td className="relative py-1 px-1.5 font-semibold text-slate-600 align-top whitespace-nowrap">
                          {sub ? 'Subgrade' : `Layer ${i+1}`}
                          <RowGrip rt={layerRT} rowKey={i} getHeight={()=>layerRT.rowH[i]||0}/>
                        </td>
                        {/* Type — optional material classification */}
                        <td className="py-1 px-1.5 align-top">
                          {!sub && (
                            <>
                              <select
                                value={layerType(l)}
                                onChange={e=>{ const v=e.target.value; updateLayer(i,'type',v); if(!GRANULAR_LAYER_TYPES.has(v)) updateLayer(i,'geogrid',null); }}
                                title="Optional material type — set it to enable IRC classification, material rates, and geogrid"
                                className="w-full border border-slate-300 rounded-md px-1.5 py-0.5 text-[11px] font-bold text-slate-700 bg-white outline-none cursor-pointer transition-colors hover:border-orange-400 focus:border-orange-500 focus:ring-2 focus:ring-orange-100">
                                <option value="">— none</option>
                                {LAYER_TYPE_OPTIONS.map(t=><option key={t} value={t}>{t}</option>)}
                              </select>
                              {GRANULAR_LAYER_TYPES.has(layerType(l)) && (
                                <select
                                  value={l.geogrid || 'none'}
                                  onChange={e=>updateLayer(i,'geogrid', e.target.value==='none'?null:e.target.value)}
                                  title="Geosynthetic reinforcement (IRC:SP:59 / MIF) — uplifts granular modulus to trim thickness"
                                  className={cn(
                                    "mt-1 border rounded-md px-1.5 py-0.5 text-[9px] font-bold outline-none cursor-pointer w-full transition-colors",
                                    l.geogrid ? "text-emerald-700 bg-emerald-50 border-emerald-300 shadow-[0_0_0_2px_rgba(16,185,129,0.08)]" : "text-slate-400 bg-slate-50 border-slate-200 hover:border-emerald-300"
                                  )}>
                                  {GEOGRID_OPTIONS.map(g=><option key={g.id} value={g.id}>{g.id==='none'?'⊘ no grid':`▦ ${g.label}`}</option>)}
                                </select>
                              )}
                            </>
                          )}
                        </td>
                        <td className="py-1 px-1 text-center">
                          {!sub ? (
                            <button onClick={()=>updateLayer(i,'is_fixed',!l.is_fixed)}
                              className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded-sm border",
                                l.is_fixed?"text-teal-700 bg-teal-50 border-teal-200":"text-orange-700 bg-orange-50 border-orange-200")}>
                              {l.is_fixed?'Fixed':'Opt'}
                            </button>
                          ):<span className="text-[10px] text-gray-400">∞</span>}
                        </td>
                        <td className="py-0.5 px-1"><input type="number" value={l.E} onChange={e=>updateLayer(i,'E',Number(e.target.value))} className={cn(inp,"w-20")}/></td>
                        <td className="py-0.5 px-1"><input type="number" value={l.nu} onChange={e=>updateLayer(i,'nu',Number(e.target.value))} step="0.01" className={cn(inp,"w-14")}/></td>
                        <td className="py-0.5 px-1.5">
                          {sub ? <span className="text-gray-400 text-[11px]">∞</span>
                          : l.is_fixed ? <input type="number" value={l.fixed_h} onChange={e=>updateLayer(i,'fixed_h',Number(e.target.value))} className={cn(inp,"w-20")}/>
                          : <div className="flex gap-1 items-center">
                              <input type="number" value={l.min_h} onChange={e=>updateLayer(i,'min_h',Number(e.target.value))} className={cn(inp,"w-16")} placeholder="min"/>
                              <span className="text-gray-400 text-xs">–</span>
                              <input type="number" value={l.max_h} onChange={e=>updateLayer(i,'max_h',Number(e.target.value))} className={cn(inp,"w-16")} placeholder="max"/>
                            </div>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Bottom strip: Analysis Points | Load Config | Opt Target | Actions */}
            <div className="px-3 py-2 flex flex-wrap gap-3 items-stretch">

              {/* Analysis Points — proper mini table */}
              <fieldset className="flex-1 border border-gray-200 rounded px-2 pt-0.5 pb-1.5 min-w-0">
                <legend className="text-[10px] font-bold uppercase text-gray-400 tracking-wide px-1 flex items-center gap-1">
                  Analysis Points
                  <select value={numPoints} onChange={e=>setNumPoints(parseInt(e.target.value))}
                    className="border border-gray-300 rounded px-1 py-0 text-[10px] font-bold text-gray-600 bg-white outline-none cursor-pointer ml-1">
                    {[1,2,3,4,5,6,7,8,9,10].map(n=><option key={n} value={n}>{n}</option>)}
                  </select>
                </legend>
                <table className="fp-rt text-[11px] border-collapse">
                  <colgroup>{pointsRT.cols.map((w,k)=><col key={k} style={{width:w}}/>)}</colgroup>
                  <thead>
                    <tr className="text-[9px] text-gray-400 uppercase font-semibold">
                      <th className="relative text-left py-0.5">#<ColGrip rt={pointsRT} i={0}/></th>
                      <th className="relative text-left py-0.5">Z (mm)<ColGrip rt={pointsRT} i={1}/></th>
                      <th className="relative text-left py-0.5">R (mm)<ColGrip rt={pointsRT} i={2}/></th>
                    </tr>
                  </thead>
                  <tbody>
                    {points.map((p,i)=>(
                      <tr key={i} style={pointsRT.rowH[i]?{height:pointsRT.rowH[i]}:undefined}>
                        <td className="relative py-0.5 font-bold text-gray-400 text-[10px]">{i+1}<RowGrip rt={pointsRT} rowKey={i} getHeight={()=>pointsRT.rowH[i]||0}/></td>
                        <td className="py-0.5 pr-1"><input type="number" value={p.z} onChange={e=>updatePoint(i,'z',Number(e.target.value))} className={cn(inp,"w-full py-0")}/></td>
                        <td className="py-0.5"><input type="number" value={p.r} onChange={e=>updatePoint(i,'r',Number(e.target.value))} className={cn(inp,"w-full py-0")}/></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </fieldset>

              {/* Material Rates Panel */}
              <fieldset className="border border-gray-200 rounded px-2 pt-0.5 pb-1.5 w-56 flex-none">
                <legend className="text-[10px] font-bold uppercase text-gray-400 tracking-wide px-1 flex items-center justify-between">
                  <span>Material Rates</span>
                  <button onClick={() => setShowRatesPanel(v => !v)} className="text-[10px] text-gray-500 ml-2 px-1 py-0.5 rounded hover:bg-gray-100">{showRatesPanel ? 'Hide' : 'Show'}</button>
                </legend>
                {showRatesPanel ? (
                  <div className="flex flex-col gap-1 max-h-40 overflow-auto">
                    <div className="flex items-center gap-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wide pl-12 pr-1">
                      <span className="w-24 text-center">Cost / m³</span>
                      <span className="w-20 text-center">CO2 / m³</span>
                    </div>
                    {Object.keys(materialRates).map((m) => (
                      <div key={m} className="flex items-center gap-2">
                        <div className="w-12 text-[11px] font-bold text-gray-700">{m}</div>
                        <input type="number" step="1" value={materialRates[m].cost_per_cum || ''} onChange={e=>updateMaterialRate(m,'cost_per_cum', Number(e.target.value))} className={cn(inp,'w-24')}/>
                        <input type="number" step="1" value={materialRates[m].co2_per_cum || ''} onChange={e=>updateMaterialRate(m,'co2_per_cum', Number(e.target.value))} className={cn(inp,'w-20')}/>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[11px] text-gray-500">Using custom material rates</div>
                )}
              </fieldset>

              {/* Load Configuration */}
              <fieldset className="border border-gray-200 rounded px-2 pt-0.5 pb-1.5 w-44 flex-none">
                <legend className="text-[10px] font-bold uppercase text-gray-400 tracking-wide px-1">Load Config</legend>
                <div className="flex flex-col gap-1">
                  <div className="flex items-center gap-1.5">
                    <label className="text-[10px] text-gray-500 font-medium w-14 text-right shrink-0">Load (N)</label>
                    <input type="number" value={load} onChange={e=>setLoad(Number(e.target.value))} className={cn(inp,"flex-1 py-0")}/>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <label className="text-[10px] text-gray-500 font-medium w-14 text-right shrink-0">Tyre (MPa)</label>
                    <input type="number" step="0.01" value={pressure} onChange={e=>setPressure(Number(e.target.value))} className={cn(inp,"flex-1 py-0")}/>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <label className="text-[10px] text-gray-500 font-medium w-14 text-right shrink-0">Wheel</label>
                    <select value={wheelType} onChange={e=>setWheelType(e.target.value)} className={cn(inp,"flex-1 py-0 cursor-pointer")}>
                      <option value="Single">Single</option><option value="Dual">Dual</option>
                    </select>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <label className="text-[10px] text-gray-500 font-medium w-14 text-right shrink-0">Spacing</label>
                    <input type="number" step="1" value={wheelSpacing} onChange={e=>setWheelSpacing(Number(e.target.value))} className={cn(inp,"flex-1 py-0")} />
                  </div>
                  <div className="flex items-center gap-1.5 h-4">
                    {debugMode && (
                      <>
                        <label className="text-[10px] text-red-500 font-bold w-14 text-right shrink-0">DEBUG</label>
                        <input type="checkbox" checked={debugMode} onChange={e=>setDebugMode(e.target.checked)} className="cursor-pointer" />
                      </>
                    )}
                  </div>
                </div>
              </fieldset>

              {/* Optimization Target */}
              <fieldset className="border border-gray-200 rounded px-2 pt-0.5 pb-1.5 w-40 flex-none">
                <legend className="text-[10px] font-bold uppercase text-gray-400 tracking-wide px-1">Opt Target</legend>
                <div className="flex flex-col gap-1">
                  <div className="flex items-center gap-1.5">
                    <label className="text-[10px] text-gray-500 font-medium w-10 text-right shrink-0">CVPD</label>
                    <input type="number" value={cvpd} onChange={e=>setCvpd(Number(e.target.value))} className={cn(inp,"flex-1 py-0")}/>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <label className="text-[10px] text-gray-500 font-medium w-10 text-right shrink-0">CBR %</label>
                    <input type="number" value={subgradeCbr} onChange={e=>setSubgradeCbr(Number(e.target.value))} className={cn(inp,"flex-1 py-0")}/>
                  </div>
                  <div className="flex items-center gap-1.5 border-t border-gray-100 pt-1 mt-0.5">
                    <input
                      type="checkbox"
                      id="optByCost"
                      checked={optimizeByCost}
                      onChange={e=>setOptimizeByCost(e.target.checked)}
                      className="cursor-pointer h-3 w-3 accent-orange-600 rounded"
                    />
                    <label htmlFor="optByCost" className="text-[10px] text-gray-600 font-semibold cursor-pointer select-none">Opt Cost</label>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      id="optByCo2"
                      checked={optimizeByCo2}
                      onChange={e=>setOptimizeByCo2(e.target.checked)}
                      className="cursor-pointer h-3 w-3 accent-orange-600 rounded"
                    />
                    <label htmlFor="optByCo2" className="text-[10px] text-gray-600 font-semibold cursor-pointer select-none">Opt CO₂</label>
                  </div>
                </div>
              </fieldset>

              {/* CTB Spectrum */}
              {showCtbPanel && (
                <fieldset className="border border-orange-200 bg-orange-50/20 rounded px-2 pt-0.5 pb-1.5 w-72 flex-none animate-in fade-in slide-in-from-left-2 duration-300">
                  <legend className="text-[10px] font-bold uppercase text-orange-600 tracking-wide px-1 flex items-center justify-between gap-2 w-full bg-white rounded border border-orange-100 py-0.5">
                    <div className="flex items-center gap-1">
                      <Activity size={10} />
                      <span>CTB Axle Spectrum</span>
                    </div>
                    <div className="flex items-center gap-2 text-[10px] font-medium text-gray-500 normal-case tracking-normal">
                      <label className="flex items-center gap-1 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={useCtbSpectrum}
                          onChange={e => {
                            const enabled = e.target.checked;
                            setUseCtbSpectrum(enabled);
                            if (enabled && !ctbSpectrumText.trim()) {
                              setCtbSpectrumText(DEFAULT_CTB_AXLE_SPECTRUM_TEXT);
                            }
                          }}
                        />
                        Enable
                      </label>
                      <label className="flex items-center gap-1 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={ctbPerClassBridgeRecompute}
                          onChange={e => setCtbPerClassBridgeRecompute(e.target.checked)}
                        />
                        Per-class
                      </label>
                    </div>
                  </legend>
                  <div className="flex flex-col gap-1 mt-1">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-[9px] text-orange-800 leading-tight">
                        <strong>Info:</strong> Define specific axle groups for Cement Treated Base fatigue analysis. 
                        Overrides default IRC reference damage values.
                      </p>
                      <button
                        type="button"
                        onClick={() => {
                          setUseCtbSpectrum(true);
                          setCtbSpectrumText(DEFAULT_CTB_AXLE_SPECTRUM_TEXT);
                        }}
                        className="text-[9px] text-orange-700 font-bold hover:bg-orange-100 px-1 py-0.5 rounded border border-orange-300 bg-white shrink-0"
                      >
                        Load Example
                      </button>
                    </div>
                    <textarea
                      value={ctbSpectrumText}
                      onChange={e => setCtbSpectrumText(e.target.value)}
                      rows={6}
                      spellCheck={false}
                      placeholder={DEFAULT_CTB_AXLE_SPECTRUM_TEXT}
                      className={cn(inp, "w-full min-h-24 resize-y font-mono text-[10px] leading-4 border-orange-200 focus:ring-orange-500")}
                    />
                    <p className="text-[8px] text-gray-500">
                      Format: Array of objects with <code>axle_type</code>, <code>load_kn</code>, and <code>expected_repetitions</code>.
                    </p>
                  </div>
                </fieldset>
              )}

              {/* Action Buttons */}
              <div className="flex flex-col gap-1.5 justify-center flex-none">
                <button onClick={doSingleRun} disabled={isSolving}
                  className="fp-btn-grad font-bold px-5 py-2 rounded-lg text-[11px] flex items-center justify-center gap-1 uppercase tracking-wide w-28 select-none">
                  {isSolving&&!optimizationMode?<Loader2 size={12} className="animate-spin"/>:<Play size={12}/>} Evaluate
                </button>
                <button onClick={doOptimize} disabled={isSolving}
                  className="bg-white hover:bg-orange-50 hover:border-orange-300 disabled:bg-gray-100 text-slate-700 disabled:text-gray-400 border border-slate-300 font-bold px-5 py-2 rounded-lg text-[11px] flex items-center justify-center gap-1 uppercase tracking-wide w-28 select-none shadow-sm active:scale-[0.99]">
                  {isSolving&&optimizationMode?<Loader2 size={12} className="animate-spin"/>:<ArrowRight size={12}/>} Optimize
                </button>
              </div>
            </div>
          </div>

          {/* ── Vertical Splitter ── */}
          <div className="relative w-1.5 flex-none group">
            <div
              onPointerDown={onPreviewDrag}
              className="absolute -left-3 -right-3 -top-3 -bottom-3 cursor-col-resize z-20 select-none touch-none"
              title="Drag to resize"
            />
            <div className="absolute inset-0 pointer-events-none bg-gray-200 group-hover:bg-orange-400 group-active:bg-orange-500 transition-colors" />
          </div>

          {/* ── Right: Compact Preview ── */}
          <div style={{ width: previewWidth }} className="flex-none flex flex-col bg-slate-50/70 min-h-0">
            <div className="flex-none px-2.5 py-1.5 fp-head-strip text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
              <span className="inline-block w-1 h-3 rounded-full" style={{background:'var(--accent-grad)'}}></span>
              Cross Section Preview
            </div>
            <div className="flex-1 p-1.5 flex items-center justify-center min-h-0 overflow-hidden">
              <PavementVisualizer 
                layers={layers} 
                points={points} 
                wheelType={wheelType} 
                wheelSpacing={wheelSpacing} 
                load={load} 
                pressure={pressure} 
              />
            </div>
          </div>
        </div>

        {/* ═══ BOTTOM: Results ═══ */}
        {/* ═══ Results ═══ */}
        <div className="flex flex-col bg-white border-t border-gray-200">
          <div className="flex-none px-3 py-1.5 fp-head-strip flex items-center justify-between">
            <span className="text-[11px] font-bold text-slate-600 uppercase tracking-wide flex items-center gap-1.5"><Table2 size={12} className="text-orange-600"/> Output Results</span>
            {results && !optimizationMode && <span className="text-[10px] text-slate-400 font-mono">{results.length} point(s)</span>}
          </div>
          <div className="overflow-auto">
            {error && <div className="m-2 text-red-700 bg-red-50 border border-red-200 p-2 rounded text-xs">{error}</div>}

            {optimizationMode && optimizedDesigns ? (
              <div className="p-3">
                {/* IRC:SP:72 low-volume regime banner */}
                {sp72Info && sp72Info.is_low_volume && (
                  <div className="mb-2 text-[11px] rounded border border-amber-200 bg-amber-50 text-amber-900 px-2.5 py-1.5">
                    <span className="font-bold uppercase tracking-wide mr-1">IRC:SP:72 Low-Volume</span>
                    <span className="font-semibold">{sp72Info.traffic_category || '—'}</span>
                    <span className="text-amber-700"> · {Number(sp72Info.esal).toLocaleString()} ESAL (~{sp72Info.msa} MSA)</span>
                    <span className="text-amber-700"> · Subgrade {sp72Info.subgrade_class} ({sp72Info.subgrade_class_name})</span>
                    {sp72Info.surfacing_hint && <span className="text-amber-700"> · Surfacing: {sp72Info.surfacing_hint}</span>}
                    {sp72Info.advisory && sp72Info.advisory.length > 0 && (
                      <div className="mt-0.5 text-[10px] text-amber-800/90">{sp72Info.advisory[sp72Info.advisory.length-1]}</div>
                    )}
                  </div>
                )}
                {/* Geosynthetic reinforcement badge */}
                {reinforcementInfo && (
                  <div className="mb-2 text-[11px] rounded border border-emerald-200 bg-emerald-50 text-emerald-900 px-2.5 py-1.5">
                    <span className="font-bold uppercase tracking-wide mr-1">Geosynthetic (IRC:SP:59 / MIF)</span>
                    {reinforcementInfo.map((r,ri)=>(
                      <span key={ri} className="mr-2">{r.layer} + {r.geogrid} → modulus ×{r.mif}</span>
                    ))}
                  </div>
                )}
                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wide mb-2">Pareto-Optimal Designs</div>
                {optimizedDesigns.length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                      {optimizedDesigns.slice(0, 12).map((d, i) => (
                        <div key={i} className="fp-card fp-fade-up overflow-hidden flex flex-col" style={{ animationDelay: `${Math.min(i,8)*40}ms` }}>
                          {/* Card Header */}
                          <div className="fp-head-strip px-3 py-2 flex justify-between items-center">
                            <div className="flex items-center gap-2">
                              <span className="bg-slate-800 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-md shadow-sm uppercase tracking-wide">#{i + 1}</span>
                              <span className={cn(
                                "text-[10px] font-bold px-2 py-0.5 rounded-md uppercase shadow-sm text-white tracking-wide",
                                d.details?.strategy === 'Economy' ? 'bg-gradient-to-r from-emerald-500 to-emerald-600' :
                                d.details?.strategy === 'Balanced' ? 'bg-gradient-to-r from-sky-500 to-sky-600' :
                                d.details?.strategy === 'Premium' ? 'bg-gradient-to-r from-indigo-500 to-indigo-600' :
                                'bg-gradient-to-r from-slate-500 to-slate-600'
                              )}>
                                {d.details?.strategy || 'Design'}
                              </span>
                            </div>
                            <span className="text-xs font-bold text-slate-800 flex items-center gap-1">
                              <Layers size={12} className="text-orange-600"/> {d.total_thickness.toFixed(0)} mm
                            </span>
                          </div>

                          <div className="p-3 flex-1 flex flex-col gap-3">
                            {/* Layer Table */}
                            <table className="w-full text-[10px] border-collapse">
                              <thead>
                                <tr className="text-gray-400 font-bold uppercase border-b border-gray-50">
                                  <th className="text-left py-1">Layer</th>
                                  <th className="text-center py-1">Type</th>
                                  <th className="text-center py-1">Thk</th>
                                  <th className="text-right py-1">E (MPa)</th>
                                </tr>
                              </thead>
                              <tbody>
                                {d.details?.layers?.map((l, j) => (
                                  <tr key={j} className="border-b border-gray-50 last:border-0 hover:bg-gray-50 transition-colors">
                                    <td className="py-1 text-gray-400 font-mono">L{l.id}</td>
                                    <td className="py-1 text-center font-medium text-gray-700">{l.name}</td>
                                    <td className="py-1 text-center font-bold text-orange-900">{l.thickness > 0 ? `${l.thickness.toFixed(0)}` : '∞'}</td>
                                    <td className="py-1 text-right text-gray-500">{l.modulus.toFixed(0)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>

                            {/* Performance Metrics */}
                            <div className="grid grid-cols-2 gap-2 bg-orange-50/30 p-2 rounded border border-orange-100/50">
                              <div className="flex flex-col">
                                <div className="flex justify-between items-center mb-0.5">
                                  <span className="text-[9px] text-gray-500 font-bold uppercase">Fatigue (ε_t)</span>
                                  <span className={`text-[9px] font-bold ${(d.details?.CDF_fatigue > 0.9) ? 'text-red-600' : 'text-green-600'}`}>
                                    {d.details?.CDF_fatigue != null ? (d.details.CDF_fatigue * 100).toFixed(1) + '%' : '--'}
                                  </span>
                                </div>
                                <div className="h-1 bg-gray-200 rounded-full overflow-hidden">
                                  <div
                                    className={`h-full transition-all duration-300 ${(d.details?.CDF_fatigue > 0.9) ? 'bg-red-500' : 'bg-green-500'}`}
                                    style={{ width: `${Math.min(100, (d.details?.CDF_fatigue || 0) * 100)}%` }}
                                  />
                                </div>
                              </div>
                              <div className="flex flex-col">
                                <div className="flex justify-between items-center mb-0.5">
                                  <span className="text-[9px] text-gray-500 font-bold uppercase">Rutting (ε_z)</span>
                                  <span className={`text-[9px] font-bold ${(d.details?.CDF_rutting > 0.9) ? 'text-red-600' : 'text-green-600'}`}>
                                    {d.details?.CDF_rutting != null ? (d.details.CDF_rutting * 100).toFixed(1) + '%' : '--'}
                                  </span>
                                </div>
                                <div className="h-1 bg-gray-200 rounded-full overflow-hidden">
                                  <div
                                    className={`h-full transition-all duration-300 ${(d.details?.CDF_rutting > 0.9) ? 'bg-red-500' : 'bg-green-500'}`}
                                    style={{ width: `${Math.min(100, (d.details?.CDF_rutting || 0) * 100)}%` }}
                                  />
                                </div>
                              </div>
                            </div>

                            {/* Meta & Governing */}
                            <div className="flex justify-between items-center space-x-2">
                               <div className="bg-gray-100 rounded px-1.5 py-0.5 flex items-center gap-1 group">
                                  <Zap size={10} className="text-orange-500"/>
                                  <span className="text-[9px] font-bold text-gray-600 uppercase tracking-tighter">Traffic: {d.details?.msa != null ? d.details.msa.toFixed(1) : '--'} MSA</span>
                               </div>
                               <div className={`rounded px-1.5 py-0.5 flex items-center gap-1 border ${d.details?.governing_mode === 'fatigue' ? 'bg-orange-50 border-orange-200 text-orange-700' : 'bg-blue-50 border-blue-200 text-blue-700'}`}>
                                  <AlertCircle size={10} />
                                  <span className="text-[9px] font-bold uppercase italic">{d.details?.governing_mode} governed</span>
                               </div>
                            </div>
                          </div>

                          {/* Footer */}
                          <div className="bg-white border-t border-gray-100 px-3 py-2 flex justify-between font-mono text-[10px]">
                            <div className="flex flex-col">
                              <span className="text-[8px] text-gray-400 uppercase font-sans">Estimated Cost</span>
                              <span className="text-orange-900 font-bold">
                                {d.cost != null ? `₹${(d.cost/1e5).toFixed(2)} Lac/km` : '—'}
                              </span>
                            </div>
                            <div className="flex flex-col text-right">
                              <span className="text-[8px] text-gray-400 uppercase font-sans">Carbon Footprint</span>
                              <span className="text-emerald-700 font-bold">
                                {d.co2 != null ? `${d.co2.toFixed(0)} kg CO₂` : '—'}
                              </span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                ):<div className="text-red-600 text-xs">No feasible designs. Relax constraints.</div>}
              </div>
            ) : !optimizationMode && results ? (
              <table className="w-full min-w-[980px] text-[11px] text-left font-mono border-collapse leading-5">
                <thead className="bg-gray-50 text-[10px] text-gray-500 uppercase font-bold sticky top-0 z-20">
                  <tr className="text-[9px] tracking-wide">
                    <th colSpan={2} className="py-1 px-3 border-b border-gray-200 bg-gray-100/70">Location</th>
                    <th colSpan={4} className="py-1 px-3 border-b border-gray-200 bg-gray-100/70">Stress State</th>
                    <th className="py-1 px-3 border-b border-gray-200 bg-gray-100/70">Deflection</th>
                    <th colSpan={2} className="py-1 px-3 border-b border-gray-200 bg-orange-50 text-orange-800">Failure Checks</th>
                  </tr>
                  <tr>
                    <th className="py-2 px-3 border-b border-gray-200">Z (mm)</th>
                    <th className="py-2 px-3 border-b border-gray-200">R (mm)</th>
                    <th className="py-2 px-3 border-b border-gray-200">σ_z</th>
                    <th className="py-2 px-3 border-b border-gray-200">σ_t</th>
                    <th className="py-2 px-3 border-b border-gray-200">σ_r</th>
                    <th className="py-2 px-3 border-b border-gray-200">τ_rz</th>
                    <th className="py-2 px-3 border-b border-gray-200">δ_z</th>
                    <th className="py-2 px-3 border-b border-orange-200 border-l border-orange-200 bg-orange-50 text-red-700 sticky right-24 z-20">ε_z</th>
                    <th className="py-2 px-3 border-b border-orange-200 border-l border-orange-300 bg-orange-100 text-orange-900 sticky right-0 z-20">ε_t</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r,i)=>(
                    <tr key={i} className="border-b border-gray-100 hover:bg-orange-50/30">
                      <td className="py-1.5 px-3">{r.z.toFixed(1)}</td>
                      <td className="py-1.5 px-3">{r.r.toFixed(1)}</td>
                      <td className="py-1.5 px-3">{formatSci(r.sigma_z)}</td>
                      <td className="py-1.5 px-3">{formatSci(r.sigma_t)}</td>
                      <td className="py-1.5 px-3 text-gray-600">{formatSci(r.sigma_r)}</td>
                      <td className="py-1.5 px-3 text-gray-600">{formatSci(r.tau_rz)}</td>
                      <td className="py-1.5 px-3 text-gray-600">{formatSci(r.disp_z)}</td>
                      <td className="py-1.5 px-3 font-bold text-red-700 bg-orange-50 border-l border-orange-200 sticky right-24 z-10">{formatSci(r.eps_z)}</td>
                      <td className="py-1.5 px-3 font-bold text-orange-900 bg-orange-100 border-l border-orange-300 sticky right-0 z-10">{formatSci(r.eps_t)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : isSolving ? (
              <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-2">
                <div className="flex items-center gap-2">
                  <Loader2 size={20} className="animate-spin text-orange-500"/>
                  <span className="text-xs font-medium">{optimizationMode?'Optimizing design...':(solverStatus || 'Computing...')}</span>
                </div>
                {solverStatus && !optimizationMode && (
                  <span className="text-[10px] text-gray-400">First run loads the in-browser solver (~once per session)</span>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center h-full text-gray-300 text-xs">
                Run Evaluate or Optimize to see results here.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Help Modal */}
      {showInstructions && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-6 backdrop-blur-[2px]">
          <div className="bg-[var(--surface-panel)] rounded-xl shadow-2xl w-full max-w-4xl overflow-hidden flex flex-col h-[80vh] max-h-[750px] border border-[var(--hairline)]">
            <div className="flex justify-between items-center px-4 py-3 border-b border-[var(--hairline)] bg-[var(--surface-sunken)]">
              <h2 className="text-sm font-bold text-[var(--text-bold)] flex items-center gap-2">
                <Info size={16} className="text-orange-600"/> 
                <span>FlexPave Operations Manual & Usage Guide</span>
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
                        CAD Cockpit Layout & Overview
                      </h3>
                      <p className="mb-2">
                        FlexPave features a high-density, **Zero-Scroll CAD Cockpit** designed for professional engineering workflows. The interface is optimized to fit a single viewport:
                      </p>
                      <ul className="list-disc ml-5 space-y-1.5 mb-3 text-[11px]">
                        <li><strong>Header Toolbar:</strong> Main application triggers, use cases loading, Advanced panels, and project Import/Export.</li>
                        <li><strong>Left Settings Panel:</strong> Environment parameters, Design Traffic (MSA), Subgrade CBR (%), VG VG-grades temperature indices, and Axle parameters.</li>
                        <li><strong>Middle Layers Grid:</strong> Interactive physical layers configurator. Set moduli, Poisson's, thickness limits, costs, and carbon indices.</li>
                        <li><strong>Right CAD Visualizer:</strong> Live SVG schematic displaying layer thicknesses, wheel loading config, stress dissipation bulbs, and interactive analysis points.</li>
                      </ul>
                    </div>

                    <div className="border-t border-[var(--hairline)] pt-4">
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-2 flex items-center gap-1.5">
                        <span className="h-5 w-5 rounded-full bg-orange-100 dark:bg-orange-950/30 text-orange-700 dark:text-orange-400 flex items-center justify-center text-[10px] font-bold">2</span>
                        Step-by-Step Pavement Design Workflow
                      </h3>
                      <ol className="list-decimal ml-5 space-y-2 text-[11px]">
                        <li>
                          <strong>Define Trial Structure:</strong> In the central layers grid, specify layer materials, thicknesses ($h$ in mm), resilient modulus ($E$ in MPa), and Poisson's ratio ($\nu$).
                        </li>
                        <li>
                          <strong>Set Traffic and Subgrade parameters:</strong> Enter MSA and Subgrade CBR (%) in the left sidebar. The Resilient Modulus ($M_{RS}$) is calculated automatically using:
                          <div className="bg-[var(--surface-sunken)] p-2 rounded-md font-mono my-1.5 text-[10px] text-[var(--text-bold)] border border-[var(--hairline)]">
                            CBR ≤ 5%: MR = 10 × CBR (MPa) <br />
                            CBR &gt; 5%: MR = 17.6 × CBR^0.64 (MPa)
                          </div>
                        </li>
                        <li>
                          <strong>Set Loading Details:</strong> Define Total Wheel Load ($N$), Tyre Pressure (MPa), and Wheel Type (Single vs Dual). Dual wheels have a default spacing of $310\text{ mm}$ (center-to-center).
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
                        Use **Export** to download your complete project layout as a `.json` configuration file, and drag-and-drop or select it in **Import** to restore progress instantly.
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
                        FlexPave runs the mechanistic elastic layer solver (in-browser via Pyodide or via backend API) to compute stress, strain, and displacement fields at designated coordinates ($r$, $z$) under circular load patches. The soil subgrade is modeled as an infinitely deep elastic half-space.
                      </p>
                    </div>

                    <div className="border-t border-[var(--hairline)] pt-4">
                      <h3 className="text-sm font-bold text-[var(--text-bold)] mb-2">Primary Design Criteria (IRC:37-2019)</h3>
                      <p className="mb-3">
                        The solver validates structural adequacy against fatigue and rutting performance transfer functions defined by **IRC:37-2019**:
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
                          <span>• TIHAN1 (Corridor Spectrum)</span>
                          <span>Passed (error &lt; 1.5%)</span>
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
                        FlexPave deploys a two-phase deterministic search algorithm to optimize layer thicknesses ($h$) within specified boundary ranges (Min/Max limits):
                      </p>
                      <ul className="list-disc ml-5 space-y-1.5 text-[11px] mb-3">
                        <li><strong>Phase 1 (Greedy Climb):</strong> Starts from minimum layer thicknesses and increments the most cost-effective/cheapest layer in 5mm steps until the first structurally adequate design is found.</li>
                        <li><strong>Phase 2 (Boundary Sweep):</strong> Runs a fine grid sweep around the Phase 1 boundary (+/-20mm window) to search for alternate structural combinations that minimize total thickness, cost, or CO2.</li>
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
                        The optimizer filters and returns up to four unique archetype designs. You can click on any archetype card to load its parameters instantly:
                      </p>
                      
                      <div className="grid grid-cols-2 gap-3 text-[11px]">
                        <div className="border border-[var(--hairline)] p-2.5 rounded-lg">
                          <strong className="text-red-600 dark:text-red-400 block mb-1">🔴 Economy Archetype</strong>
                          <span>The thinnest structural adequate configuration. Minimizes material usage and initial capital cost.</span>
                        </div>
                        <div className="border border-[var(--hairline)] p-2.5 rounded-lg">
                          <strong className="text-yellow-600 dark:text-yellow-500 block mb-1">🟡 Balanced Archetype</strong>
                          <span>Midpoint design in normalized thickness/safety margin space. Represents the optimum value-for-money configuration.</span>
                        </div>
                        <div className="border border-[var(--hairline)] p-2.5 rounded-lg">
                          <strong className="text-green-600 dark:text-green-400 block mb-1">🟢 Premium Archetype</strong>
                          <span>The design that minimizes the Cumulative Damage Factor (CDF) to provide maximum structural safety and service life.</span>
                        </div>
                        <div className="border border-[var(--hairline)] p-2.5 rounded-lg">
                          <strong className="text-teal-600 dark:text-teal-400 block mb-1">🍀 Green (Carbon) Archetype</strong>
                          <span>The design that minimizes the total carbon footprint ($kg\ CO_2\ eq$) through eco-friendly layer thicknesses.</span>
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
                        FlexPave includes advanced modules to support modern mechanistic pavement design and materials stabilization:
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
                            Runs probabilistic simulations by applying standard deviations to layer thicknesses ($h$) and resilient moduli ($E$). Executing 200+ runs computes structural life distribution, evaluating failure risks against material and construction variability.
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
                            Enables geogrid interlayers (biaxial or triaxial) inside granular bases. Applies a **Modulus Improvement Factor (MIF)** (ranging from 1.5x to 2.0x) to granular sub-bases, allowing thinner structural thickness while maintaining design life.
                          </p>
                        </div>

                        <div>
                          <h4 className="font-bold text-[var(--text-bold)] text-[11px] mb-1">🚒 Cement Treated Base (CTB) Axle Spectrum Analysis</h4>
                          <p className="text-[11px]">
                            Enables damage evaluation for Cement Treated Bases using fatigue damage accumulation ($CFD \le 1.0$). Solves fatigue distress ratios against the CTB Modulus of Rupture ($M_R \approx 1.4\text{ MPa}$) across a full axle load spectrum array.
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
            layers, numLayers, load, pressure, wheelType, wheelSpacing,
            temperature, points, numPoints, cvpd, subgradeCbr,
            results, optimizedDesigns, materialRates,
            // Single source of truth for design assumptions used by every advanced module
            growthRate: DESIGN_DEFAULTS.growthRate,
            designLife: DESIGN_DEFAULTS.designLife,
            ldf: DESIGN_DEFAULTS.ldf,
            vdf: DESIGN_DEFAULTS.vdf,
            reliabilityPercent: DESIGN_DEFAULTS.reliabilityPercent,
          }}
          onClose={() => setShowAdvanced(false)}
          onUpdateLayer={(idx, props) => {
            if (props.E !== undefined) updateLayer(idx, 'E', props.E);
            if (props.nu !== undefined) updateLayer(idx, 'nu', props.nu);
          }}
        />
      )}
    </div>
  );
}
