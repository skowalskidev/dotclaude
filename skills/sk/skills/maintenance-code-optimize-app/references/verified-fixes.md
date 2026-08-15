# Verified fixes — the recipes (optimize-app)

The proven fix recipes for `/sk:maintenance-code-optimize-app`. SKILL.md names the rule; apply these when it's in play.
Overarching rule: **fix payload, not scheduling** — deferring a 45 MB payload still ships 45 MB. Re-encode /
re-size first; loading strategy is the second-order fix.

## Video

Check the bitrate before anything else. Landing clips at 3.4–8.4 Mbps for 720x1280/24fps were **3–5x
over-encoded**.

- **CRF 18 is "visually lossless"** for x264 (18–21 is the recommended high-quality web range). Use CRF 18
  when Simon asks to preserve sharpness — he has explicitly asked for quality over size.
- **Encode once, H.264/MP4 only.** For short social clips, multi-format AV1/VP9 `<source>` ladders are not
  worth it (they're for medium/long-form content).
- `-preset veryslow` (one-time encode), `-movflags +faststart` (progressive playback), `-c:a copy` (avoids
  audio generational loss).
- **`-nostdin` is mandatory** in a `while read` loop — ffmpeg otherwise eats the loop's stdin and silently
  mangles/skips files. This actually happened.
- **Verify fidelity objectively with SSIM** (1.0 = identical), don't eyeball it:
  ```bash
  ffmpeg -nostdin -i new.mp4 -i original.mp4 -lavfi ssim -f null -
  ```
  Target SSIM >= 0.99. Real result: 45.2 MB -> 24.7 MB (45% smaller) at SSIM 0.993–0.995, with
  resolution/framerate/duration unchanged.
- **Upload re-encodes to a NEW path** (e.g. `landing/optimized/**`) and leave the originals in place —
  reverting is then a URL swap, not a restore.

## Images

- **Route everything through `next/image`.** A raw `<img>` in a React 19 app makes React emit
  `<link rel="preload" as="image">` for the **full unoptimized source** — a 1.5 MB PNG was being eagerly
  fetched at high priority for a decorative `aria-hidden` element.
- **Art direction: `<picture>` must stay.** If mobile and desktop are different crops (e.g. 3420x1854
  landscape vs 772x1672 portrait), a single `<Image>` **loses the mobile crop**. Next's officially documented
  answer is `getImageProps()` + `<picture>` (Next >= 14.1):
  ```tsx
  import Image, { getImageProps } from "next/image";
  const common = { alt, sizes: "(max-width: 640px) 100vw, 320px" };
  const { props: { srcSet: mobile } }        = getImageProps({ ...common, width: mw, height: mh, src: mobileSrc });
  const { props: { srcSet: desktop, ...rest } } = getImageProps({ ...common, width: dw, height: dh, src: desktopSrc });
  <picture>
    <source media="(max-width: 640px)" srcSet={mobile} width={mw} height={mh} />
    <source srcSet={desktop} width={dw} height={dh} />
    <img {...rest} alt={alt} style={{ width: "100%", height: "auto", display: "block" }} />
  </picture>
  ```
  Destructure `...rest` from the **desktop** call (the `<img>` is the desktop fallback). Repeat `alt`
  explicitly — `jsx-a11y` can't see it through the spread and will warn.
- **Put `width`/`height` on each `<source>`, not just the `<img>`.** That's how `<picture>` declares a
  per-crop aspect ratio without forcing one crop's ratio onto the other. Fixes `unsized-images` without
  risking CLS.
- Sanity-check natural vs displayed size (`naturalWidth` vs `getBoundingClientRect().width`). Shipping 772px
  for a 298px slot is the tell.
- Measured result: **5,763 KB -> 274 KB (96%)** just by routing through `next/image` (auto WebP/AVIF).

## Media lazy-loading

- **`loading="lazy"` on `<video>`/`<audio>` is a real standard** (Chrome 148 at 100%; Firefox/WebKit in
  review). Unsupported browsers ignore it — safe progressive enhancement. It defers fetch *and* autoplay
  until near-viewport.
- **NEVER lazy-load above-the-fold media.** Google's own guidance: it de-prioritizes the fetch behind
  scripts/styles and measurably delays LCP (developers.google.com regressed exactly this way). Keep
  above-the-fold `preload="metadata"` and eager; use `preload="none"` + `loading="lazy"` only below the fold.
- `@types/react@19` doesn't declare `loading` on video/audio. Use declaration merging (see
  `types/react-media-loading.d.ts` in a personal project) — not `any`, not `@ts-expect-error`. The type parameter
  arity must match React's generic interface or the merge silently doesn't apply.
- **Reuse the same URL across duplicate clips** so the HTTP cache dedupes them. A "lazy video loaded anyway!"
  symptom is usually just a cache hit from an above-fold twin sharing the URL — verify with
  `readyState` / `buffered` before calling it a bug.

## Accessibility & agentic-browsing audits (Rule 5)

- **`agentic-browsing`** = `agent-accessibility-tree` + `cumulative-layout-shift` + `llms-txt` (weight 1
  each, so one failure = 0.67).
- **`agent-accessibility-tree`**: axe's `aria-valid-attr-value` only checks that `aria-controls` resolves to
  an element **in the DOM**. Radix `TabsTrigger` emits `aria-controls` even with zero `TabsContent` rendered
  -> guaranteed failure. **Fix: use `ToggleGroup type="single"`**, which emits no `aria-controls` (state is
  `data-state="on"|"off"`). Guard `onValueChange` — it fires `""` on deselect.
- **`heading-order`**: headings must not skip levels. **CSS is often coupled to the tag name**
  (`.dfy-item-text h4`, `.price-card h4`, `.footer-grid h5`) — every tag change needs a paired selector
  update, or you silently restyle the page. Always grep the CSS before retagging.

## CSP (Rule 6)

Host wildcards match subdomains **at any depth**, so `https://*.sentry.io` covers a nested DSN host like
`o<id>.ingest.de.sentry.io`. Sentry's browser SDK needs it in **`connect-src`**; without it every client-side
error report is silently blocked and Sentry sees nothing. `worker-src blob:` covers Replay. `script-src` CDN
entries only matter for the loader script (N/A when bundling the npm SDK).

**A CSP console error on every page load also tanks Best Practices** (`errors-in-console` +
`inspector-issues`). One real case: a Next `<Link>` on the marketing host pointing at a route the proxy
307-redirects to another origin (`app.` subdomain). Next prefetches the route's RSC payload (`?_rsc=`); that
`fetch` follows the redirect cross-origin and `connect-src` blocks it. The right fix is **`prefetch={false}`
on cross-host links, not widening the CSP** — a cross-origin `<Link>` can't soft-navigate anyway (Next falls
back to a full load), so the prefetch was pure waste. Don't loosen a security header to silence a request
that shouldn't happen. **When fixing a repeated pattern, grep the WHOLE tree, not a hand-picked file list** —
I fixed Header/Footer/ads-for, deployed, and the error persisted because `PricingSection` and
`StickyStartButton` (which also render on the landing) still prefetched. `grep -rn --include='*.tsx'
'<Link href='` across all of `app/`, filter to the cross-host routes, and re-verify on the LIVE site after the
rollout — not just locally.

**Prove CSP fixes empirically**, don't just read the spec: fetch the real ingest host from the page and
confirm it reaches the network (an HTTP 401 means it arrived and was rejected — success) with zero
`securitypolicyviolation` events.

## Gotchas that have burned us

- **The in-app Browser pane reports `visibilityState: "hidden"`** — so IntersectionObserver never fires and
  CSS animations never complete. This single root cause explains both "lazy-load isn't triggering" and "Radix
  overlays linger at `data-state=closed`". Use the **debug Chrome**, not the preview pane, for anything
  involving viewport/animation.
- **Don't conclude a regression without a differential test.** Check out the previous commit and prove the
  old code behaves differently. A "Cancel is broken" finding turned out to be a pre-existing test artifact.
- **Next only typechecks files in its build graph** — orphan test files never break `npm run build`.
- **A stale `.next/dev/types/validator.ts` can fail `tsc --noEmit`** with a bogus TS1128. It's a generated
  dev artifact; delete `.next/dev/types/` and re-run.
- **Firebase CLI account drift:** `firebase login:list` has shown your work email (work) active on
  a personal project. Always `firebase login:use <your-personal-email>` and confirm `firebase use` before any
  CLI/MCP call. When in doubt use the Admin SDK with the project's own service-account key.
