"use client";
// OWNED BY SLICE `live`. Shows useLive(): pulsing doing-dot + "live · Ns ago" when live, review-dot "reconnecting", bad-dot "offline".
import { useEffect, useState } from "react";
import { useLive } from "@/lib/useLive";
import { StatusDot } from "@/components/StatusDot";
import type { SectionStatus } from "@/lib/types";

export interface LiveDotProps { planPath: string }

function secondsSince(iso: string): number {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
}

export function LiveDot({ planPath }: LiveDotProps) {
  const { status, updatedAt, connectedAt } = useLive(planPath);
  const [, tick] = useState(0);

  useEffect(() => {
    if (status !== "live") return;
    const id = setInterval(() => tick((n) => n + 1), 5000);
    return () => clearInterval(id);
  }, [status]);

  const lastEventAt = updatedAt ?? connectedAt;
  const dotStatus: SectionStatus = status === "live" ? "doing" : status === "reconnecting" ? "review" : "blocked";
  const text = status === "live" ? `live · ${secondsSince(lastEventAt ?? new Date().toISOString())}s` : status;

  return (
    <span className="inline-flex items-center gap-2" title={lastEventAt ?? undefined}>
      <StatusDot status={dotStatus} label={status} />
      <span className="font-mono text-xs text-mu">{text}</span>
    </span>
  );
}
