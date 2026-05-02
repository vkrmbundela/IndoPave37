import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Save, Play, Settings, Plus, Trash2, ArrowRight, Table2, Loader2, Info, X, Download, Upload, Book, RotateCcw, Database, Layers, Zap, AlertCircle, MoreHorizontal
} from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
import AdvancedPanel from './v2/AdvancedPanel';
import KnowledgeAssistant from './v2/modules/knowledge/KnowledgeAssistant';

function cn(...inputs) {
  return twMerge(clsx(inputs));
}

/* ─── Drag-to-resize hook ─── */
function useSplitter(initialValue, direction) {
  const [size, setSize] = useState(initialValue);
  const dragging = useRef(false);
  const startPos = useRef(0);
  const startSize = useRef(0);

  const onMouseDown = useCallback((e) => {
    e.preventDefault();
    dragging.current = true;
    startPos.current = direction === 'horizontal' ? e.clientX : e.clientY;
    startSize.current = size;
    document.body.style.cursor = direction === 'horizontal' ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';

    const onMouseMove = (ev) => {
      if (!dragging.current) return;
      const delta = direction === 'horizontal'
        ? startPos.current - ev.clientX  // for right-side panel, dragging left = bigger
        : startPos.current - ev.clientY; // for bottom panel, dragging up = bigger
      const newSize = Math.max(100, startSize.current + delta);
      setSize(newSize);
    };

    const onMouseUp = () => {
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }, [size, direction]);

  return [size, onMouseDown];
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

const DEFAULT_LAYERS = [
  { id: '1', name: 'Layer 1', E: 1250, nu: 0.35, fixed_h: 40, min_h: 30, max_h: 50, is_fixed: true },
  { id: '2', name: 'Layer 2', E: 1250, nu: 0.35, fixed_h: 120, min_h: 50, max_h: 250, is_fixed: false },
  { id: '3', name: 'Layer 3', E: 371.37, nu: 0.35, fixed_h: 250, min_h: 150, max_h: 300, is_fixed: true },
  { id: '4', name: 'Layer 4', E: 143.43, nu: 0.35, fixed_h: 250, min_h: 150, max_h: 300, is_fixed: true },
  { id: '5', name: 'Subgrade', E: 55.4, nu: 0.40, fixed_h: 0, min_h: 0, max_h: 0, is_fixed: true },
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

/* ─── Compact Cross-Section SVG ─── */
function PavementVisualizer({ layers, points, wheelType }) {
  const surfaceY = 45;
  const svgW = 400, svgH = 240;
  const depth = svgH - surfaceY - 15;

  const finite = layers.slice(0, -1);
  const totalH = finite.reduce((s, l) => s + (l.is_fixed ? l.fixed_h : l.max_h), 0);
  const maxPt = Math.max(0, ...points.map(p => p.z));
  const target = Math.max(totalH + 100, maxPt + 80);
  const scale = depth / target;

  const colors = ['#1a1a1a','#374151','#52525b','#6b7280','#78716c','#57534e','#44403c','#292524','#1c1917','#0c0a09'];
  const sw = 340;
  const wSp = 310 * scale, wR = Math.max(5, 80 * scale);

  return (
    <svg viewBox={`0 0 ${svgW} ${svgH}`} className="w-full h-full" preserveAspectRatio="xMidYMid meet" style={{ background:'#f9fafb' }}>
      <g transform={`translate(${svgW/2},${surfaceY})`}>
        <line x1="0" y1={-surfaceY+6} x2="0" y2={depth+8} stroke="#d1d5db" strokeDasharray="3,3" strokeWidth="0.6"/>
        <text x="0" y={-surfaceY+14} textAnchor="middle" fontSize="6" fill="#9ca3af" fontWeight="600">CL</text>

        {layers.map((l,i) => {
          const sub = i===layers.length-1;
          const hmm = sub ? target : (l.is_fixed ? l.fixed_h : l.max_h);
          const hpx = hmm * scale;
          const dy = layers.slice(0,i).reduce((s,p)=>s+((p.is_fixed?p.fixed_h:p.max_h)*scale),0);
          // Ensure minimum visible height for thin layers
          const drawH = sub ? Math.max(hpx, depth+10-dy) : Math.max(hpx, 4);
          return (
            <g key={i}>
              <rect x={-sw/2} y={dy} width={sw} height={drawH}
                fill={colors[i%colors.length]} stroke="#fff" strokeWidth="0.4" opacity="0.85"/>
              {(drawH > 10 || sub) && (
                <text x={-sw/2+6} y={dy+(sub?14:drawH/2+3)} fontSize="6.5" fill="#fff" fontWeight="700" opacity="0.9">
                  {sub ? 'Subgrade' : `L${i+1} ${l.is_fixed?l.fixed_h:`${l.min_h}-${l.max_h}`}mm`}
                </text>
              )}
            </g>
          );
        })}

        {wheelType==='Dual' ? (
          <>
            <rect x={-wSp/2-wR} y={-22} width={wR*2} height={22} rx="2" fill="#dc2626"/>
            <rect x={wSp/2-wR} y={-22} width={wR*2} height={22} rx="2" fill="#dc2626"/>
            <text x={0} y={-25} textAnchor="middle" fontSize="5.5" fill="#991b1b" fontWeight="700">DUAL</text>
          </>
        ) : (
          <>
            <rect x={-wR} y={-22} width={wR*2} height={22} rx="2" fill="#dc2626"/>
            <text x={0} y={-25} textAnchor="middle" fontSize="5.5" fill="#991b1b" fontWeight="700">SINGLE</text>
          </>
        )}

        {points.map((p,i) => {
          const px=p.r*scale, py=p.z*scale;
          return (
            <g key={i}>
              <line x1={px-4} y1={py} x2={px+4} y2={py} stroke="#16a34a" strokeWidth="1"/>
              <line x1={px} y1={py-4} x2={px} y2={py+4} stroke="#16a34a" strokeWidth="1"/>
              <circle cx={px} cy={py} r="2.5" fill="none" stroke="#16a34a" strokeWidth="0.8"/>
              <text x={px+5} y={py+2.5} fontSize="5.5" fill="#15803d" fontWeight="700">P{i+1}</text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

export default function App() {
  // Load initial state from localStorage if available
  const savedData = JSON.parse(localStorage.getItem('flexpave_cache') || '{}');

  const [layers, setLayers] = useState(savedData.layers || DEFAULT_LAYERS);
  const [numLayers, setNumLayers] = useState(savedData.numLayers || 5);
  const [load, setLoad] = useState(savedData.load || 20000);
  const [pressure, setPressure] = useState(savedData.pressure || 0.56);
  const [wheelType, setWheelType] = useState(savedData.wheelType || 'Dual');
  const [points, setPoints] = useState(savedData.points || DEFAULT_POINTS);
  const [numPoints, setNumPoints] = useState(savedData.numPoints || 4);
  const [cvpd, setCvpd] = useState(savedData.cvpd || 800);
  const [subgradeCbr, setSubgradeCbr] = useState(savedData.subgradeCbr || 8);
  const [temperature, setTemperature] = useState(savedData.temperature || 35);

  const [results, setResults] = useState(savedData.results || null);
  const [error, setError] = useState(null);
  const [isSolving, setIsSolving] = useState(false);
  const [optimizationMode, setOptimizationMode] = useState(savedData.optimizationMode || false);
  const [optimizedDesigns, setOptimizedDesigns] = useState(savedData.optimizedDesigns || null);
  const [showInstructions, setShowInstructions] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [hasStarted, setHasStarted] = useState(savedData.hasStarted || false);
  const fileInputRef = useRef(null);

  // Resizable splitters
  const [previewWidth, onPreviewDrag] = useSplitter(savedData.previewWidth || 300, 'horizontal');
  const [bottomHeight, onBottomDrag] = useSplitter(savedData.bottomHeight || 280, 'vertical');

  // Auto-Save Effect
  useEffect(() => {
    const dataToSave = {
      layers, numLayers, load, pressure, wheelType, points, numPoints,
      cvpd, subgradeCbr, temperature, results, optimizationMode, 
      optimizedDesigns, hasStarted, previewWidth, bottomHeight
    };
    localStorage.setItem('flexpave_cache', JSON.stringify(dataToSave));
  }, [
    layers, numLayers, load, pressure, wheelType, points, numPoints,
    cvpd, subgradeCbr, temperature, results, optimizationMode, 
    optimizedDesigns, hasStarted, previewWidth, bottomHeight
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

  useEffect(() => {
    setLayers(prev => {
      const c = [...prev];
      while (c.length < numLayers) c.splice(c.length-1,0,{ id:String(c.length), name:`Layer ${c.length}`, E:500, nu:0.35, fixed_h:100, min_h:50, max_h:200, is_fixed:true });
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

  const doSingleRun = async (overrides = null) => {
    setIsSolving(true); setError(null); setResults(null); setOptimizedDesigns(null); setOptimizationMode(false);
    try {
      // Logic: If overrides is a demo object (has layers), use it; 
      // otherwise (if it's a click event or null), use current state.
      const isDemo = overrides && overrides.layers;
      const targetLayers = isDemo ? overrides.layers : layers;
      const targetLoad = isDemo ? overrides.load : load;
      const targetPressure = isDemo ? overrides.pressure : pressure;
      const targetWheelType = isDemo ? overrides.wheelType : wheelType;
      const targetPoints = isDemo ? overrides.points : points;

      const res = await fetch(`${API_BASE}/api/solve`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          layers: targetLayers.map((l, i) => ({
            E: l.E,
            nu: l.nu,
            h: i === targetLayers.length - 1 ? 0 : (l.is_fixed ? (l.fixed_h || 0) : (l.min_h || 0))
          })),
          wheel_load: targetLoad,
          tire_pressure: targetPressure,
          wheel_type: targetWheelType,
          points: targetPoints.map(p => ({ z: p.z, r: p.r })),
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `Server ${res.status}`);
      }
      const data = await res.json();
      setResults(data.results || []);
    } catch(e) { setError(e.message); }
    finally { setIsSolving(false); }
  };

  const doOptimize = async () => {
    setIsSolving(true); setError(null); setOptimizedDesigns(null); setResults(null); setOptimizationMode(true);
    try {
      const res = await fetch(`${API_BASE}/api/optimize`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          layers: layers.map(l=>({
            layer_type: l.name,
            E: l.E,
            nu: l.nu,
            is_fixed: l.is_fixed,
            fixed_thickness: l.fixed_h || 0,
            min_thickness: l.min_h || 0,
            max_thickness: l.max_h || 0
          })),
          cvpd,
          subgrade_cbr: subgradeCbr,
          temperature,
          growth_rate: 0.05, // Fixed: Use fraction (e.g., 0.05 for 5%) to avoid astronomical traffic
          design_life: 20,  // Default 20 years
          wheel_load: load,
          tire_pressure: pressure,
          wheel_type: wheelType,
          points: points.map(p=>({z:p.z, r:p.r})),
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `Server ${res.status}`);
      }
      const data = await res.json();
      setOptimizedDesigns(data.adequate_designs || []);
    } catch(e) { setError(e.message); }
    finally { setIsSolving(false); }
  };

  const handleExport = () => {
    const cfg = {layers,numLayers,load,pressure,wheelType,points,numPoints,cvpd,subgradeCbr,temperature};
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

  const inp = "bg-white border border-gray-300 rounded px-1.5 py-0.5 text-xs text-gray-800 outline-none focus:border-orange-500 font-mono";
  const formatSci = (v) => {
    if (v === undefined || v === null) return '—';
    const n = Number(v);
    return Number.isFinite(n) ? n.toExponential(4) : '—';
  };

  /* ── SPLASH ── */
  if (!hasStarted) {
    return (
      <div className="min-h-[100svh] min-h-[100dvh] w-full bg-gray-100 flex items-center justify-center font-sans">
        <input type="file" ref={fileInputRef} onChange={handleImport} accept=".json" className="hidden"/>
        <div className="bg-white border border-gray-300 rounded-3xl shadow-2xl p-12 flex flex-col items-center max-w-sm w-full text-center">
          <div className="flex flex-col items-center mb-12">
            <img src="/assets/logo_mark.png" alt="FlexPave Icon" className="h-40 w-auto mb-6 drop-shadow-lg" />
            <h1 className="text-4xl font-black text-slate-900 tracking-tight uppercase">FLEXPAVE</h1>
          </div>
          <div className="flex w-full gap-3">
            <button onClick={()=>setHasStarted(true)} className="flex-1 bg-orange-600 hover:bg-orange-700 text-white font-bold py-3 rounded-lg text-sm flex items-center justify-center gap-1.5 transition-all shadow-md hover:shadow-lg active:scale-95"><Plus size={18}/> New Project</button>
            <button onClick={()=>fileInputRef.current?.click()} className="flex-1 bg-white hover:bg-gray-50 text-gray-700 font-bold py-3 rounded-lg text-sm border border-gray-300 flex items-center justify-center gap-1.5 transition-all shadow-sm hover:shadow-md active:scale-95"><Upload size={18}/> Import</button>
          </div>
          <div className="mt-6 pt-4 border-t border-gray-200 w-full text-[10px] text-gray-400">
            <p className="font-semibold text-gray-500">Vikramaditya Shah Bundela</p>
            <p className="mt-0.5">Verify designs per IRC:37 before construction.</p>
          </div>
        </div>
      </div>
    );
  }

  /* ── MAIN DASHBOARD ── */
  return (
    <div className="min-h-[100svh] min-h-[100dvh] w-full bg-gray-100 text-gray-800 font-sans flex flex-col overflow-hidden">

      {/* TOOLBAR */}
      <div className="flex-none flex items-center justify-between bg-white border-b border-gray-300 px-3 py-1.5">
        <div className="flex items-center gap-2.5">
          <img src="/assets/logo_mark.png" alt="FlexPave" className="h-7 w-auto" />
          <span className="text-sm font-bold text-slate-900 tracking-tight">FlexPave</span>
          <span className="text-[10px] text-gray-400 ml-0.5">v1.0</span>
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

      {/* WORKSPACE: top row (inputs + preview) and bottom row (results) */}
      <div className="flex-1 flex flex-col overflow-hidden min-h-0">

        {/* ═══ TOP HALF: Inputs + Preview ═══ */}
        <div style={{ height: `calc(100% - ${bottomHeight}px)` }} className="flex min-h-0 overflow-hidden">

          {/* ── Left: All inputs ── */}
          <div className="flex-1 flex flex-col min-h-0 overflow-y-auto bg-white min-w-0">

            {/* Layer Table */}
            <div className="px-3 pt-2 pb-1.5 border-b border-gray-100">
              <div className="flex justify-between items-center mb-1">
                <span className="text-[11px] font-bold uppercase text-gray-500 tracking-wide">Layer Structure</span>
                <div className="flex items-center gap-1">
                  <label className="text-[10px] text-gray-400">Layers:</label>
                  <select value={numLayers} onChange={e=>setNumLayers(parseInt(e.target.value))}
                    className="border border-gray-300 rounded px-1 py-0.5 text-[11px] font-bold text-gray-700 bg-white outline-none cursor-pointer">
                    {[2,3,4,5,6,7,8,9,10].map(n=><option key={n} value={n}>{n}</option>)}
                  </select>
                </div>
              </div>
              <table className="w-full text-[11px] border-collapse">
                <thead>
                  <tr className="bg-gray-50 text-[10px] text-gray-500 uppercase font-semibold">
                    <th className="text-left py-1 px-1.5 border-b border-gray-200 w-20">Layer</th>
                    <th className="text-center py-1 px-1 border-b border-gray-200 w-12">Mode</th>
                    <th className="text-left py-1 px-1.5 border-b border-gray-200 w-20">E (MPa)</th>
                    <th className="text-left py-1 px-1.5 border-b border-gray-200 w-16">ν</th>
                    <th className="text-left py-1 px-1.5 border-b border-gray-200">Thickness (mm)</th>
                  </tr>
                </thead>
                <tbody>
                  {layers.map((l,i)=>{
                    const sub = i===layers.length-1;
                    return (
                      <tr key={i} className="border-b border-gray-100 hover:bg-orange-50/30">
                        <td className="py-1 px-1.5 font-semibold text-gray-700">{sub?'Subgrade':`Layer ${i+1}`}</td>
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
            <div className="px-3 py-2 flex gap-3 items-stretch">

              {/* Analysis Points — proper mini table */}
              <fieldset className="flex-1 border border-gray-200 rounded px-2 pt-0.5 pb-1.5 min-w-0">
                <legend className="text-[10px] font-bold uppercase text-gray-400 tracking-wide px-1 flex items-center gap-1">
                  Analysis Points
                  <select value={numPoints} onChange={e=>setNumPoints(parseInt(e.target.value))}
                    className="border border-gray-300 rounded px-1 py-0 text-[10px] font-bold text-gray-600 bg-white outline-none cursor-pointer ml-1">
                    {[1,2,3,4,5,6,7,8,9,10].map(n=><option key={n} value={n}>{n}</option>)}
                  </select>
                </legend>
                <table className="w-full text-[11px] border-collapse">
                  <thead>
                    <tr className="text-[9px] text-gray-400 uppercase font-semibold">
                      <th className="text-left py-0.5 w-7">#</th>
                      <th className="text-left py-0.5">Z (mm)</th>
                      <th className="text-left py-0.5">R (mm)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {points.map((p,i)=>(
                      <tr key={i}>
                        <td className="py-0.5 font-bold text-gray-400 text-[10px]">{i+1}</td>
                        <td className="py-0.5 pr-1"><input type="number" value={p.z} onChange={e=>updatePoint(i,'z',Number(e.target.value))} className={cn(inp,"w-full py-0")}/></td>
                        <td className="py-0.5"><input type="number" value={p.r} onChange={e=>updatePoint(i,'r',Number(e.target.value))} className={cn(inp,"w-full py-0")}/></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
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
                </div>
              </fieldset>

              {/* Optimization Target */}
              <fieldset className="border border-gray-200 rounded px-2 pt-0.5 pb-1.5 w-36 flex-none">
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
                </div>
              </fieldset>

              {/* Action Buttons */}
              <div className="flex flex-col gap-1.5 justify-center flex-none">
                <button onClick={doSingleRun} disabled={isSolving}
                  className="bg-orange-600 hover:bg-orange-700 disabled:bg-gray-300 text-white font-bold px-5 py-2 rounded text-[11px] flex items-center justify-center gap-1 uppercase tracking-wide transition-colors w-28 select-none shadow-sm">
                  {isSolving&&!optimizationMode?<Loader2 size={12} className="animate-spin"/>:<Play size={12}/>} Evaluate
                </button>
                <button onClick={doOptimize} disabled={isSolving}
                  className="bg-white hover:bg-slate-50 disabled:bg-gray-100 text-slate-700 disabled:text-gray-400 border border-slate-300 font-bold px-5 py-2 rounded text-[11px] flex items-center justify-center gap-1 uppercase tracking-wide transition-colors w-28 select-none">
                  {isSolving&&optimizationMode?<Loader2 size={12} className="animate-spin"/>:<ArrowRight size={12}/>} Optimize
                </button>
              </div>
            </div>
          </div>

          {/* ── Vertical Splitter ── */}
          <div className="relative w-1.5 flex-none group">
            <div
              onMouseDown={onPreviewDrag}
              className="absolute -left-2 -right-2 top-0 bottom-0 cursor-col-resize z-10 select-none"
              title="Drag to resize"
            />
            <div className="absolute inset-0 pointer-events-none bg-gray-200 group-hover:bg-orange-400 group-active:bg-orange-500 transition-colors" />
          </div>

          {/* ── Right: Compact Preview ── */}
          <div style={{ width: previewWidth }} className="flex-none flex flex-col bg-gray-50 min-h-0">
            <div className="flex-none px-2 py-1 bg-white border-b border-gray-200 text-[10px] font-bold text-gray-500 uppercase tracking-wider">
              Cross Section Preview
            </div>
            <div className="flex-1 p-1.5 flex items-center justify-center min-h-0 overflow-hidden">
              <PavementVisualizer layers={layers} points={points} wheelType={wheelType}/>
            </div>
          </div>
        </div>

        {/* ── Horizontal Splitter ── */}
        <div className="relative h-1.5 flex-none group">
          <div
            onMouseDown={onBottomDrag}
            className="absolute left-0 right-0 -top-2 -bottom-2 cursor-row-resize z-10 select-none"
            title="Drag to resize"
          />
          <div className="absolute inset-0 pointer-events-none bg-gray-200 group-hover:bg-orange-400 group-active:bg-orange-500 transition-colors" />
        </div>

        {/* ═══ BOTTOM: Results ═══ */}
        <div style={{ height: bottomHeight }} className="flex-none flex flex-col bg-white min-h-0 overflow-hidden">
          <div className="flex-none px-3 py-1 bg-white border-b border-gray-200 flex items-center justify-between">
            <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wide flex items-center gap-1"><Table2 size={12}/> Output Results</span>
            {results && !optimizationMode && <span className="text-[10px] text-gray-400">{results.length} point(s)</span>}
          </div>
          <div className="flex-1 overflow-auto min-h-0">
            {error && <div className="m-2 text-red-700 bg-red-50 border border-red-200 p-2 rounded text-xs">{error}</div>}

            {optimizationMode && optimizedDesigns ? (
              <div className="p-3">
                <div className="text-[10px] font-bold text-gray-500 uppercase mb-2">Pareto-Optimal Designs</div>
                {optimizedDesigns.length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                      {optimizedDesigns.slice(0, 12).map((d, i) => (
                        <div key={i} className="border border-gray-200 rounded-lg shadow-sm bg-white overflow-hidden flex flex-col">
                          {/* Card Header */}
                          <div className="bg-gray-50 px-3 py-2 border-b border-gray-100 flex justify-between items-center">
                            <div className="flex items-center gap-2">
                              <span className="bg-orange-100 text-orange-800 text-[10px] font-bold px-1.5 py-0.5 rounded shadow-sm uppercase">OPTION #{i + 1}</span>
                              <span className={cn(
                                "text-[10px] font-bold px-1.5 py-0.5 rounded uppercase shadow-sm",
                                d.details?.strategy === 'Economy' ? 'bg-emerald-100 text-emerald-800' :
                                d.details?.strategy === 'Balanced' ? 'bg-sky-100 text-sky-800' :
                                d.details?.strategy === 'Premium' ? 'bg-indigo-100 text-indigo-800' :
                                'bg-slate-100 text-slate-800'
                              )}>
                                {d.details?.strategy || 'Design'}
                              </span>
                            </div>
                            <span className="text-xs font-bold text-gray-800 flex items-center gap-1">
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
                              <span className="text-orange-900 font-bold">₹{(d.cost/1e5).toFixed(2)} Lac/km</span>
                            </div>
                            <div className="flex flex-col text-right">
                              <span className="text-[8px] text-gray-400 uppercase font-sans">Carbon Footprint</span>
                              <span className="text-emerald-700 font-bold">{d.co2.toFixed(0)} kg CO₂</span>
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
              <div className="flex items-center justify-center h-full text-gray-400 gap-2">
                <Loader2 size={20} className="animate-spin text-orange-500"/>
                <span className="text-xs font-medium">{optimizationMode?'Optimizing design...':'Computing...'}</span>
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
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-6">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-xl overflow-hidden flex flex-col max-h-[85vh] border border-gray-300">
            <div className="flex justify-between items-center px-4 py-2.5 border-b border-gray-200 bg-gray-50">
              <h2 className="text-sm font-bold text-gray-800 flex items-center gap-1.5"><Info size={16} className="text-orange-600"/> Usage Guide</h2>
              <button onClick={()=>setShowInstructions(false)} className="text-gray-400 hover:text-gray-700 p-0.5 rounded hover:bg-gray-200"><X size={16}/></button>
            </div>
            <div className="p-4 overflow-y-auto flex flex-col gap-6 text-xs text-gray-700 leading-relaxed">
              {/* Step 1: Layer Configuration */}
              <div>
                <h3 className="font-bold text-gray-900 mb-2 flex items-center gap-1.5 border-b border-gray-100 pb-1">
                  <span className="bg-orange-100 text-orange-800 w-5 h-5 flex items-center justify-center rounded-full text-[10px]">1</span>
                  Layer & Load Configuration
                </h3>
                <ul className="list-disc ml-5 space-y-1.5">
                  <li><strong>Layer Table:</strong> Enter Elastic Modulus (E), Poisson's ratio (nu), and Thickness. The Subgrade is treated as semi-infinite.</li>
                  <li><strong>Mode Toggle:</strong> Use <span className="text-teal-700 bg-teal-50 px-1 rounded border border-teal-200">Fixed</span> for specific designs or <span className="text-orange-700 bg-orange-50 px-1 rounded border border-orange-200">Opt</span> to let the optimizer find range-based solutions.</li>
                  <li><strong>Load Config:</strong> Set Total Wheel Load (N) and Tyre Pressure (MPa). Select <strong>Single</strong> or <strong>Dual</strong> wheel configuration.</li>
                  <li><strong>Analysis Points:</strong> Define Z (depth) and R (radial) coordinates where you want to compute stresses/strains.</li>
                </ul>
              </div>

              {/* Step 2: Running the Solver */}
              <div>
                <h3 className="font-bold text-gray-900 mb-2 flex items-center gap-1.5 border-b border-gray-100 pb-1">
                  <span className="bg-orange-100 text-orange-800 w-5 h-5 flex items-center justify-center rounded-full text-[10px]">2</span>
                  Execution Modes
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-gray-50 p-2 rounded border border-gray-200">
                    <p className="font-bold text-orange-700 mb-1 flex items-center gap-1"><Play size={10}/> Evaluate</p>
                    <p className="text-[10px] leading-snug">Performs linear elastic analysis on fixed thicknesses. Best for checking a known structure against IRC:37 limits.</p>
                  </div>
                  <div className="bg-gray-50 p-2 rounded border border-gray-200">
                    <p className="font-bold text-orange-700 mb-1 flex items-center gap-1"><ArrowRight size={10}/> Optimize</p>
                    <p className="text-[10px] leading-snug">Uses Smart Pavement Search to find structurally adequate designs that minimize thickness while meeting IRC:37 criteria.</p>
                  </div>
                </div>
              </div>

              {/* Step 3: Result Interpretation */}
              <div>
                <h3 className="font-bold text-gray-900 mb-2 flex items-center gap-1.5 border-b border-gray-100 pb-1">
                  <span className="bg-orange-100 text-orange-800 w-5 h-5 flex items-center justify-center rounded-full text-[10px]">3</span>
                  Interpreting Results
                </h3>
                <p className="mb-2">The output table highlights two critical pavement failure parameters per IRC:37:</p>
                <div className="flex flex-col gap-2">
                  <div className="flex items-start gap-2">
                    <code className="bg-orange-50 px-1.5 py-0.5 rounded text-red-600 font-mono font-bold shrink-0">ε_z</code>
                    <p className="text-[10px]"><strong>Vertical Subgrade Strain:</strong> High values indicate potential <strong>Rutting</strong> failure in the subgrade.</p>
                  </div>
                  <div className="flex items-start gap-2">
                    <code className="bg-orange-50 px-1.5 py-0.5 rounded text-orange-800 font-mono font-bold shrink-0">ε_t</code>
                    <p className="text-[10px]"><strong>Tensile Strain:</strong> Measured at the bottom of the bituminous layer. High values indicate potential <strong>Fatigue Cracking</strong>.</p>
                  </div>
                </div>
              </div>

              {/* Step 4: UI Cockpit Controls */}
              <div className="bg-orange-50/50 p-3 rounded-md border border-orange-100">
                <h3 className="font-bold text-orange-900 mb-1 text-[11px] flex items-center gap-1"><Settings size={12}/> Pro-User Controls</h3>
                <ul className="list-disc ml-5 text-[10px] space-y-1 text-orange-800">
                  <li><strong>Resizable HUD:</strong> Drag the thin gray splitters to expand the Layer table, Visualizer, or Results view.</li>
                  <li><strong>Visualizer:</strong> Real-time animation of layer thicknesses and analysis point locations.</li>
                  <li><strong>Data Handling:</strong> Use <strong>Export</strong> to save your current project state as a .JSON file and <strong>Import</strong> to resume later.</li>
                </ul>
              </div>
            </div>
            <div className="px-4 py-2.5 border-t border-gray-200 bg-gray-50 flex justify-end">
              <button onClick={()=>setShowInstructions(false)} className="px-4 py-1.5 bg-orange-600 hover:bg-orange-700 text-white font-bold rounded text-xs">Close</button>
            </div>
          </div>
        </div>
      )}

      {showKnowledge && (
        <div className="fixed bottom-24 right-5 z-[70] w-[min(92vw,430px)] h-[min(74vh,640px)] bg-white/95 backdrop-blur-md rounded-2xl shadow-2xl border border-orange-200 overflow-hidden flex flex-col">
          <div className="flex justify-between items-center px-3 py-2.5 border-b border-orange-200 bg-gradient-to-r from-slate-800 to-slate-700 text-white">
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-full bg-white/15 border border-white/20 flex items-center justify-center">
                <Book size={14} className="text-orange-300" />
              </div>
              <div>
                <h2 className="text-xs font-bold tracking-wide uppercase">FlexPave Bot</h2>
                <p className="text-[10px] text-slate-200">Ask questions in plain language</p>
              </div>
            </div>
            <button onClick={()=>setShowKnowledge(false)} className="text-slate-200 hover:text-white p-1 rounded hover:bg-white/10"><X size={14}/></button>
          </div>
          <KnowledgeAssistant apiBase={API_BASE} />
        </div>
      )}

      <button
        onClick={() => setShowKnowledge(v => !v)}
        className={cn(
          "fixed bottom-5 right-5 z-[75] h-14 w-14 rounded-full shadow-xl border flex items-center justify-center transition-all duration-200",
          showKnowledge
            ? "bg-slate-800 border-slate-700 text-white hover:bg-slate-900"
            : "bg-orange-500 border-orange-400 text-white hover:bg-orange-600"
        )}
        title={showKnowledge ? "Close FlexPave Bot" : "Open FlexPave Bot"}
      >
        {showKnowledge ? <X size={20} /> : <Book size={20} />}
      </button>

      {showAdvanced && (
        <AdvancedPanel
          sharedState={{ layers, numLayers, load, pressure, wheelType, temperature, points, numPoints, cvpd, subgradeCbr, results, optimizedDesigns }}
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
