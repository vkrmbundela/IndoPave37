import React, { useEffect, useState } from 'react';
import { BookOpen, Search, ArrowRight, Copy, Check, Sparkles } from 'lucide-react';
import useAdvancedApi from '../../hooks/useAdvancedApi';
import { CATEGORIES, FALLBACK_MATERIALS } from './materialData';

function CostBadge({ multiplier }) {
  if (multiplier < 0.9) return <span className="text-[9px] px-1.5 py-0.5 rounded bg-green-50 border border-green-200 text-green-700 font-bold">Cost Saver</span>;
  if (multiplier > 1.15) return <span className="text-[9px] px-1.5 py-0.5 rounded bg-orange-50 border border-orange-200 text-orange-700 font-bold">Premium</span>;
  return null;
}

export default function MaterialPicker({ sharedState, onUpdateLayer }) {
  const { get } = useAdvancedApi();
  const [materials, setMaterials] = useState([]);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [copiedCode, setCopiedCode] = useState(null);
  const [applyingTo, setApplyingTo] = useState(null);  // { materialCode, layerIndex }

  useEffect(() => {
    get('/materials').then(res => {
      if (res?.materials) setMaterials(res.materials);
      else setMaterials(FALLBACK_MATERIALS);
    });
  }, [get]);

  const filtered = materials.filter(m => {
    const matchSearch = search === '' ||
      m.name.toLowerCase().includes(search.toLowerCase()) ||
      m.code.toLowerCase().includes(search.toLowerCase());
    const matchCategory = category === 'all' || m.category === category;
    return matchSearch && matchCategory;
  });

  const handleCopy = (mat) => {
    const text = `E = ${mat.E_default} MPa, ν = ${mat.nu}`;
    navigator.clipboard.writeText(text).then(() => {
      setCopiedCode(mat.code);
      setTimeout(() => setCopiedCode(null), 1500);
    });
  };

  const handleApply = (mat, layerIdx) => {
    if (onUpdateLayer) {
      onUpdateLayer(layerIdx, { E: mat.E_default, nu: mat.nu });
      setApplyingTo({ materialCode: mat.code, layerIndex: layerIdx });
      setTimeout(() => setApplyingTo(null), 1200);
    }
  };

  const layers = sharedState.layers || [];

  return (
    <div className="p-5">
      {/* Header */}
      <div className="mb-4">
        <h2 className="text-base font-bold text-gray-900 flex items-center gap-2">
          <BookOpen size={18} className="text-orange-600" /> Material Library
        </h2>
        <p className="text-[11px] text-gray-400 mt-0.5">
          India-market materials with IRC:37 properties — click Apply to populate a layer
        </p>
      </div>

      {/* Search + Filters */}
      <div className="flex items-center gap-2 mb-3">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search materials..."
            className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-300 rounded bg-white outline-none focus:border-orange-400 focus:ring-1 focus:ring-orange-100"
          />
        </div>
      </div>

      {/* Category Tabs */}
      <div className="flex items-center gap-1 mb-4 overflow-x-auto">
        {CATEGORIES.map(cat => (
          <button
            key={cat.id}
            onClick={() => setCategory(cat.id)}
            className={`px-2.5 py-1 rounded text-[11px] font-medium whitespace-nowrap transition-colors ${
              category === cat.id
                ? 'bg-orange-50 text-orange-800 border border-orange-200'
                : 'text-gray-500 hover:bg-gray-50 border border-transparent'
            }`}
          >
            {cat.label}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-gray-300">{filtered.length} materials</span>
      </div>

      {/* Material Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {filtered.map(mat => (
          <div
            key={mat.code}
            className={`bg-white rounded-lg border p-3.5 transition-all hover:shadow-md ${
              mat.source === 'advanced' ? 'border-orange-200' : 'border-gray-200'
            }`}
          >
            {/* Card Header */}
            <div className="flex items-start justify-between mb-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-bold text-gray-800 truncate">{mat.name}</span>
                  {mat.source === 'advanced' && (
                    <Sparkles size={10} className="text-orange-500 flex-shrink-0" />
                  )}
                </div>
                <span className="text-[10px] text-gray-400 font-mono">{mat.code}</span>
              </div>
              <CostBadge multiplier={mat.cost_multiplier} />
            </div>

            {/* Properties Grid */}
            <div className="grid grid-cols-3 gap-2 mb-2.5 bg-gray-50 rounded p-2">
              <div className="text-center">
                <p className="text-[9px] text-gray-400 uppercase">Modulus</p>
                <p className="text-xs font-bold font-mono text-gray-700">{mat.E_default}</p>
                <p className="text-[8px] text-gray-400">MPa</p>
              </div>
              <div className="text-center">
                <p className="text-[9px] text-gray-400 uppercase">Poisson</p>
                <p className="text-xs font-bold font-mono text-gray-700">{mat.nu}</p>
              </div>
              <div className="text-center">
                <p className="text-[9px] text-gray-400 uppercase">Density</p>
                <p className="text-xs font-bold font-mono text-gray-700">{mat.density}</p>
                <p className="text-[8px] text-gray-400">kg/m³</p>
              </div>
            </div>

            {/* Description */}
            <p className="text-[10px] text-gray-500 mb-3 leading-relaxed line-clamp-2">{mat.description}</p>

            {/* Actions */}
            <div className="flex items-center gap-1.5">
              {onUpdateLayer && layers.length > 0 ? (
                <div className="flex-1 relative group">
                  <button className="w-full flex items-center justify-center gap-1 px-2 py-1.5 text-[11px] font-medium bg-orange-50 text-orange-700 border border-orange-200 rounded hover:bg-orange-100 transition-colors">
                    <ArrowRight size={10} /> Apply to Layer
                  </button>
                  {/* Layer dropdown (appears on hover) */}
                  <div className="hidden group-hover:block absolute left-0 right-0 bottom-full mb-1 bg-white border border-gray-200 rounded shadow-lg z-10 py-1 max-h-40 overflow-y-auto">
                    {layers.slice(0, -1).map((l, idx) => {
                      const applied = applyingTo?.materialCode === mat.code && applyingTo?.layerIndex === idx;
                      return (
                        <button
                          key={idx}
                          onClick={() => handleApply(mat, idx)}
                          className="w-full text-left px-2.5 py-1 text-[11px] hover:bg-orange-50 flex items-center gap-1.5 transition-colors"
                        >
                          {applied ? <Check size={10} className="text-green-500" /> : <ArrowRight size={10} className="text-gray-300" />}
                          <span className="text-gray-600">L{idx + 1}:</span>
                          <span className="truncate text-gray-800">{l.name || `Layer ${idx + 1}`}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ) : null}
              <button
                onClick={() => handleCopy(mat)}
                className="flex items-center gap-1 px-2 py-1.5 text-[11px] text-gray-500 border border-gray-200 rounded hover:bg-gray-50 transition-colors"
                title="Copy E and ν to clipboard"
              >
                {copiedCode === mat.code ? <Check size={10} className="text-green-500" /> : <Copy size={10} />}
                {copiedCode === mat.code ? 'Copied!' : 'Copy'}
              </button>
            </div>
          </div>
        ))}
      </div>

      {filtered.length === 0 && (
        <div className="text-center py-8 text-gray-400">
          <BookOpen size={32} className="mx-auto mb-2 opacity-30" />
          <p className="text-xs">No materials match your search.</p>
        </div>
      )}
    </div>
  );
}
