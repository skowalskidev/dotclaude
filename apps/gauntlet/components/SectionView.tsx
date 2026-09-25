// OWNED BY SLICE `canvas`. Server component: head (title, StatusDot, `next` one-liner), tools row (Before|Target|Current segmented → ?role=, Desktop|Mobile → ?persona=, Open ↗), canvas = AssetFrame of the chosen role (target by default; review sections show the target full-width), Filmstrip below. previewUrl → one "Open preview ↗" link in the Current header.
import Link from "next/link";
import { ExternalLink, Globe } from "lucide-react";
import type { AssetRole, PublicSpec, Section } from "@/lib/types";
import { AssetFrame } from "./AssetFrame";
import { Filmstrip } from "./Filmstrip";
import { StatusDot } from "./StatusDot";

export interface SectionViewProps { spec: PublicSpec; section: Section; planPath: string; role: "before" | "target" | "current"; persona: "desktop" | "mobile" }

const ROLES: Array<{ key: AssetRole; label: string }> = [
  { key: "before", label: "Before" },
  { key: "target", label: "Target" },
  { key: "current", label: "Current" },
];

function sectionHref(planPath: string, sectionId: string, role: string, persona: string): string {
  return `/p?plan=${encodeURIComponent(planPath)}&section=${encodeURIComponent(sectionId)}&role=${role}&persona=${persona}`;
}

export function SectionView({ section, planPath, role, persona }: SectionViewProps) {
  const asset = section[role];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2.5 px-4 pt-3 pb-2">
        <h1 className="text-base font-semibold">{section.title}</h1>
        <StatusDot status={section.status} />
        {section.next && <span className="truncate text-xs text-mu">{section.next}</span>}
      </div>
      <div className="flex items-center gap-3 px-4 pb-2">
        <div className="flex items-center gap-0.5 rounded-md border border-ln p-0.5">
          {ROLES.filter((r) => section[r.key]).map((r) => (
            <Link
              key={r.key}
              href={sectionHref(planPath, section.id, r.key, persona)}
              className={`rounded px-2 py-1 text-xs ${role === r.key ? "bg-sf2 text-tx" : "text-mu hover:text-tx"}`}
            >
              {r.label}
            </Link>
          ))}
        </div>
        <div className="flex items-center gap-0.5 rounded-md border border-ln p-0.5">
          <Link
            href={sectionHref(planPath, section.id, role, "desktop")}
            className={`rounded px-2 py-1 text-xs ${persona === "desktop" ? "bg-sf2 text-tx" : "text-mu hover:text-tx"}`}
          >
            Desktop
          </Link>
          <Link
            href={sectionHref(planPath, section.id, role, "mobile")}
            className={`rounded px-2 py-1 text-xs ${persona === "mobile" ? "bg-sf2 text-tx" : "text-mu hover:text-tx"}`}
          >
            Mobile
          </Link>
        </div>
        <div className="flex-1" />
        {asset?.url && (
          <a href={asset.url} target="_blank" rel="noreferrer" aria-label="Open" title="Open" className="text-mu hover:text-tx">
            <ExternalLink size={16} />
          </a>
        )}
        {role === "current" && section.previewUrl && (
          <a href={section.previewUrl} target="_blank" rel="noreferrer" aria-label="Open preview" title="Open preview" className="text-mu hover:text-tx">
            <Globe size={16} />
          </a>
        )}
      </div>
      <div className="mx-4 min-h-0 flex-1 overflow-hidden rounded-[var(--radius)] border border-ln bg-sf">
        <AssetFrame asset={asset} role={role} persona={persona} fill />
      </div>
      <Filmstrip section={section} planPath={planPath} role={role} />
    </div>
  );
}
