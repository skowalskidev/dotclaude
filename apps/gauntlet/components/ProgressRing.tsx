// OWNED BY SLICE `shell`. 22px conic ring; server-safe.
export interface ProgressRingProps { done: number; total: number }
export function ProgressRing({ done, total }: ProgressRingProps) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return <span aria-label={`${done} of ${total} done`} role="img" title={`${done}/${total}`} style={{ width: 22, height: 22, borderRadius: 999, background: `conic-gradient(var(--tx) 0 ${pct}%, var(--ln) ${pct}% 100%)`, position: "relative", display: "inline-block" }}><span style={{ position: "absolute", inset: 4, borderRadius: 999, background: "var(--bg)" }} /></span>;
}
