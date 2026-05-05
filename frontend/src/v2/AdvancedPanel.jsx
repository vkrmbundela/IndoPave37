import React, { useState, useEffect, Suspense, lazy } from 'react';
import {
  X, Zap, Gauge, BookOpen, Grid3x3, Box, Route, Dice5,
} from 'lucide-react';
import { AdvancedProvider } from './AdvancedContext';
import ReserveMeter from './modules/reserve/ReserveMeter';
import MaterialPicker from './modules/materials/MaterialPicker';
import SensitivityHeatmap from './modules/sensitivity/SensitivityHeatmap';
import CorridorOptimizer from './modules/corridor/CorridorOptimizer';
import MonteCarloPanel from './modules/montecarlo/MonteCarloPanel';

const DEFAULT_CTB_AXLE_SPECTRUM_TEXT = JSON.stringify([
  { axle_type: 'single', load_kn: 80, expected_repetitions: 1000000 },
  { axle_type: 'tandem', load_kn: 120, expected_repetitions: 200000 },
  { axle_type: 'tridem', load_kn: 180, expected_repetitions: 50000 },
], null, 2);

const StrainBulbViewer = lazy(() => import('./modules/strainbulb/StrainBulbViewer'));

const TABS = [
  { id: 'reserve',      label: 'Reserve Meter',  icon: Gauge,   active: true },
  { id: 'materials',    label: 'Material Library',icon: BookOpen, active: true },
  { id: 'sensitivity',  label: 'Sensitivity',     icon: Grid3x3, active: true },
  { id: 'strainbulb',   label: '3D Strain Bulbs', icon: Box,     active: true },
  { id: 'corridor',     label: 'Corridor Opt.',   icon: Route,   active: true },
  { id: 'montecarlo',   label: 'Monte Carlo',     icon: Dice5,   active: true },
];

export default function AdvancedPanel({ sharedState, onClose, onUpdateLayer }) {
  const [activeTab, setActiveTab] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('flexpave_advanced') || '{}');
      return saved.activeTab || 'reserve';
    } catch { return 'reserve'; }
  });
  const [useCtbSpectrum, setUseCtbSpectrum] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('flexpave_advanced') || '{}');
      return saved.useCtbSpectrum || false;
    } catch { return false; }
  });
  const [ctbSpectrumText, setCtbSpectrumText] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('flexpave_advanced') || '{}');
      return saved.ctbSpectrumText || '';
    } catch { return ''; }
  });
  const [ctbPerClassBridgeRecompute, setCtbPerClassBridgeRecompute] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('flexpave_advanced') || '{}');
      return saved.ctbPerClassBridgeRecompute || false;
    } catch { return false; }
  });

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('flexpave_advanced') || '{}');
      saved.activeTab = activeTab;
      saved.useCtbSpectrum = useCtbSpectrum;
      saved.ctbSpectrumText = ctbSpectrumText;
      saved.ctbPerClassBridgeRecompute = ctbPerClassBridgeRecompute;
      localStorage.setItem('flexpave_advanced', JSON.stringify(saved));
    } catch {
      // Ignore localStorage persistence failures.
    }
  }, [activeTab, useCtbSpectrum, ctbSpectrumText, ctbPerClassBridgeRecompute]);

  useEffect(() => {
    const handleKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const advancedSharedState = {
    ...sharedState,
    useCtbSpectrum,
    ctbSpectrumText,
    ctbPerClassBridgeRecompute,
  };

  const renderContent = () => {
    switch (activeTab) {
      case 'reserve':
        return <ReserveMeter sharedState={advancedSharedState} />;
      case 'materials':
        return <MaterialPicker sharedState={advancedSharedState} onUpdateLayer={onUpdateLayer} />;
      case 'sensitivity':
        return <SensitivityHeatmap sharedState={advancedSharedState} />;
      case 'strainbulb':
        return (
          <Suspense fallback={<div className="flex-1 flex items-center justify-center p-8"><div className="animate-spin rounded-full h-8 w-8 border-2 border-orange-200 border-t-orange-600" /></div>}>
            <StrainBulbViewer sharedState={advancedSharedState} />
          </Suspense>
        );
      case 'corridor':
        return <CorridorOptimizer sharedState={advancedSharedState} />;
      case 'montecarlo':
        return <MonteCarloPanel sharedState={advancedSharedState} />;
      default:
        return null;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-white rounded-lg shadow-2xl flex flex-col overflow-hidden"
        style={{ width: 'calc(100vw - 64px)', height: 'calc(100vh - 64px)' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex-none flex items-center justify-between px-4 py-2.5 border-b border-gray-200 bg-gray-50">
          <div className="flex items-center gap-2">
            <Zap size={16} className="text-orange-600" />
            <span className="text-sm font-bold text-gray-900">Advanced Analysis</span>
            <span className="text-[10px] text-gray-400 bg-orange-50 border border-orange-200 rounded px-1.5 py-0.5 font-medium">v2</span>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-gray-200 rounded transition-colors">
            <X size={16} className="text-gray-500" />
          </button>
        </div>

        {/* CTB Spectrum Settings */}
        <div className="flex-none border-b border-orange-100 bg-orange-50/60 px-4 py-2">
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-gray-700">
            <label className="flex items-center gap-2 cursor-pointer select-none font-medium">
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
              CTB spectrum
            </label>
            <label className="flex items-center gap-2 cursor-pointer select-none font-medium">
              <input
                type="checkbox"
                checked={ctbPerClassBridgeRecompute}
                onChange={e => setCtbPerClassBridgeRecompute(e.target.checked)}
              />
              Per-class bridge recompute
            </label>
            <button
              type="button"
              onClick={() => {
                setUseCtbSpectrum(true);
                setCtbSpectrumText(DEFAULT_CTB_AXLE_SPECTRUM_TEXT);
              }}
              className="ml-auto px-2 py-1 rounded border border-orange-200 bg-white text-orange-700 hover:bg-orange-100 text-[10px] font-semibold"
            >
              Load example spectrum
            </button>
          </div>
          <textarea
            value={ctbSpectrumText}
            onChange={e => setCtbSpectrumText(e.target.value)}
            rows={4}
            spellCheck={false}
            placeholder={DEFAULT_CTB_AXLE_SPECTRUM_TEXT}
            className="mt-2 w-full rounded border border-orange-200 bg-white px-2 py-1 font-mono text-[10px] leading-4 text-gray-700 outline-none focus:border-orange-400 resize-y"
          />
          <p className="mt-1 text-[10px] text-gray-500">
            Format: array of {`{ axle_type, load_kn, expected_repetitions }`} objects. The corridor panel will read these settings when CTB spectrum mode is enabled.
          </p>
        </div>

        {/* Tab Bar */}
        <div className="flex-none flex items-center gap-0.5 px-3 py-1.5 border-b border-gray-100 bg-white overflow-x-auto">
          {TABS.map(tab => {
            const Icon = tab.icon;
            const isActive = tab.id === activeTab;
            const isEnabled = tab.active;
            return (
              <button
                key={tab.id}
                onClick={() => isEnabled && setActiveTab(tab.id)}
                disabled={!isEnabled}
                title={!isEnabled ? 'Coming Soon' : tab.label}
                className={`
                  flex items-center gap-1.5 px-3 py-1.5 rounded text-[11px] font-medium whitespace-nowrap transition-all
                  ${isActive
                    ? 'bg-orange-50 text-orange-800 border border-orange-200 shadow-sm'
                    : isEnabled
                      ? 'text-gray-600 hover:bg-gray-50 hover:text-gray-800 border border-transparent'
                      : 'text-gray-300 cursor-not-allowed border border-transparent'
                  }
                `}
              >
                <Icon size={12} />
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Content */}
        <AdvancedProvider>
          <div className="flex-1 overflow-y-auto min-h-0">
            {renderContent()}
          </div>
        </AdvancedProvider>

        {/* Footer - Status Bar */}
        <div className="flex-none flex items-center justify-between px-4 py-1.5 border-t border-gray-100 bg-gray-50 text-[10px] text-gray-400">
          <span>
            {sharedState.numLayers} layers | {sharedState.wheelType} {sharedState.load}N |
            CBR {sharedState.subgradeCbr}% | {sharedState.cvpd} CVPD |
            CTB {useCtbSpectrum ? 'spectrum on' : 'reference'}
          </span>
          <span>{sharedState.results?.length > 0 ? 'Results available' : 'No results — run Evaluate first'}</span>
        </div>
      </div>
    </div>
  );
}
