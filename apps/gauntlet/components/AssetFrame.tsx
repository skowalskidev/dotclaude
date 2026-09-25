// OWNED BY SLICE `canvas`. Renders one Asset: text → prose box; image → <img src={url}> (click opens full view); html → <iframe sandbox="allow-scripts allow-same-origin" src={url}> bounded to the stage, plus "Open ↗" (new tab, same url). Never srcdoc, never base64.
import type { Asset, AssetRole } from "@/lib/types";

export interface AssetFrameProps { asset?: Asset; role: AssetRole; persona?: "desktop" | "mobile"; fill?: boolean }

export function AssetFrame({ asset, persona }: AssetFrameProps) {
  if (!asset) return <div className="grid h-full place-items-center text-mu">—</div>;

  if (asset.kind === "text") {
    return (
      <div className="h-full overflow-auto whitespace-pre-wrap p-5 font-mono text-xs text-mu">
        <div className="text-tx">{asset.label}</div>
        {asset.text}
      </div>
    );
  }

  if (asset.kind === "image") {
    if (!asset.url) return <div className="grid h-full place-items-center text-mu">—</div>;
    return (
      <a href={asset.url} target="_blank" rel="noreferrer" className="block h-full w-full">
        <img src={asset.url} alt={asset.label} className="h-full w-full object-contain object-top" />
      </a>
    );
  }

  if (!asset.url) return <div className="grid h-full place-items-center text-mu">—</div>;
  const frame = <iframe title={asset.label} sandbox="allow-scripts allow-same-origin" src={asset.url} className="h-full w-full border-0 bg-white" />;
  return persona === "mobile" ? <div className="mx-auto h-full max-w-[390px]">{frame}</div> : frame;
}
