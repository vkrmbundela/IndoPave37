// Non-component helpers shared by the cockpit components.
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

// Status tone of a demand/capacity ratio: <= 0.9 ok, <= 1 warn (close to the
// limit), > 1 fail.
export function ratioTone(r) {
  if (r == null || !Number.isFinite(Number(r))) return 'muted';
  if (r > 1) return 'fail';
  if (r > 0.9) return 'warn';
  return 'ok';
}

// Archetype accent (flat; the label may be merged, e.g. "Economy + Sustainable").
export function archetypeTone(strategy = '') {
  if (strategy.includes('Premium')) return { color: 'var(--arch-premium)', key: 'premium' };
  if (strategy.includes('Structural')) return { color: 'var(--arch-structural)', key: 'structural' };
  if (strategy.includes('Economy')) return { color: 'var(--arch-economy)', key: 'economy' };
  if (strategy.includes('Sustainable')) return { color: 'var(--arch-sustainable)', key: 'sustainable' };
  return { color: 'var(--text-muted)', key: 'design' };
}

// Indian number formatting: ₹ lakh / crore per lane-km.
export function formatRupees(perKm) {
  if (perKm == null || !Number.isFinite(Number(perKm))) return '—';
  const v = Number(perKm);
  return v >= 1e7 ? `₹${(v / 1e7).toFixed(2)} Cr/km` : `₹${(v / 1e5).toFixed(1)} lakh/km`;
}
