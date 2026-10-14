# Windows input adapter contract

The adapter must support named physical keys, arbitrary multi-key chords, separate left and right modifiers, raw scan codes, arbitrary Windows virtual-key codes, Unicode text, absolute and relative pointer movement, left/right/middle/X1/X2 buttons, repeated clicks, dragging, and vertical/horizontal wheel input. Desktop coordinates cover all attached monitors, including negative coordinates and monitor corners.

Every held key and button has an explicit owner. Context-manager cleanup and release-all release only adapter-owned inputs. Validation occurs before starting a chord or input sequence. Rejected or partially submitted native input must raise an error; API submission alone does not prove an application consumed it.

Windows secure attention sequences, secure desktops, firmware-only keys, higher-privilege applications, and applications which reject synthesized input require separate mechanisms. The adapter must report these boundaries without advertising ordinary SendInput as universal access. Ctrl+Alt+Delete requires Windows' separate SendSAS facilities and configured privileges; it cannot be claimed as a normal keyboard chord.

Candidate libraries: [PyDirectInput RGX](https://github.com/ReggX/pydirectinput_rgx), [pynput](https://github.com/moses-palmer/pynput), and [PyAutoGUI](https://github.com/asweigart/pyautogui). Backend selection will be documented against the requirements and measured Windows results.

Authoritative Windows interfaces: [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput), [virtual-key codes](https://learn.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes), and [SendSAS](https://learn.microsoft.com/en-us/windows/win32/api/sas/nf-sas-sendsas).
