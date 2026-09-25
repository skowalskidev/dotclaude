import Link from "next/link";
import { listProjects } from "@/lib/plan";
import { StatusDot } from "@/components/StatusDot";

export const dynamic = "force-dynamic";

/** Project picker: every plan the engine registered via `serve`. */
export default async function Home() {
  const rows = await listProjects();
  return (
    <main className="mx-auto w-full max-w-3xl p-8">
      <h1 className="text-sm font-semibold text-mu mb-4">Projects</h1>
      {rows.length === 0 && <p className="text-mu">None yet. Run <code className="font-mono">workflow-dashboard.py serve</code> in a project.</p>}
      <ul className="divide-y divide-ln border border-ln rounded-[var(--radius)]">
        {rows.map((r) => (
          <li key={r.plan}>
            <Link href={`/p?plan=${encodeURIComponent(r.plan)}`} className="flex items-center gap-3 px-4 py-3 hover:bg-sf2">
              <StatusDot status={r.phase === "complete" ? "done" : r.phase === "blocked" ? "blocked" : "doing"} />
              <span className="font-medium">{r.title}</span>
              <span className="text-mu font-mono text-xs ml-auto">{r.root.split("/").slice(-2).join("/")} · r{r.revision}</span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
