// OWNED BY SLICE `api-plan`. GET ?plan=… → PublicSpec JSON (publicSpec). POST ?plan=… body {sectionId, verdict:'approve'|'request', note?, pins?} → append under state.feedbackDrafts[sectionId] via an atomic rewrite of ONLY the fenced JSON block (revision+1, updatedAt=now) → 200 {revision}. Never touch plan prose. Errors → 400 {error}.
export const dynamic = "force-dynamic";
export async function GET() { return Response.json({ error: "not implemented" }, { status: 501 }); }
export async function POST() { return Response.json({ error: "not implemented" }, { status: 501 }); }
