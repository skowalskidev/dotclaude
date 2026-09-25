// FROZEN CONTRACT — path jail + project registry. Slices call these; none edits them.
import { promises as fs } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import type { ProjectRow } from './types';

export const REGISTRY = path.join(os.homedir(), '.claude', 'state', 'gauntlet-projects.json');

/** Absolute plan path or throw. Only *-plan.md files inside a .context directory are accepted. */
export function planPathOrThrow(input: string | null | undefined): string {
  if (!input) throw new Error('plan query parameter required');
  const p = path.resolve(input);
  if (!p.endsWith('-plan.md') || path.basename(path.dirname(p)) !== '.context') throw new Error('plan must be .context/<slug>-plan.md');
  return p;
}
/** Resolve an asset path relative to the plan directory; refuse anything that escapes it. */
export function assetPathOrThrow(planPath: string, rel: string): string {
  const base = path.dirname(path.resolve(planPath));
  const p = path.resolve(base, rel);
  if (p !== base && !p.startsWith(base + path.sep)) throw new Error('asset must stay inside the plan directory');
  return p;
}
export function assetUrl(planPath: string, rel: string): string {
  return `/api/asset?plan=${encodeURIComponent(planPath)}&path=${encodeURIComponent(rel)}`;
}
export async function readRegistry(): Promise<string[]> {
  try { const raw = await fs.readFile(REGISTRY, 'utf8'); const j = JSON.parse(raw); return Array.isArray(j.plans) ? j.plans.filter((x: unknown) => typeof x === 'string') : []; }
  catch { return []; }
}
export async function writeRegistry(plans: string[]): Promise<void> {
  await fs.mkdir(path.dirname(REGISTRY), { recursive: true });
  const tmp = REGISTRY + '.tmp';
  await fs.writeFile(tmp, JSON.stringify({ plans: Array.from(new Set(plans)) }, null, 2));
  await fs.rename(tmp, REGISTRY);
}
export function projectRoot(planPath: string): string { return path.dirname(path.dirname(path.resolve(planPath))); }
export type { ProjectRow };
