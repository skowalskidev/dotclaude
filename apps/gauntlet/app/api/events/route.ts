// OWNED BY SLICE `live`. GET ?plan=… → text/event-stream. Uses lib/watch subscribe(); each LiveEvent as `data: <json>\n\n`; ping every 25 s; unsubscribe on request abort (req.signal). Headers: Cache-Control: no-cache, Connection: keep-alive, X-Accel-Buffering: no.
import { planPathOrThrow } from "@/lib/paths";
import { subscribe } from "@/lib/watch";
import type { Unsubscribe } from "@/lib/watch";
import type { LiveEvent } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  let planPath: string;
  try {
    const { searchParams } = new URL(request.url);
    planPath = planPathOrThrow(searchParams.get("plan"));
  } catch (err) {
    return Response.json({ error: (err as Error).message }, { status: 400 });
  }

  const encoder = new TextEncoder();
  let unsubscribe: Unsubscribe | null = null;

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const send = (event: LiveEvent) => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      };
      send({ type: "ping", at: new Date().toISOString() });
      unsubscribe = subscribe(planPath, send);
      request.signal.addEventListener("abort", () => {
        unsubscribe?.();
        unsubscribe = null;
        try {
          controller.close();
        } catch {
          /* already closed */
        }
      });
    },
    cancel() {
      unsubscribe?.();
      unsubscribe = null;
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
