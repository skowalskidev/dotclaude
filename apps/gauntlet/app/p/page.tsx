import { publicSpec } from "@/lib/plan";
import { planPathOrThrow } from "@/lib/paths";
import { TopBar } from "@/components/TopBar";
import { Nav } from "@/components/Nav";
import { SectionView } from "@/components/SectionView";
import { Rail } from "@/components/Rail";
import { RecordDrawer } from "@/components/RecordDrawer";
import { CommandPalette } from "@/components/CommandPalette";

export const dynamic = "force-dynamic";

/** FROZEN COMPOSITION (layout D1): top bar · left nav · canvas · right rail · record drawer · ⌘K. */
export default async function PlanPage({ searchParams }: PageProps<"/p">) {
  const sp = await searchParams;
  const planPath = planPathOrThrow(typeof sp.plan === "string" ? sp.plan : null);
  const spec = await publicSpec(planPath);
  const sectionId = typeof sp.section === "string" && spec.sections.some((s) => s.id === sp.section) ? sp.section : (spec.sections.find((s) => s.status === "review") ?? spec.sections.find((s) => s.status !== "done") ?? spec.sections[0])?.id;
  const role = sp.role === "before" || sp.role === "current" ? sp.role : "target";
  const persona = sp.persona === "mobile" ? "mobile" : "desktop";
  const section = spec.sections.find((s) => s.id === sectionId);
  return (
    <div className="flex h-dvh flex-col">
      <TopBar spec={spec} planPath={planPath} />
      <div className="flex min-h-0 flex-1">
        <Nav spec={spec} planPath={planPath} activeId={sectionId} />
        <main className="flex min-w-0 flex-1 flex-col">
          {section ? <SectionView spec={spec} section={section} planPath={planPath} role={role} persona={persona} /> : <p className="p-6 text-mu">No sections.</p>}
        </main>
        {section && <Rail section={section} spec={spec} planPath={planPath} />}
      </div>
      <RecordDrawer spec={spec} planPath={planPath} />
      <CommandPalette spec={spec} planPath={planPath} />
    </div>
  );
}
