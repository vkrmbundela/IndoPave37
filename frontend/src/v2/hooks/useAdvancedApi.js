import { useState, useCallback } from 'react';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export default function useAdvancedApi() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);

  const execute = useCallback(async (path, options = {}) => {
    setLoading(true);
    setError(null);
    try {
      const url = `${API_BASE}/api/v2${path}`;
      const res = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        const detail = err.detail;
        const msg = typeof detail === 'string' ? detail
          : Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('; ')
          : `HTTP ${res.status}`;
        throw new Error(msg);
      }
      const json = await res.json();
      setData(json);
      return json;
    } catch (e) {
      setError(e.message);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const get = useCallback((path) => execute(path), [execute]);

  const post = useCallback((path, body) => execute(path, {
    method: 'POST',
    body: JSON.stringify(body),
  }), [execute]);

  return { data, error, loading, get, post };
}
