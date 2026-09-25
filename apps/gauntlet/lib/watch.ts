// OWNED BY SLICE `live`. Contract: subscribe to a plan directory; callback per change; returns unsubscribe.
import path from "node:path";
import { watch } from "chokidar";
import type { LiveEvent } from "./types";
import { readPlan } from "./plan";

export type Unsubscribe = () => void;

const DEBOUNCE_MS = 150;
const PING_MS = 25_000;

function isIgnoredEntry(entryPath: string, planDir: string, planPath: string): boolean {
  if (entryPath === planPath) return false;
  const rel = path.relative(planDir, entryPath);
  if (!rel || rel.startsWith("..")) return false;
  const parts = rel.split(path.sep);
  if (parts.includes("node_modules")) return true;
  return parts.some((part) => part.startsWith("."));
}

/** Watch <planDir> recursively (chokidar). Emit {type:'revision'} when the plan file changes (read its revision/updatedAt),
 *  {type:'asset', path} for any other file, and {type:'ping'} every 25 s so proxies keep the stream open. */
export function subscribe(planPath: string, onEvent: (e: LiveEvent) => void): Unsubscribe {
  const planDir = path.dirname(planPath);
  const timers = new Map<string, ReturnType<typeof setTimeout>>();

  const flush = async (absPath: string): Promise<void> => {
    timers.delete(absPath);
    if (absPath === planPath) {
      try {
        const { state } = await readPlan(planPath);
        onEvent({ type: "revision", revision: state.revision, updatedAt: state.updatedAt });
      } catch {
        /* mid-write / unparsable: skip this tick, a later write will re-trigger */
      }
      return;
    }
    onEvent({ type: "asset", path: path.relative(planDir, absPath) });
  };

  const schedule = (absPath: string): void => {
    const existing = timers.get(absPath);
    if (existing) clearTimeout(existing);
    timers.set(
      absPath,
      setTimeout(() => {
        void flush(absPath);
      }, DEBOUNCE_MS),
    );
  };

  const watcher = watch(planDir, {
    ignoreInitial: true,
    ignored: (entryPath: string) => isIgnoredEntry(path.resolve(entryPath), planDir, planPath),
  });
  watcher.on("add", schedule).on("change", schedule).on("unlink", schedule);

  const ping = setInterval(() => {
    onEvent({ type: "ping", at: new Date().toISOString() });
  }, PING_MS);

  return () => {
    clearInterval(ping);
    for (const timer of timers.values()) clearTimeout(timer);
    timers.clear();
    void watcher.close();
  };
}
