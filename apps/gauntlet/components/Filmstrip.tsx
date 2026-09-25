// OWNED BY SLICE `canvas`. 120×68 thumbnails: before, target, current (whatever exists) + older mockup versions if the html asset's #spec lists versions (fetch /api/asset text and parse the <script id="spec"> JSON client-side, lazily). Active thumb outlined. Click → ?role=…
"use client";
import type { Section } from "@/lib/types";
export interface FilmstripProps { section: Section; planPath: string; role: "before" | "target" | "current" }
export function Filmstrip({ section, role }: FilmstripProps) {
  void section;
  return <div className="px-4 pb-3 text-mu text-xs">filmstrip · {role}</div>;
}
