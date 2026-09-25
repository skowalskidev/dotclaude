// OWNED BY SLICE `live`. Contract: subscribe to a plan directory; callback per change; returns unsubscribe.
import type { LiveEvent } from './types';
export type Unsubscribe = () => void;
/** Watch <planDir> recursively (chokidar). Emit {type:'revision'} when the plan file changes (read its revision/updatedAt),
 *  {type:'asset', path} for any other file, and {type:'ping'} every 25 s so proxies keep the stream open. */
export function subscribe(planPath: string, onEvent: (e: LiveEvent) => void): Unsubscribe {
  void planPath; void onEvent;
  throw new Error('not implemented: slice live');
}
