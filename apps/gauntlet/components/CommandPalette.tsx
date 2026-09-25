"use client";
// OWNED BY SLICE `record`. cmdk palette on ⌘K / Ctrl+K: jump to section, switch role/persona, open record tab, open project picker, toggle theme (data-theme + localStorage 'gauntlet-theme'), copy dashboard link. Keyboard: j/k move sections, 1-3 role, r record, t theme.
import type { PublicSpec } from "@/lib/types";
export interface CommandPaletteProps { spec: PublicSpec; planPath: string }
export function CommandPalette({ spec }: CommandPaletteProps) {
  void spec;
  return null;
}
