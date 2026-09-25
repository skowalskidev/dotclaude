"use client";
// OWNED BY SLICE `record`. Bottom drawer, collapsed to one 32px row: "Record" (text-tx font-medium) then chips "Decisions N · Pivots N · Asks N · Sources N · Artifacts N · Remaining N" in text-mu text-xs, a chevron icon button (aria-label "Expand record") on the right; expanded (height 45vh, border-t, bg-bg) shows a tab strip (the chip names plus "Journey" = User journey + System journey entries, and "Changelog") and the active tab's content: bullets as a list, ledger entries as rows with at + kind dot + text (clamped to 6 lines with a "more" toggle), artifacts as rows sectionId · role · kind · label, remaining as rows with StatusDot + next. Minimal markdown (no dependency): "- " lists, "### " headings, `code` spans, [text](url) links. Opens when the URL has ?record=<tab> or on `r` outside inputs; Escape closes.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { ArtifactIndexRow, LedgerEntry, PublicSpec, RemainingRow } from "@/lib/types";
import { groupRecord, RECORD_TABS, type RecordTab } from "@/lib/ledger";
import { StatusDot } from "./StatusDot";

export interface RecordDrawerProps { spec: PublicSpec; planPath: string }

function isTab(v: string | null): v is RecordTab {
  return !!v && (RECORD_TABS as readonly string[]).includes(v);
}

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

/** Inline markdown: `code` spans and [text](url) links. No block-level handling here. */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = re.exec(text))) {
    if (match.index > last) out.push(text.slice(last, match.index));
    if (match[1] !== undefined) {
      out.push(<code key={`${keyPrefix}-c${i}`} className="rounded bg-sf2 px-1 font-mono text-[11px]">{match[1]}</code>);
    } else {
      out.push(<a key={`${keyPrefix}-l${i}`} href={match[3]} target="_blank" rel="noreferrer" className="text-tx underline underline-offset-2">{match[2]}</a>);
    }
    last = re.lastIndex;
    i++;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Minimal block markdown: "- " lists and "### " headings, falling back to paragraphs. */
function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const nodes: ReactNode[] = [];
  let list: string[] = [];
  const flushList = (key: string) => {
    if (!list.length) return;
    nodes.push(
      <ul key={key} className="list-disc space-y-0.5 pl-4">
        {list.map((item, i) => <li key={i}>{renderInline(item, `${key}-${i}`)}</li>)}
      </ul>
    );
    list = [];
  };
  lines.forEach((line, idx) => {
    const trimmed = line.trimStart();
    if (trimmed.startsWith("- ")) { list.push(trimmed.slice(2)); return; }
    flushList(`ul-${idx}`);
    if (trimmed.startsWith("### ")) nodes.push(<div key={idx} className="mt-2 text-xs font-semibold text-tx">{trimmed.slice(4)}</div>);
    else if (trimmed.length) nodes.push(<p key={idx} className="whitespace-pre-wrap">{renderInline(line, `p-${idx}`)}</p>);
  });
  flushList("ul-end");
  return <>{nodes}</>;
}

function Empty() {
  return <p className="text-mu">Nothing yet.</p>;
}

function LedgerRow({ entry }: { entry: LedgerEntry }) {
  const [expanded, setExpanded] = useState(false);
  const status = entry.kind === "pivot" ? "review" : entry.kind === "ask" ? "doing" : "done";
  return (
    <div className="flex gap-2 border-b border-ln py-2 last:border-b-0">
      <span className="shrink-0 font-mono text-xs text-mu">{entry.at}</span>
      <StatusDot status={status} />
      <div className="min-w-0 flex-1">
        <p className={`whitespace-pre-wrap ${expanded ? "" : "line-clamp-6"}`}>{entry.text}</p>
        <button type="button" onClick={() => setExpanded((e) => !e)} className="mt-1 text-xs text-mu hover:text-tx">
          {expanded ? "less" : "more"}
        </button>
      </div>
    </div>
  );
}

function ArtifactRow({ row }: { row: ArtifactIndexRow }) {
  return (
    <div className="flex items-center gap-2 border-b border-ln py-1.5 text-xs last:border-b-0">
      <span className="text-mu">{row.sectionId}</span><span className="text-mu">·</span>
      <span>{row.role}</span><span className="text-mu">·</span>
      <span>{row.kind}</span><span className="text-mu">·</span>
      <span className="truncate text-tx">{row.label}</span>
    </div>
  );
}

function RemainingRowView({ row }: { row: RemainingRow }) {
  return (
    <div className="flex items-start gap-2 border-b border-ln py-1.5 text-xs last:border-b-0">
      <span className="pt-0.5"><StatusDot status={row.status} /></span>
      <span className="shrink-0 text-tx">{row.section}</span>
      {row.next && <span className="text-mu">{row.next}</span>}
    </div>
  );
}

function TabContent({ tab, spec, groups }: { tab: RecordTab; spec: PublicSpec; groups: ReturnType<typeof groupRecord> }) {
  switch (tab) {
    case "Decisions":
      return groups.decisions.length ? (
        <ul className="list-disc space-y-1 pl-4">{groups.decisions.map((d, i) => <li key={i}>{renderInline(d, `dec-${i}`)}</li>)}</ul>
      ) : <Empty />;
    case "Sources":
      return groups.sources.length ? (
        <ul className="list-disc space-y-1 pl-4">{groups.sources.map((s, i) => <li key={i}>{renderInline(s, `src-${i}`)}</li>)}</ul>
      ) : <Empty />;
    case "Pivots":
      return groups.pivots.length ? <div>{groups.pivots.map((e, i) => <LedgerRow key={i} entry={e} />)}</div> : <Empty />;
    case "Asks":
      return groups.asks.length ? <div>{groups.asks.map((e, i) => <LedgerRow key={i} entry={e} />)}</div> : <Empty />;
    case "Artifacts":
      return spec.record.artifacts.length ? <div>{spec.record.artifacts.map((r, i) => <ArtifactRow key={i} row={r} />)}</div> : <Empty />;
    case "Remaining":
      return spec.record.remaining.length ? <div>{spec.record.remaining.map((r, i) => <RemainingRowView key={i} row={r} />)}</div> : <Empty />;
    case "Journey": {
      const uj = spec.record.sections.find((s) => s.label === "User journey");
      const sj = spec.record.sections.find((s) => s.label === "System journey");
      if (!uj && !sj) return <Empty />;
      return (
        <div className="space-y-4">
          {uj && <div><div className="mb-1 text-xs font-semibold text-tx">User journey</div><Markdown text={uj.text} /></div>}
          {sj && <div><div className="mb-1 text-xs font-semibold text-tx">System journey</div><Markdown text={sj.text} /></div>}
        </div>
      );
    }
    case "Changelog":
      return groups.changelog ? <Markdown text={groups.changelog} /> : <Empty />;
  }
}

export function RecordDrawer({ spec }: RecordDrawerProps) {
  const searchParams = useSearchParams();
  const groups = useMemo(() => groupRecord(spec), [spec]);
  const recordParam = searchParams.get("record");
  const urlKey = searchParams.toString();
  const urlOpen = searchParams.has("record");
  const urlTab: RecordTab = isTab(recordParam) ? recordParam : "Decisions";
  const [manual, setManual] = useState<{ key: string; open?: boolean; tab?: RecordTab }>({ key: urlKey });
  const current = manual.key === urlKey ? manual : { key: urlKey };
  const open = current.open ?? urlOpen;
  const tab = current.tab ?? urlTab;
  const setOpen = (v: boolean | ((o: boolean) => boolean)) =>
    setManual((m) => { const base = m.key === urlKey ? m : { key: urlKey }; const prev = base.open ?? urlOpen; return { ...base, key: urlKey, open: typeof v === "function" ? v(prev) : v }; });
  const setTab = (v: RecordTab) => setManual((m) => ({ ...(m.key === urlKey ? m : { key: urlKey }), key: urlKey, tab: v }));

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") { setOpen(false); return; }
      if (isTypingTarget(e.target)) return;
      if (e.key === "r") setOpen((o) => !o);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const counts: Record<RecordTab, number> = {
    Decisions: groups.decisions.length, Pivots: groups.pivots.length, Asks: groups.asks.length,
    Sources: groups.sources.length, Artifacts: spec.record.artifacts.length, Remaining: spec.record.remaining.length,
    Journey: 0, Changelog: 0,
  };

  return (
    <footer className="shrink-0 border-t border-ln bg-bg">
      <div className="flex h-8 items-center gap-4 px-4 text-xs">
        <b className="text-tx font-medium">Record</b>
        <span className="flex-1 truncate text-mu">
          Decisions {counts.Decisions} · Pivots {counts.Pivots} · Asks {counts.Asks} · Sources {counts.Sources} · Artifacts {counts.Artifacts} · Remaining {counts.Remaining}
        </span>
        <button
          type="button"
          aria-label={open ? "Collapse record" : "Expand record"}
          title={open ? "Collapse record" : "Expand record"}
          onClick={() => setOpen((o) => !o)}
          className="rounded p-1 hover:bg-sf2"
        >
          {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>
      </div>
      {open && (
        <div className="flex h-[45vh] flex-col border-t border-ln">
          <div className="flex shrink-0 gap-1 overflow-x-auto px-2 py-1.5 border-b border-ln">
            {RECORD_TABS.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`shrink-0 rounded px-2.5 py-1 text-xs ${tab === t ? "bg-sf2 text-tx" : "text-mu hover:bg-sf2"}`}
              >
                {t}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <TabContent tab={tab} spec={spec} groups={groups} />
          </div>
        </div>
      )}
    </footer>
  );
}
