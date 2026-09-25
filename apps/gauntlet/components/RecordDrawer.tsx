"use client";
// OWNED BY SLICE `record`. Bottom drawer, collapsed to one 32px row: "Record · Decisions N · Pivots N · Sources N · Changelog N · Ledger N". Expands (click or `r`) to tabs over spec.record.sections + spec.ledger (asks, pivots, reconciles) + artifacts index + remaining actions. Markdown rendered minimally (headings, lists, links, code). Everything read-only.
import type { PublicSpec } from "@/lib/types";
export interface RecordDrawerProps { spec: PublicSpec; planPath: string }
export function RecordDrawer({ spec }: RecordDrawerProps) {
  return <footer className="flex h-8 items-center gap-4 border-t border-ln px-4 text-xs text-mu"><b className="text-tx font-medium">Record</b><span>Ledger {spec.ledger.length}</span></footer>;
}
