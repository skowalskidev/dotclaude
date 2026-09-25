// OWNED BY SLICE `canvas`. Server component: head (title, StatusDot, `next` one-liner), tools row (Before|Target|Current segmented → ?role=, Desktop|Mobile → ?persona=, Open ↗), canvas = AssetFrame of the chosen role (target by default; review sections show the target full-width), Filmstrip below. previewUrl → one "Open preview ↗" link in the Current header.
import type { PublicSpec, Section } from "@/lib/types";
import { AssetFrame } from "./AssetFrame";
import { Filmstrip } from "./Filmstrip";
import { StatusDot } from "./StatusDot";
export interface SectionViewProps { spec: PublicSpec; section: Section; planPath: string; role: "before" | "target" | "current"; persona: "desktop" | "mobile" }
export function SectionView({ section, planPath, role }: SectionViewProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2.5 px-4 pt-3 pb-2"><h1 className="text-base font-semibold">{section.title}</h1><StatusDot status={section.status} />{section.next && <span className="text-xs text-mu">{section.next}</span>}</div>
      <div className="mx-4 min-h-0 flex-1 overflow-hidden rounded-[var(--radius)] border border-ln bg-sf"><AssetFrame asset={section[role]} role={role} fill /></div>
      <Filmstrip section={section} planPath={planPath} role={role} />
    </div>
  );
}
