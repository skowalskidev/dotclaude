// OWNED BY SLICE `api-plan`. GET → ProjectRow[] (listProjects). POST {plan} → register (planPathOrThrow, writeRegistry) → 200 {plans}. DELETE {plan} → unregister → 200 {plans}. Errors → 400 {error}.
import type { NextRequest } from "next/server";
import { listProjects } from "@/lib/plan";
import { planPathOrThrow, readRegistry, writeRegistry } from "@/lib/paths";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const rows = await listProjects();
    return Response.json(rows);
  } catch (err) {
    return Response.json({ error: err instanceof Error ? err.message : String(err) }, { status: 400 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const planPath = planPathOrThrow(body?.plan);
    const plans = await readRegistry();
    plans.push(planPath);
    await writeRegistry(plans);
    return Response.json({ plans: Array.from(new Set(plans)) });
  } catch (err) {
    return Response.json({ error: err instanceof Error ? err.message : String(err) }, { status: 400 });
  }
}

export async function DELETE(request: NextRequest) {
  try {
    const body = await request.json();
    const planPath = planPathOrThrow(body?.plan);
    const plans = (await readRegistry()).filter((p) => p !== planPath);
    await writeRegistry(plans);
    return Response.json({ plans });
  } catch (err) {
    return Response.json({ error: err instanceof Error ? err.message : String(err) }, { status: 400 });
  }
}
