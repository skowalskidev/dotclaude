"use client";
// OWNED BY SLICE `live`. Contract: EventSource on /api/events?plan=…; router.refresh() on revision; exposes status.
import type { LiveStatus } from './types';
export function useLive(planPath: string): { status: LiveStatus; revision: number | null; updatedAt: string | null } {
  void planPath;
  return { status: 'offline', revision: null, updatedAt: null };
}
