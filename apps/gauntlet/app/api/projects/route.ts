// OWNED BY SLICE `api-plan`. GET → ProjectRow[] (listProjects). POST {plan} → register (planPathOrThrow, writeRegistry) → 200 {plans}. DELETE {plan} → unregister → 200 {plans}. Errors → 400 {error}.
export const dynamic = "force-dynamic";
export async function GET() { return Response.json({ error: "not implemented" }, { status: 501 }); }
export async function POST() { return Response.json({ error: "not implemented" }, { status: 501 }); }
export async function DELETE() { return Response.json({ error: "not implemented" }, { status: 501 }); }
