**The first public test release of TurboCAT 4**: the 1994–96 Amiga disk cataloguer, back for
Windows, macOS and Linux, with TurboView to search your collection on a real or emulated Amiga.

*Deutsch: [LIESMICH.md](https://github.com/davidhill99/TurboCAT4/blob/main/LIESMICH.md)*

## Which file?

| You have | Download |
|---|---|
| Windows 10 or 11 | `TurboCAT-…-Windows-Setup.exe` (installs for you only, no admin rights), or the `…-Windows-portable.zip` |
| A Mac with Apple Silicon (M1 or later) | `TurboCAT-…-macOS-AppleSilicon.dmg` |
| An older Intel Mac | `TurboCAT-…-macOS-Intel.dmg` |
| Linux (64-bit) | `TurboCAT-…-x86_64.AppImage`: make it executable and run it |

The packages aren't signed yet, so the first time:
- **Windows** says "Windows protected your PC": click **More info › Run anyway**.
- **macOS** says it can't check the app: **right-click the app › Open**.

Everything TurboCAT needs is inside (7-Zip for LHA, xdms for DMS, libopenmpt for music). To play
disks you also need an emulator (WinUAE, FS-UAE or Amiberry) and Kickstart ROMs:
**Help › Check setup** explains both.

`SHA256SUMS.txt` lists each file's checksum.

## Testers wanted

This is a beta: please tell me what works and what doesn't.
- **On a real Amiga**: Tools › TurboView on a real Amiga… makes two TurboView floppies (for a Gotek
  or real disks). The [tester's checklist](https://github.com/davidhill99/TurboCAT4/blob/main/docs/testing-turboview-on-a-real-amiga.md)
  says what to try; report with Help › How TurboView went on your Amiga…
- **On Windows and macOS**: I develop on Linux, so every report from these helps.
- **Translators**: a German version (and others) is planned.

Report with **Help › Report a problem…** in TurboCAT, on
[GitHub Issues](https://github.com/davidhill99/TurboCAT4/issues), or by email to tcpturbocat@gmail.com.

What's in this release: [CHANGELOG.md](https://github.com/davidhill99/TurboCAT4/blob/main/CHANGELOG.md).
TurboCAT is free software (GPL-3.0-or-later). If it's helped you:
[ko-fi.com/tcpturbocat](https://ko-fi.com/tcpturbocat)
