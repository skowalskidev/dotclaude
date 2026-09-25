"use client";
// OWNED BY SLICE `record`. cmdk palette on ⌘K / Ctrl+K: jump to section, switch role/persona, open record tab, open project picker, toggle theme (data-theme + localStorage 'gauntlet-theme'), copy dashboard link. Keyboard: j/k move sections, t theme (both outside inputs and while closed), Escape closes.
import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Command } from "cmdk";
import { Search } from "lucide-react";
import type { PublicSpec } from "@/lib/types";
import { RECORD_TABS } from "@/lib/ledger";
import { StatusDot } from "./StatusDot";

export interface CommandPaletteProps { spec: PublicSpec; planPath: string }

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

function cap(s: string): string {
  return s[0].toUpperCase() + s.slice(1);
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("gauntlet-theme", next); } catch { /* private mode: theme just won't persist */ }
}

export function CommandPalette({ spec, planPath }: CommandPaletteProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [open, setOpen] = useState(false);

  const currentSectionId = useCallback((): string | undefined => {
    const fromUrl = searchParams.get("section");
    if (fromUrl && spec.sections.some((s) => s.id === fromUrl)) return fromUrl;
    return (spec.sections.find((s) => s.status === "review") ?? spec.sections.find((s) => s.status !== "done") ?? spec.sections[0])?.id;
  }, [searchParams, spec.sections]);

  const go = useCallback((patch: Record<string, string>) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("plan", planPath);
    for (const [k, v] of Object.entries(patch)) params.set(k, v);
    router.push(`/p?${params.toString()}`);
    setOpen(false);
  }, [router, searchParams, planPath]);

  const moveSection = useCallback((delta: number) => {
    const ids = spec.sections.map((s) => s.id);
    if (!ids.length) return;
    const cur = currentSectionId();
    const idx = cur ? ids.indexOf(cur) : 0;
    const next = ids[(idx + delta + ids.length) % ids.length];
    go({ section: next });
  }, [spec.sections, currentSectionId, go]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
        return;
      }
      if (e.key === "Escape" && open) { setOpen(false); return; }
      if (open || isTypingTarget(e.target)) return;
      if (e.key === "j") moveSection(1);
      else if (e.key === "k") moveSection(-1);
      else if (e.key === "t") toggleTheme();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, moveSection]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/50" onClick={() => setOpen(false)}>
      <div
        className="mx-auto w-[520px] overflow-hidden rounded-[var(--radius)] border border-ln bg-sf shadow-xl"
        style={{ marginTop: "20vh" }}
        onClick={(e) => e.stopPropagation()}
      >
        <Command label="Jump to…" loop className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-mu">
          <div className="flex items-center gap-2 border-b border-ln px-3">
            <Search size={14} className="shrink-0 text-mu" aria-hidden="true" />
            <Command.Input autoFocus placeholder="Jump…" className="h-10 flex-1 bg-transparent text-sm outline-none placeholder:text-mu" />
          </div>
          <Command.List className="max-h-[60vh] overflow-y-auto p-1">
            <Command.Empty className="px-3 py-6 text-center text-mu">No matches.</Command.Empty>
            <Command.Group heading="Sections">
              {spec.sections.map((s) => (
                <Command.Item
                  key={s.id}
                  value={`section ${s.title}`}
                  onSelect={() => go({ section: s.id })}
                  className="flex items-center gap-2.5 rounded px-3 py-2 text-tx data-[selected=true]:bg-sf2"
                >
                  <StatusDot status={s.status} />
                  <span className="truncate">{s.title}</span>
                </Command.Item>
              ))}
            </Command.Group>
            <Command.Group heading="View">
              {(["before", "target", "current"] as const).map((role) => (
                <Command.Item
                  key={`role-${role}`}
                  value={`view ${role}`}
                  onSelect={() => go({ role })}
                  className="rounded px-3 py-2 text-tx data-[selected=true]:bg-sf2"
                >
                  {cap(role)}
                </Command.Item>
              ))}
              {(["desktop", "mobile"] as const).map((persona) => (
                <Command.Item
                  key={`persona-${persona}`}
                  value={`view ${persona}`}
                  onSelect={() => go({ persona })}
                  className="rounded px-3 py-2 text-tx data-[selected=true]:bg-sf2"
                >
                  {cap(persona)}
                </Command.Item>
              ))}
            </Command.Group>
            <Command.Group heading="Record">
              {RECORD_TABS.map((t) => (
                <Command.Item
                  key={`record-${t}`}
                  value={`record ${t}`}
                  onSelect={() => go({ record: t })}
                  className="rounded px-3 py-2 text-tx data-[selected=true]:bg-sf2"
                >
                  {t}
                </Command.Item>
              ))}
            </Command.Group>
            <Command.Group heading="Actions">
              <Command.Item
                value="toggle theme"
                onSelect={() => { toggleTheme(); setOpen(false); }}
                className="rounded px-3 py-2 text-tx data-[selected=true]:bg-sf2"
              >
                Toggle theme
              </Command.Item>
              <Command.Item
                value="copy link"
                onSelect={() => { navigator.clipboard?.writeText(window.location.href).catch(() => {}); setOpen(false); }}
                className="rounded px-3 py-2 text-tx data-[selected=true]:bg-sf2"
              >
                Copy link
              </Command.Item>
              <Command.Item
                value="projects"
                onSelect={() => { router.push("/"); setOpen(false); }}
                className="rounded px-3 py-2 text-tx data-[selected=true]:bg-sf2"
              >
                Projects
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
