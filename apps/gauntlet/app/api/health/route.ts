import { GAUNTLET_PORT } from "@/lib/types";
export const dynamic = "force-dynamic";
/** Engine bridge health check: {ok:true, pid, port}. */
export function GET() { return Response.json({ ok: true, pid: process.pid, port: GAUNTLET_PORT, app: "gauntlet" }); }
