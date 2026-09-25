"use client";
// OWNED BY SLICE `canvas`. 120×68 thumbnails: before, target, current (whatever exists) + older mockup versions if the html asset's #spec lists versions (fetch /api/asset text and parse the <script id="spec"> JSON client-side, lazily). Active thumb outlined. Click → ?role=…
import { useEffect, useState } from "react";
import Link from "next/link";
import type { AssetRole, Section } from "@/lib/types";

export interface FilmstripProps { section: Section; planPath: string; role: "before" | "target" | "current" }

interface SpecVersion { id: string; author?: string }

const ROLES: Array<{ key: AssetRole; label: string }> = [
  { key: "before", label: "Before" },
  { key: "target", label: "Target" },
  { key: "current", label: "Current" },
];

function roleHref(planPath: string, sectionId: string, role: AssetRole): string {
  return `/p?plan=${encodeURIComponent(planPath)}&section=${encodeURIComponent(sectionId)}&role=${role}`;
}

export function Filmstrip({ section, planPath, role }: FilmstripProps) {
  const [loaded, setLoaded] = useState<{ url: string; versions: SpecVersion[] } | null>(null);
  const activeAsset = section[role];
  const activeUrl = activeAsset && activeAsset.kind === "html" ? activeAsset.url : undefined;
  const versions = loaded && loaded.url === activeUrl ? loaded.versions : [];

  useEffect(() => {
    if (!activeUrl) return;
    let cancelled = false;
    fetch(activeUrl)
      .then((r) => r.text())
      .then((html) => {
        if (cancelled) return;
        const m = /<script type="application\/json" id="spec">([\s\S]*?)<\/script>/.exec(html);
        if (!m) return;
        const parsed = JSON.parse(m[1]) as { versions?: SpecVersion[] };
        if (Array.isArray(parsed.versions)) setLoaded({ url: activeUrl, versions: parsed.versions });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [activeUrl]);

  return (
    <div className="flex items-center gap-2 overflow-x-auto px-4 pb-3">
      {ROLES.filter((r) => section[r.key]).map((r) => {
        const asset = section[r.key]!;
        const active = r.key === role;
        return (
          <Link
            key={r.key}
            href={roleHref(planPath, section.id, r.key)}
            style={active ? { outline: "1.5px solid var(--tx)" } : undefined}
            className="h-[68px] w-[120px] shrink-0 overflow-hidden rounded border border-ln bg-sf2"
          >
            {asset.kind === "image" && asset.url ? (
              <img src={asset.url} alt={asset.label} className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full items-center justify-center p-1 text-center text-[10px] text-mu">{asset.label}</div>
            )}
          </Link>
        );
      })}
      {versions.map((v, i) => (
        <a
          key={v.id}
          href={`${activeUrl}#v=${v.id}`}
          target="_blank"
          rel="noreferrer"
          className={`flex h-[68px] w-[120px] shrink-0 items-center justify-center rounded border border-ln bg-sf2 p-1 text-center text-[10px] text-mu ${i === versions.length - 1 ? "" : "opacity-50"}`}
        >
          {v.id}
          {v.author ? ` · ${v.author}` : ""}
        </a>
      ))}
    </div>
  );
}
