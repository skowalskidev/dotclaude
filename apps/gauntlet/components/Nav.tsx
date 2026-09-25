// OWNED BY SLICE `shell`. Server component: numbered section list with StatusDot, active row highlighted; review rows carry an unread red dot; footer icons: Record (opens drawer via ?record=1), Ledger, Sources.
import Link from "next/link";
import { ListOrdered, PenLine, Link2 } from "lucide-react";
import type { PublicSpec } from "@/lib/types";
import { StatusDot } from "./StatusDot";

export interface NavProps { spec: PublicSpec; planPath: string; activeId?: string }

function recordHref(planPath: string, activeId: string | undefined, record: string): string {
  const params = new URLSearchParams({ plan: planPath });
  if (activeId) params.set("section", activeId);
  params.set("record", record);
  return `/p?${params.toString()}`;
}

export function Nav({ spec, planPath, activeId }: NavProps) {
  return (
    <nav className="flex h-full w-54 shrink-0 flex-col gap-0.5 border-r border-ln p-2">
      {spec.sections.map((s, i) => (
        <Link
          key={s.id}
          href={`/p?plan=${encodeURIComponent(planPath)}&section=${encodeURIComponent(s.id)}`}
          className={`flex items-center gap-2.5 rounded-md px-2.5 py-1.5 ${s.id === activeId ? "bg-sf2" : "hover:bg-sf2"}`}
        >
          <span className="font-mono text-[11px] text-mu w-4">{String(i + 1).padStart(2, "0")}</span>
          <StatusDot status={s.status} />
          <span className="min-w-0 flex-1 truncate max-[1000px]:hidden">{s.title}</span>
          {s.status === "review" && (
            <i aria-label="needs review" role="img" className="h-1.5 w-1.5 shrink-0 rounded-full max-[1000px]:hidden" style={{ background: "var(--bad)" }} />
          )}
        </Link>
      ))}
      <div className="mt-auto flex items-center justify-around border-t border-ln pt-2">
        <Link href={recordHref(planPath, activeId, "1")} aria-label="Record" title="Record" className="inline-flex items-center justify-center rounded-md p-1.5 hover:bg-sf2">
          <ListOrdered size={16} />
        </Link>
        <Link href={recordHref(planPath, activeId, "ledger")} aria-label="Ledger" title="Ledger" className="inline-flex items-center justify-center rounded-md p-1.5 hover:bg-sf2">
          <PenLine size={16} />
        </Link>
        <Link href={recordHref(planPath, activeId, "sources")} aria-label="Sources" title="Sources" className="inline-flex items-center justify-center rounded-md p-1.5 hover:bg-sf2">
          <Link2 size={16} />
        </Link>
      </div>
    </nav>
  );
}
