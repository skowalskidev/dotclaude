// OWNED BY SLICE `live`. GET ?plan=… → text/event-stream. Uses lib/watch subscribe(); each LiveEvent as `data: <json>\n\n`; ping every 25 s; unsubscribe on request abort (req.signal). Headers: Cache-Control: no-cache, Connection: keep-alive, X-Accel-Buffering: no.
export const dynamic = "force-dynamic";
export async function GET() { return Response.json({ error: "not implemented" }, { status: 501 }); }
