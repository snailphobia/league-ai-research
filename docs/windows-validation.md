# Windows validation

Acceptance requires running the adapter on Windows and independently observing delivered keyboard and mouse events. Linux mocks alone are insufficient.

The original input milestone below records its 50-test suite. The preceding
input/capture suite passed 74 tests on Windows 11 and Server 2025; see
[capture acceptance and recorded results](capture.md#verified-results). The
combined suite with the first learned policy now passes **79 tests on Server
2025**. Its [native feedback results](visual-policy.md#native-results) include
actual application receipt, changed pixels, and full observation-to-feedback
latency. Fresh learned-policy validation on Windows 11 remains uncompleted.

The validation matrix covers named keys, modifier ordering and release, extended scan codes, representative virtual keys, Unicode including non-BMP characters, all mouse buttons, absolute coordinates, relative movement, both wheel axes, dragging, and cleanup after exceptions. It must exercise monitor corners and record the actual virtual desktop geometry.

A Windows evaluation VM can be provisioned from Microsoft's official installation media using QEMU/KVM. VM disks and installation media live in a private host directory outside this repository. Test artifacts must identify the Windows version, Python and dependency versions, observed events, and any untested platform conditions such as multi-monitor topology.

## Verified native Windows run

[Run 38624263854](https://github.com/snailphobia/league-ai-research/actions/runs/38624263854) tested revision dbc8992 on Windows Server 2025, build 26100, using Python 3.12.10 and PyDirectInput RGX 2.1.3.1. All 50 tests passed without skips: 27 portable contract tests and 23 native acceptance tests. The desktop was one monitor at 1024 by 768 pixels, independently enumerated by the native receiver.

The adapter at revision f4b9e9c also passed all 50 tests in a local Windows 11 Enterprise LTSC evaluation VM, build 26100, with a 1280 by 800 desktop, Python 3.12.10, and the same pinned backend. See the [Windows 11 summary](../artifacts/windows-11/summary.json), [native observations](../artifacts/windows-11/native-input.json), and [JUnit result](../artifacts/windows-11/junit.xml). The VM uses UEFI Secure Boot and a software TPM; unattended installation overrides compatibility checks for the evaluation VM. These results establish client Windows input delivery without claiming game, graphics-performance, or anti-cheat acceptance.

Revision dbc8992 also passed all 50 tests on that Windows 11 VM with two actual Windows display surfaces: a 1280 by 800 primary monitor at (0, 0), and a 1024 by 768 secondary monitor at (-1024, -100). The receiver independently enumerated both monitors. Native observations confirm ten corner/center clicks, including negative x and y coordinates, and rejection of both tested gaps in the virtual desktop bounding rectangle. The second display was provided by [signed Virtual Display Driver 25.7.23](https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/tag/25.7.23), installed only in the evaluation VM; it is not an adapter dependency. See the [two-monitor summary](../artifacts/windows-11-multimonitor/summary.json), [native evidence](../artifacts/windows-11-multimonitor/native-input.json), and [JUnit result](../artifacts/windows-11-multimonitor/junit.xml).

Independent native observations cover 137 distinct named keys, 92 left/right modifier combinations, a 14-key chord, raw scan/virtual-key examples, all five mouse buttons, both wheel axes and signs, exact pixel movement, native relative motion, dragging, exception cleanup, and clicks at all four desktop corners. Large wheel requests retain their sign and total, and native coordinate overflow is rejected before injection. Unicode, including Romanian characters, CJK, and a non-BMP emoji, reached a real Windows EDIT control. The control also observed Ctrl and Shift held while receiving A, plus all five mouse button messages. Mixed raw/named modifier holds preserve one ownership record and release in order.

The keyboard catalog and large modifier matrix are logged by low-level Windows hooks, which suppress forwarding of injected keyboard events during those cases to avoid triggering shell shortcuts. This proves Windows receipt and ordering, not application behavior for every shortcut. Unicode application-effect tests enable forwarding. Ordinary SendInput acceptance by a particular game remains a separate test.

See the [machine-readable summary](../artifacts/windows-server-2025/summary.json) and [generated native event evidence](../artifacts/windows-server-2025/native-input.json). These artifacts contain the synthetic test input, not personal keyboard recordings.

Published native JSON uses LF line endings. Each summary records both the original source byte hash and the published file hash; the observed events are unchanged.

## Reproduce on Windows

Run on a disposable interactive desktop: the receiver temporarily covers the virtual desktop with a topmost window.

```powershell
python -m pip install -e ".[dev]"
$env:LEAGUE_INPUT_NATIVE_TESTS = "1"
$env:LEAGUE_INPUT_EVIDENCE = "artifacts/windows-input.json"
python -m pytest -q --junitxml=artifacts/windows-junit.xml
```

The default portable run skips tests that emit real Windows input. The GitHub workflow opts in explicitly and retains the witness artifacts on failure as well as success.

## Remaining platform coverage

Native single-monitor and staggered two-monitor topologies are verified. Mixed-DPI topologies and application-specific input paths remain untested. The receiver enumerates each monitor independently, and movement acceptance targets every monitor's corners and center. Staggered layouts also exercise rejection of bounding-box corners that fall in monitor gaps.
