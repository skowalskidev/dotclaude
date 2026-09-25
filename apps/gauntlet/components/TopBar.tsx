// OWNED BY SLICE `shell`. Server component: project name + root path (link to /), ProgressRing, LiveDot, ⌘K hint, theme toggle (client child), Present (opens /p?…&present=1 in a new tab).
import path from "node:path";
import Link from "next/link";
import { Maximize2 } from "lucide-react";
import type { PublicSpec } from "@/lib/types";
import { ProgressRing } from "./ProgressRing";
import { LiveDot } from "./LiveDot";
import { ThemeToggle } from "./ThemeToggle";

export interface TopBarProps { spec: PublicSpec; planPath: string }

export function TopBar({ spec, planPath }: TopBarProps) {
  const done = spec.sections.filter((s) => s.status === "done").length;
  const root = path.dirname(spec.planDir);
  const rootChip = root.split(path.sep).filter(Boolean).slice(-2).join("/");
  return (
    <header className="flex h-11 items-center gap-3 border-b border-ln px-3.5">
      <span className="font-semibold">{spec.title}</span>
      <Link href="/" className="text-mu font-mono text-xs hover:text-tx">{rootChip}</Link>
      <ProgressRing done={done} total={spec.sections.length} />
      <span className="flex-1" />
      <LiveDot planPath={planPath} />
      <kbd title="Command palette" className="rounded-md border border-ln px-1.5 py-0.5 text-mu font-mono text-[11px]">⌘K</kbd>
      <ThemeToggle />
      <a
        href={`/p?plan=${encodeURIComponent(planPath)}&present=1`}
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Present"
        title="Present"
        className="inline-flex items-center justify-center rounded-md p-1.5 hover:bg-sf2"
      >
        <Maximize2 size={16} />
      </a>
    </header>
  );
}
