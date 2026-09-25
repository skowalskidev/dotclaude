// FROZEN CONTRACT — TypeScript port of bin/workflow-dashboard.py read_plan/narrative/task_record/public_spec.
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { DashboardState, LedgerEntry, PublicSpec, RecordEntry, TaskRecord, ProjectRow } from './types';
import { assetUrl, readRegistry } from './paths';

const BLOCK = /^```dashboard-state\n([\s\S]*?)\n```\s*$/m;
export const RECORD_HEADINGS: Array<[string, string]> = [
  ['goal & user journey', 'User journey'], ['system journey', 'System journey'], ['tasks', 'Tasks'],
  ['decisions & rationale', 'Decisions'], ['risks & assumptions', 'Risks'], ['sources', 'Sources'],
  ['execution notes', 'Execution notes'], ['out of scope', 'Out of scope'], ['changelog', 'Changelog'],
];

export async function readPlan(planPath: string): Promise<{ content: string; state: DashboardState }> {
  const content = await fs.readFile(planPath, 'utf8');
  const m = BLOCK.exec(content);
  if (!m) throw new Error('Plan needs exactly one dashboard-state fenced block');
  return { content, state: JSON.parse(m[1]) as DashboardState };
}
export function narrativeSections(content: string): RecordEntry[] {
  const heads = [...content.matchAll(/^## ([^\n]+)\s*$/gm)];
  const found: Record<string, string> = {};
  heads.forEach((h, i) => {
    const name = h[1].trim().toLowerCase();
    const end = i + 1 < heads.length ? heads[i + 1].index! : content.length;
    const body = content.slice(h.index! + h[0].length, end).trim();
    for (const [prefix, label] of RECORD_HEADINGS) if (name.startsWith(prefix)) { found[label] = body; break; }
  });
  return RECORD_HEADINGS.filter(([, l]) => found[l]).map(([, l]) => ({ label: l, text: found[l] }));
}
export function taskRecord(content: string, state: DashboardState): TaskRecord {
  const artifacts: TaskRecord['artifacts'] = []; const remaining: TaskRecord['remaining'] = [];
  for (const s of state.sections) {
    for (const role of ['before', 'target', 'current'] as const) {
      const a = s[role]; if (!a) continue;
      artifacts.push({ sectionId: s.id, section: s.title, role, kind: a.kind, label: a.label, path: a.path, source: a.source, capturedAt: a.capturedAt });
    }
    if (s.status !== 'done') remaining.push({ sectionId: s.id, section: s.title, status: s.status, next: s.next ?? '', criteria: s.criteria.filter(c => !c.passed).map(c => c.text) });
  }
  return { sections: narrativeSections(content), artifacts, remaining };
}
/** Read-only projection of the intent ledger beside the plan, if present. Entries start with `## <iso> · <kind>`. */
export async function readLedger(planPath: string): Promise<LedgerEntry[]> {
  try {
    const raw = await fs.readFile(path.join(path.dirname(planPath), 'intent-ledger.md'), 'utf8');
    const out: LedgerEntry[] = []; const heads = [...raw.matchAll(/^## (\S+) · (\w+)(?: · session (\S+))?\s*$/gm)];
    heads.forEach((h, i) => {
      const end = i + 1 < heads.length ? heads[i + 1].index! : raw.length;
      const kind = (['ask', 'sources', 'plan', 'pivot', 'reconcile'] as const).find(k => k === h[2]) ?? 'other';
      out.push({ at: h[1], kind, session: h[3], text: raw.slice(h.index! + h[0].length, end).trim() });
    });
    return out;
  } catch { return []; }
}
/** State + record + ledger, with every image/html asset given a served URL (never base64). */
export async function publicSpec(planPath: string): Promise<PublicSpec> {
  const { content, state } = await readPlan(planPath);
  const spec: PublicSpec = { ...state, record: taskRecord(content, state), ledger: await readLedger(planPath), planDir: path.dirname(planPath) };
  for (const s of spec.sections) for (const role of ['before', 'target', 'current'] as const) {
    const a = s[role]; if (a && a.kind !== 'text' && a.path) a.url = assetUrl(planPath, a.path);
  }
  return spec;
}
export async function listProjects(): Promise<ProjectRow[]> {
  const rows: ProjectRow[] = [];
  for (const plan of await readRegistry()) {
    try { const { state } = await readPlan(plan); rows.push({ plan, title: state.title, phase: state.phase, revision: state.revision, updatedAt: state.updatedAt, root: path.dirname(path.dirname(plan)) }); }
    catch { /* stale registry row: skip */ }
  }
  return rows;
}
