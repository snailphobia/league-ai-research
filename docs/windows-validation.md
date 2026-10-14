# Windows validation

Acceptance requires running the adapter on Windows and independently observing delivered keyboard and mouse events. Linux mocks alone are insufficient.

The validation matrix covers named keys, modifier ordering and release, extended scan codes, representative virtual keys, Unicode including non-BMP characters, all mouse buttons, absolute coordinates, relative movement, both wheel axes, dragging, and cleanup after exceptions. It must exercise monitor corners and record the actual virtual desktop geometry.

A Windows evaluation VM can be provisioned from Microsoft's official installation media using QEMU/KVM. VM disks and installation media live in a private host directory outside this repository. Test artifacts must identify the Windows version, Python and dependency versions, observed events, and any untested platform conditions such as multi-monitor topology.

## Verified native Windows run

[Run 38620467658](https://github.com/snailphobia/league-ai-research/actions/runs/38620467658) tested code revision f4b9e9c on Windows Server 2025, build 26100, using Python 3.12.10 and PyDirectInput RGX 2.1.3.1. All 50 tests passed without skips: 27 portable contract tests and 23 native acceptance tests. The desktop was one monitor at 1024 by 768 pixels.

The same revision also passed all 50 tests in a local Windows 11 Enterprise LTSC evaluation VM, build 26100, with a 1280 by 800 desktop, Python 3.12.10, and the same pinned backend. See the [Windows 11 summary](../artifacts/windows-11/summary.json), [native observations](../artifacts/windows-11/native-input.json), and [JUnit result](../artifacts/windows-11/junit.xml). The VM uses UEFI Secure Boot and a software TPM; unattended installation overrides compatibility checks for the evaluation VM. These results establish client Windows input delivery without claiming game, graphics-performance, or anti-cheat acceptance.

Independent native observations cover 137 distinct named keys, 92 left/right modifier combinations, a 14-key chord, raw scan/virtual-key examples, all five mouse buttons, both wheel axes and signs, exact pixel movement, native relative motion, dragging, exception cleanup, and clicks at all four desktop corners. Large wheel requests retain their sign and total, and native coordinate overflow is rejected before injection. Unicode, including Romanian characters, CJK, and a non-BMP emoji, reached a real Windows EDIT control. The control also observed Ctrl and Shift held while receiving A, plus all five mouse button messages. Mixed raw/named modifier holds preserve one ownership record and release in order.

The keyboard catalog and large modifier matrix are logged by low-level Windows hooks, which suppress forwarding of injected keyboard events during those cases to avoid triggering shell shortcuts. This proves Windows receipt and ordering, not application behavior for every shortcut. Unicode application-effect tests enable forwarding. Ordinary SendInput acceptance by a particular game remains a separate test.

See the [machine-readable summary](../artifacts/windows-server-2025/summary.json) and [generated native event evidence](../artifacts/windows-server-2025/native-input.json). These artifacts contain the synthetic test input, not personal keyboard recordings.

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

Native multi-monitor and mixed-DPI topologies have not yet been observed; negative virtual desktop coordinates are currently covered by portable contract tests and the native backend uses Windows' virtual-desktop mapping. Do not present those portable cases as multi-monitor Windows acceptance. The native receiver now enumerates each monitor independently, and movement acceptance targets every monitor's corners and center. Staggered layouts also exercise rejection of bounding-box corners that fall in monitor gaps.
