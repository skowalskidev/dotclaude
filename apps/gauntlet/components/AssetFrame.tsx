// OWNED BY SLICE `canvas`. Renders one Asset: text → prose box; image → <img src={url}> (click opens full view); html → <iframe sandbox="allow-scripts allow-same-origin" src={url}> bounded to the stage, plus "Open ↗" (new tab, same url). Never srcdoc, never base64.
import type { Asset } from "@/lib/types";
export interface AssetFrameProps { asset?: Asset; role: "before" | "target" | "current"; fill?: boolean }
export function AssetFrame({ asset, role }: AssetFrameProps) {
  if (!asset) return <div className="grid h-full place-items-center text-mu">—</div>;
  return <div className="p-4 text-mu">{role}: {asset.label}</div>;
}
