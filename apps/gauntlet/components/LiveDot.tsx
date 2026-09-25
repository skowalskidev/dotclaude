"use client";
// OWNED BY SLICE `live`. Shows useLive(): pulsing doing-dot + "live · Ns ago" when live, review-dot "reconnecting", bad-dot "offline".
import { useLive } from "@/lib/useLive";
export interface LiveDotProps { planPath: string }
export function LiveDot({ planPath }: LiveDotProps) {
  const { status } = useLive(planPath);
  return <span className="text-mu text-xs">{status}</span>;
}
