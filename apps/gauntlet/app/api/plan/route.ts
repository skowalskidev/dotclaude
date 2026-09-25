// OWNED BY SLICE `api-plan`. GET ?plan=… → PublicSpec JSON (publicSpec). POST ?plan=… body {sectionId, verdict:'approve'|'request', note?, pins?} → append under state.feedbackDrafts[sectionId] via an atomic rewrite of ONLY the fenced JSON block (revision+1, updatedAt=now) → 200 {revision}. Never touch plan prose. Errors → 400 {error}.
import { promises as fs } from "node:fs";
import type { NextRequest } from "next/server";
import { publicSpec } from "@/lib/plan";
import { planPathOrThrow } from "@/lib/paths";
import type { DashboardState } from "@/lib/types";

export const dynamic = "force-dynamic";

// Same block pattern as lib/plan.ts's BLOCK, split into a JSON group and a trailing-whitespace
// group so the rewrite can restore the exact bytes around the JSON without touching prose.
const BLOCK = /^```dashboard-state\n([\s\S]*?)\n```(\s*)$/m;

export async function GET(request: NextRequest) {
  try {
    const planPath = planPathOrThrow(request.nextUrl.searchParams.get("plan"));
    const spec = await publicSpec(planPath);
    return Response.json(spec);
  } catch (err) {
    return Response.json({ error: err instanceof Error ? err.message : String(err) }, { status: 400 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const planPath = planPathOrThrow(request.nextUrl.searchParams.get("plan"));
    const body = await request.json();
    const sectionId = body?.sectionId;
    const verdict = body?.verdict;
    if (typeof sectionId !== "string" || !sectionId) throw new Error("sectionId required");
    if (verdict !== "approve" && verdict !== "request") throw new Error("verdict must be 'approve' or 'request'");
    const note = typeof body?.note === "string" ? body.note : undefined;
    const pins = body?.pins;

    const content = await fs.readFile(planPath, "utf8");
    const m = BLOCK.exec(content);
    if (!m) throw new Error("Plan needs exactly one dashboard-state fenced block");
    const state = JSON.parse(m[1]) as DashboardState;

    state.feedbackDrafts = {
      ...(state.feedbackDrafts ?? {}),
      [sectionId]: { verdict, note, pins, at: new Date().toISOString() },
    };
    state.revision += 1;
    state.updatedAt = new Date().toISOString();

    const newBlock = "```dashboard-state\n" + JSON.stringify(state, null, 2) + "\n```" + m[2];
    const newContent = content.slice(0, m.index) + newBlock + content.slice(m.index + m[0].length);

    const tmp = planPath + ".tmp";
    await fs.writeFile(tmp, newContent, "utf8");
    await fs.rename(tmp, planPath);

    return Response.json({ revision: state.revision });
  } catch (err) {
    return Response.json({ error: err instanceof Error ? err.message : String(err) }, { status: 400 });
  }
}
