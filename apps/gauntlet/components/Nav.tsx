// OWNED BY SLICE `shell`. Server component: numbered section list with StatusDot, active row highlighted; review rows carry an unread red dot; footer icons: Record (opens drawer via ?record=1), Ledger, Sources.
import Link from "next/link";
import type { PublicSpec } from "@/lib/types";
import { StatusDot } from "./StatusDot";
export interface NavProps { spec: PublicSpec; planPath: string; activeId?: string }
export function Nav({ spec, planPath, activeId }: NavProps) {
  return (
    <nav className="w-54 shrink-0 border-r border-ln p-2 flex flex-col gap-0.5">
      {spec.sections.map((s, i) => (
        <Link key={s.id} href={`/p?plan=${encodeURIComponent(planPath)}&section=${encodeURIComponent(s.id)}`} className={`flex items-center gap-2.5 rounded-md px-2.5 py-1.5 ${s.id === activeId ? "bg-sf2" : "hover:bg-sf2"}`}>
          <span className="font-mono text-[11px] text-mu w-4">{String(i + 1).padStart(2, "0")}</span>
          <StatusDot status={s.status} />
          <span className="truncate">{s.title}</span>
        </Link>
      ))}
    </nav>
  );
}
