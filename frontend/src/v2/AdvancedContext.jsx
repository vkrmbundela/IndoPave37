import React, { createContext, useState, useEffect } from 'react';

const AdvancedContext = createContext(null);

const STORAGE_KEY = 'flexpave_advanced';

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch { return {}; }
}

export function AdvancedProvider({ children }) {
  const [state, setState] = useState(loadState);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  const update = (key, value) => {
    setState(prev => ({ ...prev, [key]: value }));
  };

  return (
    <AdvancedContext.Provider value={{ state, update }}>
      {children}
    </AdvancedContext.Provider>
  );
}
