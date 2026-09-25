"use client";
// OWNED BY SLICE `live`. Contract: EventSource on /api/events?plan=…; router.refresh() on revision; exposes status.
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { LiveEvent, LiveStatus } from "./types";

const MAX_FAILURES = 5;

export function useLive(planPath: string): { status: LiveStatus; revision: number | null; updatedAt: string | null; connectedAt: string | null } {
  const router = useRouter();
  const [status, setStatus] = useState<LiveStatus>("reconnecting");
  const [connectedAt, setConnectedAt] = useState<string | null>(null);
  const [revision, setRevision] = useState<number | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const failures = useRef(0);

  useEffect(() => {
    const source = new EventSource(`/api/events?plan=${encodeURIComponent(planPath)}`);

    source.onopen = () => {
      setConnectedAt(new Date().toISOString());
      failures.current = 0;
      setStatus("live");
    };

    source.onmessage = (ev: MessageEvent) => {
      let event: LiveEvent;
      try {
        event = JSON.parse(ev.data) as LiveEvent;
      } catch {
        return;
      }
      if (event.type === "revision") {
        setRevision(event.revision);
        setUpdatedAt(event.updatedAt);
        router.refresh();
      }
    };

    source.onerror = () => {
      failures.current += 1;
      setStatus(failures.current >= MAX_FAILURES ? "offline" : "reconnecting");
    };

    return () => {
      source.close();
    };
  }, [planPath, router]);

  return { status, revision, updatedAt, connectedAt };
}
