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

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('flexpave_advanced') || '{}');
      saved.activeTab = activeTab;
      localStorage.setItem('flexpave_advanced', JSON.stringify(saved));
    } catch {
      // Ignore localStorage persistence failures.
    }
  }, [activeTab]);

  useEffect(() => {
    const handleKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const renderContent = () => {
    switch (activeTab) {
      case 'reserve':
        return <ReserveMeter sharedState={sharedState} />;
      case 'materials':
        return <MaterialPicker sharedState={sharedState} onUpdateLayer={onUpdateLayer} />;
      case 'sensitivity':
        return <SensitivityHeatmap sharedState={sharedState} />;
      case 'strainbulb':
        return (
          <Suspense fallback={<div className="flex-1 flex items-center justify-center p-8"><div className="animate-spin rounded-full h-8 w-8 border-2 border-orange-200 border-t-orange-600" /></div>}>
            <StrainBulbViewer sharedState={sharedState} />
          </Suspense>
        );
      case 'corridor':
        return <CorridorOptimizer sharedState={sharedState} />;
      case 'montecarlo':
        return <MonteCarloPanel sharedState={sharedState} />;
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
            CBR {sharedState.subgradeCbr}% | {sharedState.cvpd} CVPD
          </span>
          <span>{sharedState.results?.length > 0 ? 'Results available' : 'No results — run Evaluate first'}</span>
        </div>
      </div>
    </div>
  );
}
