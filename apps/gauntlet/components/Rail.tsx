"use client";
// OWNED BY SLICE `canvas`. 40px icon strip (criteria ✓, comments, pins) that expands to 260px on click; expanded: CRITERIA list (StatusDot done/todo + text), PINS (from spec.feedbackDrafts if any), Request / Approve buttons (POST /api/plan?plan=… with {sectionId, verdict} — the api-plan slice accepts it and stores under feedbackDrafts). Collapsed by default.
import { useState } from "react";
import { CheckSquare, MessageSquare, Pin, X } from "lucide-react";
import type { PublicSpec, Section } from "@/lib/types";
import { StatusDot } from "./StatusDot";

export interface RailProps { section: Section; spec: PublicSpec; planPath: string }

function pinsFor(spec: PublicSpec, sectionId: string): string[] {
  const drafts = spec.feedbackDrafts as Record<string, { pins?: unknown }> | undefined;
  const pins = drafts?.[sectionId]?.pins;
  return Array.isArray(pins) ? pins.filter((p): p is string => typeof p === "string") : [];
}

export function Rail({ section, spec, planPath }: RailProps) {
  const [expanded, setExpanded] = useState(false);
  const [sent, setSent] = useState(false);

  async function send(verdict: "request" | "approve") {
    setSent(false);
    const res = await fetch(`/api/plan?plan=${encodeURIComponent(planPath)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sectionId: section.id, verdict }),
    });
    if (res.ok) setSent(true);
  }

  if (!expanded) {
    return (
      <aside className="flex w-10 shrink-0 flex-col items-center gap-3 border-l border-ln p-2">
        <button type="button" aria-label="Criteria" title="Criteria" onClick={() => setExpanded(true)} className="text-mu hover:text-tx">
          <CheckSquare size={16} />
        </button>
        <button type="button" aria-label="Comments" title="Comments" onClick={() => setExpanded(true)} className="text-mu hover:text-tx">
          <MessageSquare size={16} />
        </button>
        <button type="button" aria-label="Pins" title="Pins" onClick={() => setExpanded(true)} className="text-mu hover:text-tx">
          <Pin size={16} />
        </button>
      </aside>
    );
  }

  const pins = pinsFor(spec, section.id);

  return (
    <aside className="flex w-[260px] shrink-0 flex-col gap-3 border-l border-ln p-3">
      <button type="button" aria-label="Collapse" title="Collapse" onClick={() => setExpanded(false)} className="self-end text-mu hover:text-tx">
        <X size={14} />
      </button>
      <div>
        <div className="text-[11px] font-semibold tracking-wide text-mu">CRITERIA</div>
        <div className="mt-1.5 flex flex-col gap-1.5">
          {section.criteria.map((c) => (
            <div key={c.id} className="flex items-start gap-2 text-xs">
              <StatusDot status={c.passed ? "done" : "todo"} />
              <span>{c.text}</span>
            </div>
          ))}
        </div>
      </div>
      {pins.length > 0 && (
        <div>
          <div className="text-[11px] font-semibold tracking-wide text-mu">PINS</div>
          <div className="mt-1.5 flex flex-col gap-1.5">
            {pins.map((p, i) => (
              <div key={i} className="text-xs text-mu">{p}</div>
            ))}
          </div>
        </div>
      )}
      <div className="mt-auto flex items-center gap-2">
        <button type="button" onClick={() => send("request")} className="rounded-md border border-ln px-2.5 py-1.5 text-xs text-tx">Request</button>
        <button type="button" onClick={() => send("approve")} className="rounded-md bg-ac px-2.5 py-1.5 text-xs text-ac-fg">Approve</button>
        {sent && <i aria-label="Sent" role="img" style={{ display: "inline-block", width: 6, height: 6, borderRadius: 999, background: "var(--ok)" }} />}
      </div>
    </aside>
  );
}
