// OWNED BY SLICE `record`. Helpers that group LedgerEntry[] for display (asks, pivots, decisions from plan record).
import type { LedgerEntry, PublicSpec } from './types';

export interface RecordGroups { decisions: string[]; pivots: LedgerEntry[]; asks: LedgerEntry[]; sources: string[]; changelog: string }

/** Shared tab list for the record drawer and command palette (one source of truth for tab ids/labels). */
export const RECORD_TABS = ['Decisions', 'Pivots', 'Asks', 'Sources', 'Artifacts', 'Remaining', 'Journey', 'Changelog'] as const;
export type RecordTab = (typeof RECORD_TABS)[number];

function bullets(text: string | undefined): string[] {
  if (!text) return [];
  return text.split('\n').filter((l) => l.trimStart().startsWith('- ')).map((l) => l.trimStart().slice(2).trim());
}

export function groupRecord(spec: PublicSpec): RecordGroups {
  const find = (label: string) => spec.record.sections.find((s) => s.label === label)?.text;
  return {
    decisions: bullets(find('Decisions')),
    pivots: spec.ledger.filter((e) => e.kind === 'pivot'),
    asks: spec.ledger.filter((e) => e.kind === 'ask'),
    sources: bullets(find('Sources')),
    changelog: find('Changelog') ?? '',
  };
}
