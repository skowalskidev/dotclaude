# iOS simulator playbook

DO use this playbook for an explicitly requested simulator preview, native runtime test or simulator
recovery. Compose `references/testing-strategy.md` and `references/dev-server-hygiene.md`; retain their
opt-in, signing, capacity, stage-deadline, worker-limit and cleanup policies. Default an interactive
preview request to a visible GUI; headless test success does not fulfill that request. TEST: the run
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
| Launch | `xcrun simctl launch "$UDID" "$BUNDLE_ID"`; pass only supported options and the project's declared configuration |
| GUI (visible preview only) | Open the resolved path inside the lease after boot readiness, select the owned UDID and verify no unrelated device started |
| Ready | Verify backend identity and the requested app/test readiness signal; preserve startup logs and errors |
| Capture (requested UI/preview/capture only) | `xcrun simctl io "$UDID" screenshot "$CAPTURE"`; inspect the image for the intended app and state |
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
| Keychain/signing failure | Compare the built host's signature and entitlements to its runtime configuration; execute the scoped platform-service fixture before the suite. Keep product auth unchanged. |
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

DO recheck installed help when the toolchain changes. Online sources checked 2026-10-09:

| Source | Scope |
|---|---|
| [Apple command-line selection](https://developer.apple.com/documentation/xcode/configuring-command-line-tools-settings) | Per-command `DEVELOPER_DIR` without changing the global selection |
| [Apple Device Hub](https://developer.apple.com/documentation/xcode/device-hub) and [WWDC26 Device Hub](https://developer.apple.com/videos/play/wwdc2026/260/) | Device Hub GUI; Xcode 27 introduction and shared underlying technology with `devicectl` |
| [Apple command-line tool reference](https://developer.apple.com/documentation/xcode/xcode-command-line-tool-reference) | Installed `simctl` and `devicectl` help is the capability reference |
| [Apple device captures](https://developer.apple.com/documentation/xcode/capturing-screenshots-and-videos-from-devices) | Device screenshots and videos; separate from observing a macOS window |

DO keep Python FD and native signing sources with their owning procedures above; do not duplicate
those policies here. TEST: this playbook composes one capacity owner and one testing owner.
