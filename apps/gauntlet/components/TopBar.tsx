// OWNED BY SLICE `shell`. Server component: project name + root path (link to /), ProgressRing, LiveDot, ⌘K hint, theme toggle (client child), Present (opens /p?…&present=1 in a new tab).
import type { PublicSpec } from "@/lib/types";
import { ProgressRing } from "./ProgressRing";
import { LiveDot } from "./LiveDot";
export interface TopBarProps { spec: PublicSpec; planPath: string }
export function TopBar({ spec, planPath }: TopBarProps) {
  const done = spec.sections.filter((s) => s.status === "done").length;
  return (
    <header className="flex h-11 items-center gap-3 border-b border-ln px-3">
      <span className="font-semibold">{spec.title}</span>
      <ProgressRing done={done} total={spec.sections.length} />
      <span className="flex-1" />
      <LiveDot planPath={planPath} />
    </header>
  );
}
