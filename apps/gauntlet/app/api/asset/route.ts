// OWNED BY SLICE `api-plan`. GET ?plan=…&path=… → stream the file (assetPathOrThrow), Content-Type by extension (html/webp/png/jpg/svg/json/txt/md), ETag = size+mtime, 304 on If-None-Match, Cache-Control: no-cache. HTML gets `Content-Security-Policy: default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:; frame-src about: blob:; connect-src 'none'` (self-contained mockups need nothing else) and X-Frame-Options omitted. 404 → {error}.
import { promises as fs, createReadStream } from "node:fs";
import { Readable } from "node:stream";
import path from "node:path";
import type { NextRequest } from "next/server";
import { assetPathOrThrow, planPathOrThrow } from "@/lib/paths";

export const dynamic = "force-dynamic";

const CONTENT_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".webp": "image/webp",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".json": "application/json",
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
};

const HTML_CSP =
  "default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:; frame-src about: blob:; connect-src 'none'";

export async function GET(request: NextRequest) {
  let filePath: string;
  try {
    const planPath = planPathOrThrow(request.nextUrl.searchParams.get("plan"));
    const rel = request.nextUrl.searchParams.get("path");
    if (!rel) throw new Error("path query parameter required");
    filePath = assetPathOrThrow(planPath, rel);
  } catch (err) {
    return Response.json({ error: err instanceof Error ? err.message : String(err) }, { status: 400 });
  }

  try {
    const stat = await fs.stat(filePath);
    const etag = `"${stat.size}-${stat.mtimeMs}"`;
    const ifNoneMatch = request.headers.get("if-none-match");
    if (ifNoneMatch === etag) {
      return new Response(null, { status: 304, headers: { ETag: etag, "Cache-Control": "no-cache" } });
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = CONTENT_TYPES[ext] ?? "application/octet-stream";
    const headers: Record<string, string> = {
      "Content-Type": contentType,
      ETag: etag,
      "Cache-Control": "no-cache",
    };
    if (ext === ".html") headers["Content-Security-Policy"] = HTML_CSP;

    const body = Readable.toWeb(createReadStream(filePath)) as ReadableStream<Uint8Array>;
    return new Response(body, { headers });
  } catch (err) {
    return Response.json({ error: err instanceof Error ? err.message : String(err) }, { status: 404 });
  }
}
