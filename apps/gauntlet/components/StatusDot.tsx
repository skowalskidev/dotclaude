// OWNED BY SLICE `shell`. Server-safe (no hooks). 8px dot, colour from STATUS_COLOR, pulses while `doing`.
import type { SectionStatus } from "@/lib/types";
import { STATUS_COLOR } from "@/lib/types";
export interface StatusDotProps { status: SectionStatus; label?: string; size?: number }
export function StatusDot({ status, label, size = 8 }: StatusDotProps) {
  return <i aria-label={label ?? status} role="img" className={status === "doing" ? "pulse" : undefined} style={{ display: "inline-block", width: size, height: size, borderRadius: 999, background: STATUS_COLOR[status], flex: "0 0 auto" }} />;
}
