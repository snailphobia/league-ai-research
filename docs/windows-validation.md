# Windows validation

Acceptance requires running the adapter on Windows and independently observing delivered keyboard and mouse events. Linux mocks alone are insufficient.

The validation matrix covers named keys, modifier ordering and release, extended scan codes, representative virtual keys, Unicode including non-BMP characters, all mouse buttons, absolute coordinates, relative movement, both wheel axes, dragging, and cleanup after exceptions. It must exercise monitor corners and record the actual virtual desktop geometry.

A Windows evaluation VM can be provisioned from Microsoft's official installation media using QEMU/KVM. VM disks and installation media live in a private host directory outside this repository. Test artifacts must identify the Windows version, Python and dependency versions, observed events, and any untested platform conditions such as multi-monitor topology.

Current status: validation implementation and VM provisioning are in progress; no Windows acceptance pass has been claimed.
