# iOS simulator playbook

DO use this playbook for an explicitly requested simulator preview, native runtime test or simulator
recovery. Compose `references/testing-strategy.md` and `references/dev-server-hygiene.md`; retain their
opt-in, signing, capacity, stage-deadline, worker-limit and cleanup policies. Boot headless by
default: `xcrun simctl boot` opens no window. Open the GUI only when Simon asked to look (an interactive
preview, or a co-pilot walk where he types); headless test success does not fulfill that request.
Read this file before booting for ANY native step, a co-pilot walk or screenshot capture included.
Run ONE device machine-wide: the capacity owner's `MAX_BOOTED_SIMULATORS` refuses a second.
Use ONE persistent warmed device named `agent` for every task: find it, never create a fresh one (§ One warmed agent device).
TEST: the run records the requested activity and its evidence separately from skipped native work.

## Use the project's one proven recipe

DO run simulator work through the project's ONE recorded recipe: one command or script that builds
once, boots one device headless, installs, launches with the documented environment, drives XCUITest
to a NAMED screen, screenshots it and shuts down. Record it where the project keeps its run commands
(a script, or the project's `CLAUDE.md` when the project-doc policy allows), with its measured duration
on this machine. DON'T re-derive build flags, launch environment and backend wiring per task.
DO make a bounded spike the first step when the project has no proven recipe: one device, one screen,
at most 20 minutes, and its only output is that recipe. The feature task starts after the spike.
DO stop after ONE failed boot, install or launch and report the exact command, exit and log lines.
DON'T re-boot, rebuild or switch drivers in a loop; reuse the built `.app` and `.xctestrun` for every
attempt. WHY: churned boots and rebuilds under load left devices launched, idle and never on the target
screen. TEST: a simulator task report names the recipe it used, or the spike that created it, and shows
at most one boot per device per task.

The recipe, on Apple's own stack (simctl and XCUITest; install nothing):

| Step | Command |
|---|---|
| Build once | `xcodebuild build-for-testing -scheme "$SCHEME" -destination id="$UDID" -derivedDataPath "$DD"`; reuse its `.app` and `.xctestrun` |
| Device | Find `agent` by name and reuse its UDID; create and warm it only when absent (§ One warmed agent device) |
| Boot | `xcrun simctl boot "$UDID" && xcrun simctl bootstatus "$UDID"`; no GUI, no second device, no shutdown between steps |
| Install and launch | `xcrun simctl install "$UDID" "$APP"`, then `SIMCTL_CHILD_<VAR>=… xcrun simctl launch --terminate-running-process "$UDID" "$BUNDLE_ID"` |
| Drive | ONE `xcodebuild test-without-building -xctestrun "$XCTESTRUN" -destination id="$UDID" -only-testing:<UITests>/<Walk>/test<Screen> -collect-test-diagnostics never -parallel-testing-enabled NO` per walk, settings passed as `TEST_RUNNER_<VAR>` |
| Capture | `xcrun simctl io "$UDID" screenshot "$CAPTURE"`; video per Walkthrough recording below |
| Shut down | `xcrun simctl shutdown "$UDID"` at the end of every simulator step batch and at hand-back, then `release-sim`; keep it booted only when the very next step needs it |

DO shut down your own booted simulator and `release-sim` at the end of each simulator step batch, unless
the very next step needs it. DON'T leave one booted with no lease or while the session waits on anything
else: it blocks every other session's heavy work (lease rules: `references/dev-server-hygiene.md` §
Machine-wide capacity). TEST: between batches, `status` lists no simulator for this owner unless a named
next step uses it.

DO pass `-collect-test-diagnostics never` to every `xcodebuild test` and `test-without-building`.
WHY: the default is `on-failure` (`xcodebuild -help`, Xcode 27.1), and a failed session then collects a
sysdiagnose that can run for about 10 minutes (mobile-dev-inc/Maestro#3633). TEST: no `xcodebuild`
test invocation in the run omits the flag.

## One warmed agent device

DO keep ONE persistent device named `agent` per machine and reuse it for every task, across sessions,
branches and projects. A fresh device's first boot starts the system daemons cold, and they crash:
a new device booted for an `xcodebuild test` run threw PosterBoard and WidgetRenderer crash dialogs
on macOS, then maild and siriactionsd at shutdown (Xcode 27.1, iOS 27.0 runtime, 2026-10-20). A
warmed device has already taken those first boots.
DO find it before any boot: `xcrun simctl list devices --json`, match the name `agent` on the
selected runtime. Present: reuse its UDID, no creation. Absent: create and warm it once, then reuse.
DO create it as `agent-warming` so a half-warmed device is never reused, then warm it before driving:

1. `xcrun simctl create agent-warming "<device type id>" "<runtime id>"`, boot it, run `bootstatus`.
2. Open the GUI yourself (Drive and capture below). In Settings, turn off Siri & Search.
3. Add a stock image with `xcrun simctl addmedia "$UDID" <image>`, open Photos, pick it, choose
   Use as Wallpaper. Once per device; the wallpaper extension (PosterBoard) crashes in a loop until a
   wallpaper exists (Apple Developer Forums thread 805625).
4. Shut it down, then `xcrun simctl rename "$UDID" agent`. The name `agent` means warmed.

DO shut `agent` down and `release-sim` it at task end, and never delete it. DON'T delete, erase or
recreate it for a clean state: wipe app state with `xcrun simctl uninstall` plus `keychain reset`
(Local backend safety). Delete only a device you created for a one-off reason (another runtime, a
parallel-device experiment), after its task, by its own UDID. A project handover or cleanup rule that
says "delete your simulator" yields to this section; apply it to one-off devices only. A runtime that
`agent` cannot run (an OS upgrade removed it) is the one reason to create the next `agent` through
the steps above and then delete the old one.
TEST: `xcrun simctl list devices` shows one `agent` before and after the task, its UDID unchanged
across tasks; no task report shows a device created for a recipe step, and none shows `agent` deleted.

## Preflight before claiming or booting

DO record one local run receipt with the owner, workspace/source fingerprint and requested journey.
Resolve project instruction policy before reading project guides. Resolve git origin, connector
manifest and environment before accessing a backend; apply `rules/connectors.md` and
`references/connectors-setup.md`. Keep project paths, device identifiers and credentials out of this
shared playbook. Complete all five checks before boot:

1. **Effective Xcode.** Record `DEVELOPER_DIR` when set, `xcode-select -p`, `xcrun --find simctl`
   and `xcodebuild -version`. Use the same environment for discovery, builds and execution. Resolve the
   effective developer directory below; reject Command Line Tools or a missing Xcode bundle for this
   native workflow. DON'T globally switch `xcode-select`, install Xcode or download runtimes automatically.
2. **Installed capabilities and device.** Read `xcrun simctl help` and help for each command used.
   Inspect `xcrun simctl list runtimes --json` and `xcrun simctl list devices --json`; select one available,
   compatible runtime and explicit UDID. Check device state and ownership before claiming it. Use
   `xcrun devicectl help` only when `xcrun --find devicectl` succeeds; discover its supported inspection
   commands there. A missing application named Simulator is not evidence of a missing runtime.
3. **GUI for a visible preview.** Discover the selected Xcode's installed application before boot,
   without opening it. Check Device Hub and legacy Simulator by capability, not a version-number
   branch or `open -a Simulator`. For a headless test, record GUI as unnecessary. If a requested GUI
   is missing, stop before boot and report the missing component; do not search the whole disk.
   Run the snippet below and `python3 ~/.claude/bin/local-capacity.py status` before ANY native launch,
   a repo launch script included, and read the script first. When it assumes one GUI layout (it opens
   `Simulator` by name), fix the script to use the discovery, not the invocation. TEST: no native launch
   precedes a recorded discovery result and load status (the fix for a repo script that failed with
   "Unable to find application named 'Simulator'" on a toolchain where the GUI is Device Hub).
4. **App artifact.** Record the `.app` path, bundle identifier, scheme/configuration, simulator SDK
   and architecture, source revision plus uncommitted-input fingerprint, generated inputs, dependencies
   and signing/entitlements. Reuse cached output only when those inputs match the requested branch.
   Keep sources stable during a build. Rebuild mismatches under admission; use the runtime signing
   procedure before claiming Keychain or other platform-service coverage. An installed app can still
   be yesterday's artifact.
   DO export each test-products build to one absent destination; do not pre-create or reuse an
   `.xctestproducts` destination. After a successful build and final signing, bind the source
   fingerprint to the exact produced bundle path and app/test executable SHA-256s in its receipt.
   Use that bundle for install and test. Stop on nested or multiple candidate bundles until the
   selected output matches that receipt; a source annotation beside old output is not binary proof
   (the fix for a new export nested inside an older runnable bundle). TEST: the runtime receipt
   identifies the successful build's exact output and matching executable hashes before boot.
5. **Backend.** Name fixture, isolated copied-data or authorized live mode and every service endpoint.
   Verify the project's supported runtime, locked dependencies and startup inputs. Reserve the port
   lane and reject stale listeners. Inside the admitted run, start only owned required services and
   verify SHA, run ID and cwd through the identity handshake before booting the device. A fixture UI
   can retain real native authentication or purchase boundaries; list them and do not infer they work
   from a rendered fixture screen.

DO use this bounded discovery snippet for the two installed GUI layouts. These paths are observed
installation candidates, not an Apple promise; inspect the selected bundle if neither exists:

```sh
selected_dev=${DEVELOPER_DIR:-$(xcode-select -p)}
case "$selected_dev" in
  *.app) selected_dev="$selected_dev/Contents/Developer" ;;
esac
selected_dev=$(cd "$selected_dev" && pwd -P) || exit 1
case "$selected_dev" in
  */Contents/Developer) xcode_contents=${selected_dev%/Developer} ;;
  *) echo 'Selected developer directory is not an Xcode bundle' >&2; exit 1 ;;
esac
sim_gui=
for candidate in "$xcode_contents/Applications/DeviceHub.app" \
                 "$selected_dev/Applications/Simulator.app"; do
  if [ -d "$candidate" ]; then sim_gui=$candidate; break; fi
done
[ -n "$sim_gui" ] || { echo 'No simulator GUI in selected Xcode' >&2; exit 1; }
printf '%s\n' "$sim_gui"
```

TEST: the receipt names the effective toolchain, available runtime, owned UDID, matching artifact,
GUI path or headless mode, and backend identity before the first boot attempt.

## Execute one foreground lifecycle

DO prepare one local foreground orchestrator and its cleanup before admission. Use the capacity
owner's claim/run/stage procedure and its Python descriptor-inheritance contract at every subprocess
boundary. Keep the same lease through service startup, build if needed, boot, install, launch, tests
or viewing, and device shutdown. Never split a preview into detached unowned commands or nested leases.

DO run these stages in order, with explicit UDID and fail-fast exit handling. Wrap each command in
`local-capacity.py stage` using the owning policy's deadline; bound launch and screenshot stages to
60 seconds each. Stop the next stage on any failed exit or timeout:

| Stage | Command or proof |
|---|---|
| Boot | `xcrun simctl boot "$UDID"`, headless; enter only with the claimed device in Shutdown |
| Wait | `xcrun simctl bootstatus "$UDID"`; use installed help, omit `-b` because it can initiate a new boot |
| Install | `xcrun simctl install "$UDID" "$APP"`; confirm artifact and bundle identifier |
| Launch | The project's own launch script when it has one (read it first, per step 3); else `xcrun simctl launch --terminate-running-process "$UDID" "$BUNDLE_ID"` with every option and `SIMCTL_CHILD_` variable the project's declared configuration passes, the backend override included (see Local backend safety below) |
| GUI (visible preview, walk or capture) | Open the resolved path inside the lease after boot readiness, select the owned UDID and verify no unrelated device started |
| Ready | Verify backend identity and the requested app/test readiness signal; preserve startup logs and errors. TEST: the app's first request appears in the owned local API log before any sign-in or other write |
| Drive (requested walk, preview or capture) | Navigate and capture per Drive and capture below; Simon is never asked to open the GUI or tap |
| Capture (requested UI/preview/capture only) | The driver's own screenshot (a UI test's `app.screenshot()` written to a host folder), or `xcrun simctl io "$UDID" screenshot "$CAPTURE"`; inspect the image for the intended app and state |
| Test or hold | Run the requested scoped checks, or retain the owned preview until its stated deadline |
| Cleanup | Stop exact owned service groups, shut down the owned UDID and verify Shutdown before claim release |

DO open `"$sim_gui"` with `open "$sim_gui"` only inside the admitted lifecycle after the owned device
is booted and ready. Select that UDID using the installed GUI's supported controls or targeting
options; verify the selected device and actual device list. A GUI can auto-boot its last device, so
preflight discovery must stay read-only. If a foreign device starts, stop progression and report it;
do not claim or shut down that unrelated device automatically.

DO distinguish three proofs for requested UI/preview/capture: process launch, simulator framebuffer
and desktop GUI. Skip GUI and capture for headless runtime tests unless separately requested. Install success
and a process PID prove neither screen readiness nor a usable preview. Inspect the simulator capture
for the requested screen; it proves the device rendered, not that the window Simon looks at shows it.
DO count an interactive preview ready only after capturing the GUI window itself with macOS
`screencapture` (`-l <windowid>`, or `-R` on the window's bounds) and viewing that image for the device
screen, not a placeholder such as "Connecting display...". Wait at most 60 seconds after boot readiness;
past that, report the preview NOT visible with the simctl captures instead, and never write "window
open on <screen>". A delegated worker returns the window capture path; the orchestrator views it before
relaying "it's up" (the fix for a delegated run that reported the window on the target screen while it
showed "Connecting display..."). Missing macOS screen-recording/accessibility permission is an evidence
gap; report it without automatically changing permissions or declaring the app broken. TEST: a preview
receipt states exactly which of these proofs was obtained, and every interactive-preview "ready" cites a
window capture path that shows the device screen.

## Local backend safety

DO treat a Debug build launched without the project's backend override as pointed at PRODUCTION. A
launch path can ignore the Xcode scheme's launch environment, where a "Local" scheme sets the override:
`xcrun simctl launch` and an `XCUIApplication().launch()` both did, and a walk test signed in to
production and wrote a sign-in plus two analytics events (2026-10-15; the override was a backend URL
and key pair of environment variables, e.g. `<APP>_API_URL` and `<APP>_API_KEY`). A unit test is no
exception: `xcodebuild test -only-testing:<UnitTests>/...` starts the app as its test host, and the
host's startup made network calls. A run given a closed loopback port logged
`nw_endpoint_flow_failed ... 127.0.0.1:9`, so the unguarded runs before it reached the default
backend, production for a Debug build (2026-10-16).

DO apply the next block to EVERY `xcodebuild test` of the app target, unit or UI, and to every
`simctl launch`. When no local stack runs, point the override at a closed loopback port such as
`http://127.0.0.1:9`, so startup calls fail harmlessly instead of reaching production. Steps 3 and 4
need a running local stack and apply to launches and UI tests that sign in. Before ANY launch or test:

1. **Pass the override explicitly.** Read the project's declared override variables, then set each as
   `SIMCTL_CHILD_<VAR>` for `simctl launch`, or as `TEST_RUNNER_<VAR>` in the `xcodebuild` environment
   (xcodebuild hands `TEST_RUNNER_`-prefixed variables to the test host process), and for a UI test
   copy it into `app.launchEnvironment` before `launch()`. DON'T rely on the scheme.
2. **Make the UI test refuse a non-local URL.** The test reads the URL it was given and fails before
   launching unless the host is loopback (`localhost`, `127.0.0.1`, `::1`).
3. **Prove the backend before any sign-in.** Tail the owned local API log and wait for the app's first
   request there. No request seen: stop before any sign-in, because the app is on another backend.
4. **Wipe earlier app state on the owned device:** `xcrun simctl uninstall "$UDID" "$BUNDLE_ID"` then
   `xcrun simctl keychain "$UDID" reset`, so a stored session or token from a prior run cannot skip
   the check or leak across backends.

TEST: no `xcodebuild test` of the app target runs without a loopback backend override in its
`TEST_RUNNER_` environment, no sign-in or write happens before the app's first request is seen in the
local log, and the UI test asserts a loopback URL before it launches the app.

DO build every simulator test signed, with Xcode's default ad-hoc "Sign to Run Locally".
DON'T pass `CODE_SIGNING_ALLOWED=NO` to an `xcodebuild` test of the app target: the unsigned app loses
its keychain items across a relaunch, so a signed-in session comes back signed out and a relaunch or
cold-start test fails as if the product were broken (the fix for a cold-start UI test that failed two
unsigned runs and passed 2/2 signed).
TEST: no app-target `xcodebuild test` carries `CODE_SIGNING_ALLOWED=NO`, and a relaunch test that
fails on the signed-out screen is rerun signed before it is called a product bug.

## Drive and capture

DO open the simulator GUI yourself for every requested iOS walk, preview or capture: the resolved
`$sim_gui` above, inside the admitted lifecycle, with the owned UDID selected and verified. DON'T ask
Simon to open the window, pick the device or run `open -a Simulator`, which fails on Xcode 27 where
Device Hub replaces Simulator.app. When Device Hub does not show the owned device (a `devices://<UDID>`
URL did not help on 2026-10-15), say so in the receipt and keep driving and capturing; Simon watches
the screenshots you take.

DO navigate the app and take every screenshot yourself. Default to XCUITest, the proven path on
Xcode 27: add a UI test to the app's UI test target that performs the walk (sign in, open the menu,
open a screen) and writes each screenshot to a host folder with
`try app.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("<step>.png"))`.
Pass `dir` as `TEST_RUNNER_<NAME>` in the `xcodebuild` environment, which xcodebuild hands to the test
runner (the placement rule is in `references/testing-strategy.md`). Run it as one bounded stage on the
owned UDID, with the backend override from Local backend safety. One test per paced step, or one
parameterised test that takes the step name, fits a paced walk. Read every screenshot and confirm the
intended screen before the next step.

DO treat the AXe CLI (cameroncooke/AXe, MIT, 2.3k stars, last push 2026-07-21) as an optional fast
path, used only after a no-op check, and NEVER on a device where an XCUITest run is live. Two open
issues explain the 2026-10-15 failures on Xcode 27: `axe tap` exits before the simulator HID daemon
activates its service, so the tap is dropped while success is printed (AXe#71; `--post-delay 0.5`
delivered 3 of 3 there; fix PR #73 unmerged), and `axe describe-ui` restarts testmanagerd, which ends
other XCUITest runners' sessions (AXe#76). To try it, run `axe --version` (install with
`brew install cameroncooke/axe/axe` when absent; DON'T run `axe init`, which writes skill files into AI
clients), then `axe tap ... --post-delay 0.5` on one element and take a screenshot to prove the screen
changed. Unchanged: switch to XCUITest at once, no retry. Changed: continue with `describe-ui`
(read), `tap --label`/`--id`/`type`/`swipe` (act) and `axe screenshot` (capture), re-checking after
each transition. TEST: no AXe command runs while an `xcodebuild test` on the same UDID is live.

DO split a co-pilot walk by the rule in `/sk:test-copilot`: you drive the lead-up and every step that is
not new, and Simon types only the inputs the change adds, in the GUI window you opened. Screenshot each
step yourself either way.

DON'T hand navigation to Simon because one driver failed; switch driver. A step no driver can reach is
named in the receipt with the step, never delegated silently.

DO record the driver, its version and the no-op check result in the receipt. TEST: no walk step asks
Simon to open the simulator, tap a screen that is not a new input, or paste a screenshot; each step
names a capture file you took; an AXe step has a recorded changed-screen check.

Rejected as the default, rechecked 2026-10-15: Maestro (mobile-dev-inc/Maestro, 16k stars) is built
around scripted YAML flows and its README names no Xcode version support.

## Hold for the user, then clean up

DO shut down the device and release its claim as soon as the task's last capture or walk ends, not at
the end of the session. Leave ONE device booted at hand-back only when Simon asked to look at it, and
name its UDID and the exact `xcrun simctl shutdown <UDID>` command in the hand-back. TEST: after
hand-back, `local-capacity.py status` shows no simulator claim or booted device for this owner unless
the hand-back names it.

DO retain an explicitly requested preview at hand-back as the exception to end-of-turn cleanup.
Keep its runner and capacity lease alive throughout viewing. Default the viewing deadline to the
earlier of readiness plus 55 minutes or the run deadline minus 5 minutes; reserve that final budget
for cleanup. If startup consumed the viewing budget, clean up and report no usable hold. Do not extend
the capacity owner's maximum to create a longer preview. TEST: the receipt has finite absolute start,
viewing-end and cleanup deadlines, and never promises an indefinite preview.

DO give Simon a short receipt: owner; device name and UDID; bundle ID and source; GUI and rendered-screen
proof; backend mode/service identity and ports; start/deadline; log/capture paths; exact stop and restart
commands. Save the detailed receipt locally. Derive stop from the verified runner identity and owned
process groups; restart repeats preflight and admission with the same local orchestrator. A bare
`kill <pid>` without receipt/identity validation risks PID reuse.

DO implement cleanup with the owner's signal/trap discipline before launching services. Stop owned
server groups and verify their ports are clear; shut down only the owned UDID, verify Shutdown, then
release its claim and lane. The runner releases capacity only after owned resources are clear. Keep
an uncertain lease and explicit cleanup action when shutdown fails. Retain the shut-down `agent` device,
derived data and build caches. DON'T reset shared Apple services as routine hand-back cleanup, erase
or delete simulators (the shared `agent` above, always), use `shutdown all`, global `killall`, bypass locks or kill unrelated listeners.
TEST: interruption and viewing expiry both enter exact-owned teardown; a non-Shutdown device never
produces a successful release receipt.

## Diagnose the failed stage before retrying

DO keep the failed command, exit, elapsed time and bounded logs. Use the following next check;
research an unresolved failure against current primary sources before repeating the same fix.

| Symptom | Next check and stop condition |
|---|---|
| Toolchain/runtime mismatch | Compare effective `DEVELOPER_DIR`, resolved tools, runtime availability, SDK and artifact architecture. Stop until compatible inputs are selected explicitly. |
| GUI missing | Check both selected-bundle candidates and installed capabilities. Stop the visible-preview path before boot; report a separate headless result only when requested. |
| Boot or bootstatus failure/timeout | Inspect the exact UDID's actual state and logs. Do not enter install/tests or hide a boot retry in `bootstatus -b`; clean up the owned lifecycle. |
| Legacy bridge descriptor error | Inspect every Python intermediary's `pass_fds` and inherited environment. Repair the caller; keep validation and the single lease. |
| Keychain/signing failure, or signed out after a relaunch | Check the build did not pass `CODE_SIGNING_ALLOWED=NO`. Compare the built host's signature and entitlements to its runtime configuration; execute the scoped platform-service fixture before the suite. Keep product auth unchanged. |
| Install/launch/wrong screen | Compare bundle ID, simulator architecture, source/build fingerprint and launch configuration. Inspect startup logs; do not repeatedly reinstall a mismatched artifact. |
| Stale backend or blank web content | Check service SHA/run ID/cwd, app endpoint configuration and port ownership. A responding foreign listener never passes readiness. |
| GUI cannot be inspected | Preserve simulator-screen evidence separately; name missing desktop evidence/permission. Do not silently grant permissions. |
| Slow admission or overloaded run | Record capacity/load and the current holder; defer per the capacity protocol. Do not self-prioritize, loosen thresholds or kill unrelated work. |
| `watchdog: HOT` on a simulator process | The named owner shuts down its own UDID and reports it; never stop another owner's device. On the next boot of that device, confirm Siri & Search is off before driving. |
| macOS crash dialog from a simulator daemon (PosterBoard, WidgetRenderer, maild, siriactionsd, other) | Read the report in `~/Library/Logs/DiagnosticReports`: a `procPath` under the simulator runtime volume is an Apple simulator bug, not the app under test; an app-bundle `procPath` is the app's own crash and is diagnosed as a product failure. Report the daemon, time and exit reason, once. DON'T reboot, recreate the device or rerun the suite over a daemon report. Confirm `agent` is the warmed device; a fresh device is the usual cause. `SIGTERM_TIMEOUT` reports from maild or siriactionsd at shutdown are expected noise. Disabling ReportCrash (`launchctl`) is machine-wide: offer it as an option and run it only on Simon's explicit yes. |
| Incomplete xcodebuild result | Apply the testing owner's full-result procedure. A nested passing suite or timed-out runner cannot establish success. |
| Stale Apple discovery | Compare fresh `simctl` actual device states with supported `devicectl` inspection and GUI state. Do not infer a phantom process or recreate a device from the GUI alone. |

DO restart the GUI first during authorized stale-discovery recovery and recheck the same evidence.
Restart a shared CoreDevice service only with explicit, scoped recovery authorization, evidence the
GUI restart did not resolve the mismatch, and a check that no other simulator, physical-device or
debug session is active. Discover the installed service and its supported recovery mechanism before
acting; do not apply a generic process-kill recipe. Reconcile CLI and GUI lists afterwards. A reported
incident where service restart aligned stale lists is observational evidence, not an Apple-confirmed
universal bug. TEST: shared-service recovery never runs automatically at task completion or while
another device session is active.

## Primary sources

DO recheck installed help when the toolchain changes. Online sources checked 2026-10-09 (AXe README row 2026-10-15, last four rows 2026-10-20):

| Source | Scope |
|---|---|
| [Apple command-line selection](https://developer.apple.com/documentation/xcode/configuring-command-line-tools-settings) | Per-command `DEVELOPER_DIR` without changing the global selection |
| [Apple Device Hub](https://developer.apple.com/documentation/xcode/device-hub) and [WWDC26 Device Hub](https://developer.apple.com/videos/play/wwdc2026/260/) | Device Hub GUI; Xcode 27 introduction and shared underlying technology with `devicectl` |
| [Apple command-line tool reference](https://developer.apple.com/documentation/xcode/xcode-command-line-tool-reference) | Installed `simctl` and `devicectl` help is the capability reference |
| [AXe README](https://github.com/cameroncooke/AXe) and installed `axe --help` | Claimed Xcode 26/27 support and commands; `tap` was a no-op on Xcode 27.0 here (2026-10-15) |
| [Apple device captures](https://developer.apple.com/documentation/xcode/capturing-screenshots-and-videos-from-devices) | Device screenshots and videos; separate from observing a macOS window |
| [AXe#71](https://github.com/cameroncooke/AXe/issues/71), [#73](https://github.com/cameroncooke/AXe/pull/73), [#76](https://github.com/cameroncooke/AXe/issues/76) (open, read 2026-10-20) | Dropped first gesture on Xcode 27 and its `--post-delay` workaround; `describe-ui` ending other XCUITest sessions |
| [Maestro#3633](https://github.com/mobile-dev-inc/Maestro/issues/3633) and installed `xcodebuild -help` (Xcode 27.1, 2026-10-20) | `-collect-test-diagnostics on-failure` default and the sysdiagnose delay |
| [Developer forums thread 805625](https://developer.apple.com/forums/thread/805625), [806225](https://developer.apple.com/forums/thread/806225), [744912](https://developer.apple.com/forums/thread/744912) (read 2026-10-20) | Xcode 26.1 wallpaper extension (MercuryPosterExtension/PosterBoard) crash loop and the once-per-device Use as Wallpaper workaround; ReportCrash CPU from that loop, no Apple fix; simulator daemon "quit unexpectedly" alerts as Apple-side assertion failures |
| [Developer forums thread 682253](https://developer.apple.com/forums/thread/682253) | Community Siri & Search workaround for simulator Spotlight CPU (Xcode 13 era; no Apple root cause) |

DO keep Python FD and native signing sources with their owning procedures above; do not duplicate
those policies here. TEST: this playbook composes one capacity owner and one testing owner.

## Walkthrough recording

DO record explicitly requested simulator walkthroughs with the installed `simctl io <owned-UDID>
recordVideo --codec=h264` capability (the installed default is hevc) inside the existing admitted lifecycle. Confirm its help before invocation,
wait for `Recording started`, replay the reset journey, then send SIGINT to the owned recorder and
await its exit before shutdown or lease release. Inspect the finalized video from first to last state.
TEST: the receipt identifies the owned recorder, completed file and playback check; no recording
process survives hand-back.
