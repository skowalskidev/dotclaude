// FROZEN CONTRACT — every slice reads this; none edits it.
export type SectionStatus = 'todo' | 'doing' | 'blocked' | 'review' | 'done';
export type Phase = 'planning' | 'running' | 'paused' | 'blocked' | 'complete';
export type AssetKind = 'text' | 'image' | 'html';
export type AssetRole = 'before' | 'target' | 'current';

export interface Asset {
  kind: AssetKind; label: string; text?: string; path?: string; source?: string; capturedAt?: string;
  viewport?: { width: number; height: number }; origin?: 'generated'; targetRevision?: number;
  approval?: { by: string; evidence: string; targetRevision: number };
  /** Filled by publicSpec(): a same-origin URL served by /api/asset (never base64). */
  url?: string; sha256?: string;
}
export interface Criterion { id: string; text: string; passed: boolean; evidence: string }
export interface Judge { verdict: 'pending' | 'pass' | 'fail' | 'blocked'; agentId?: string; builderId?: string; artifactRevision?: number; reference?: string; evidence?: string }
export interface Section {
  id: string; title: string; summary: string; status: SectionStatus; artifactRevision: number; next?: string;
  previewUrl?: string; before?: Asset; target?: Asset; current?: Asset; criteria: Criterion[]; judge: Judge;
}
export interface DashboardState {
  schemaVersion: number; title: string; planPath: string; revision: number; updatedAt: string; phase: Phase;
  engine: string; gauntlet: boolean; referenceMode?: string; inspiration?: string; optionsConfirmedAt?: string | null;
  iteration?: number; maxIterations?: number; sections: Section[]; handoff?: Record<string, unknown>;
  feedbackDrafts?: Record<string, unknown>;
}
export interface RecordEntry { label: string; text: string }
export interface ArtifactIndexRow { sectionId: string; section: string; role: AssetRole; kind: AssetKind; label: string; path?: string; source?: string; capturedAt?: string }
export interface RemainingRow { sectionId: string; section: string; status: SectionStatus; next: string; criteria: string[] }
export interface TaskRecord { sections: RecordEntry[]; artifacts: ArtifactIndexRow[]; remaining: RemainingRow[] }
/** One intent-ledger entry (read-only projection of .context/intent-ledger.md). */
export interface LedgerEntry { at: string; kind: 'ask' | 'sources' | 'plan' | 'pivot' | 'reconcile' | 'other'; session?: string; text: string }
export interface PublicSpec extends DashboardState { record: TaskRecord; ledger: LedgerEntry[]; planDir: string }
export interface ProjectRow { plan: string; title: string; phase: Phase; revision: number; updatedAt: string; root: string }
/** SSE payload on /api/events?plan=… */
export type LiveEvent = { type: 'revision'; revision: number; updatedAt: string } | { type: 'asset'; path: string } | { type: 'ping'; at: string };
export type LiveStatus = 'live' | 'reconnecting' | 'offline';
export const GAUNTLET_PORT = 4747;
export const STATUS_COLOR: Record<SectionStatus, string> = { done: 'var(--ok)', review: 'var(--review)', doing: 'var(--doing)', todo: 'var(--idle)', blocked: 'var(--bad)' };
