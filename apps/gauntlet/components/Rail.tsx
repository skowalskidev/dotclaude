"use client";
// OWNED BY SLICE `canvas`. 40px icon strip (criteria ✓, comments, pins) that expands to 260px on click; expanded: CRITERIA list (StatusDot done/todo + text), PINS (from spec.feedbackDrafts if any), Request / Approve buttons (POST /api/plan?plan=… with {sectionId, verdict} — the api-plan slice accepts it and stores under feedbackDrafts). Collapsed by default.
import type { PublicSpec, Section } from "@/lib/types";
export interface RailProps { section: Section; spec: PublicSpec; planPath: string }
export function Rail({ section }: RailProps) {
  return <aside className="w-10 shrink-0 border-l border-ln p-2 text-mu text-xs">{section.criteria.filter((c) => c.passed).length}/{section.criteria.length}</aside>;
}
