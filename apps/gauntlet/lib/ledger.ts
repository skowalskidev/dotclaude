// OWNED BY SLICE `record`. Helpers that group LedgerEntry[] for display (asks, pivots, decisions from plan record).
import type { LedgerEntry, PublicSpec } from './types';
export interface RecordGroups { decisions: string[]; pivots: LedgerEntry[]; asks: LedgerEntry[]; sources: string[]; changelog: string }
export function groupRecord(spec: PublicSpec): RecordGroups {
  void spec;
  return { decisions: [], pivots: [], asks: [], sources: [], changelog: '' };
}
