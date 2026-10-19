# iOS simulator playbook

DO use this playbook for an explicitly requested simulator preview, native runtime test or simulator
recovery. Compose `references/testing-strategy.md` and `references/dev-server-hygiene.md`; retain their
opt-in, signing, capacity, stage-deadline, worker-limit and cleanup policies. Default an interactive
preview request to a visible GUI; headless test success does not fulfill that request. Read this file
before booting for ANY native step, a co-pilot walk or screenshot capture included. TEST: the run
records the requested activity and its evidence separately from skipped native work.

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
| Boot | `xcrun simctl boot "$UDID"`; enter only with the claimed device in Shutdown |
| Wait | `xcrun simctl bootstatus "$UDID"`; use installed help, omit `-b` because it can initiate a new boot |
| Install | `xcrun simctl install "$UDID" "$APP"`; confirm artifact and bundle identifier |
| Launch | The project's own launch script when it has one (read it first, per step 3); else `xcrun simctl launch "$UDID" "$BUNDLE_ID"` with every option and `SIMCTL_CHILD_` variable the project's declared configuration passes, the backend override included (see Local backend safety below) |
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
for the requested screen, then verify that the selected GUI displays that UDID for an interactive
preview. Capture the desktop/window through an already authorized mechanism when available. Missing
macOS screenshot/accessibility permission is an evidence gap; report it without automatically changing
permissions or declaring the app broken. TEST: a preview receipt states exactly which of these proofs
was obtained, and does not call unseen desktop contents verified.

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
path, used only after a no-op check. Observed failure, 2026-10-15, Xcode 27.0 with AXe 1.8.0:
`axe describe-ui` worked, but `axe tap` (by label, by id and by coordinates) and `axe button home`
printed success and changed nothing on screen. Root cause not established. Its README states Xcode 27
support, so recheck it on a later release. To try it, run `axe --version` (install with
`brew install cameroncooke/axe/axe` when absent; DON'T run `axe init`, which writes skill files into AI
clients), then tap one element and read `axe describe-ui --udid "$UDID"` or take a screenshot to prove the
screen changed. Unchanged: switch to XCUITest at once, no retry. Changed: continue with `describe-ui`
(read), `tap --label`/`--id`/`type`/`swipe` (act) and `axe screenshot` (capture), re-checking after
each transition.

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
an uncertain lease and explicit cleanup action when shutdown fails. Retain the shut-down device,
derived data and build caches. DON'T reset shared Apple services as routine hand-back cleanup, erase
or delete simulators, use `shutdown all`, global `killall`, bypass locks or kill unrelated listeners.
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

DO recheck installed help when the toolchain changes. Online sources checked 2026-10-09 (AXe row 2026-10-15):

| Source | Scope |
|---|---|
| [Apple command-line selection](https://developer.apple.com/documentation/xcode/configuring-command-line-tools-settings) | Per-command `DEVELOPER_DIR` without changing the global selection |
| [Apple Device Hub](https://developer.apple.com/documentation/xcode/device-hub) and [WWDC26 Device Hub](https://developer.apple.com/videos/play/wwdc2026/260/) | Device Hub GUI; Xcode 27 introduction and shared underlying technology with `devicectl` |
| [Apple command-line tool reference](https://developer.apple.com/documentation/xcode/xcode-command-line-tool-reference) | Installed `simctl` and `devicectl` help is the capability reference |
| [AXe README](https://github.com/cameroncooke/AXe) and installed `axe --help` | Claimed Xcode 26/27 support and commands; `tap` was a no-op on Xcode 27.0 here (2026-10-15) |
| [Apple device captures](https://developer.apple.com/documentation/xcode/capturing-screenshots-and-videos-from-devices) | Device screenshots and videos; separate from observing a macOS window |

DO keep Python FD and native signing sources with their owning procedures above; do not duplicate
those policies here. TEST: this playbook composes one capacity owner and one testing owner.

## Walkthrough recording

DO record explicitly requested simulator walkthroughs with the installed `simctl io <owned-UDID>
recordVideo` capability inside the existing admitted lifecycle. Confirm its help before invocation,
wait for `Recording started`, replay the reset journey, then send SIGINT to the owned recorder and
await its exit before shutdown or lease release. Inspect the finalized video from first to last state.
TEST: the receipt identifies the owned recorder, completed file and playback check; no recording
process survives hand-back.
