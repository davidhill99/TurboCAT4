# Getting TurboCAT into the stores (prepared, not yet submitted)

Each store points at the files of a published GitHub release. The SHA256 lines are filled in for
**4.0.0-beta.2** from the draft release's SHA256SUMS.txt, so once that release is published these are
ready to submit. For a later release, take the numbers from its SHA256SUMS.txt. Nothing here has been
submitted yet.

| Store | What to submit | Where |
|---|---|---|
| **winget** (Windows) | the three files in `winget/` | a pull request to github.com/microsoft/winget-pkgs (path `manifests/d/DavidHill/TurboCAT/4.0.0-beta.2/`); `wingetcreate` can do it |
| **Homebrew** (macOS) | `homebrew/Casks/turbocat.rb` | a tap of your own: a public repo **davidhill99/homebrew-turbocat** with this file in `Casks/`. People then run `brew install --cask davidhill99/turbocat/turbocat`. (Homebrew's main list won't take unsigned apps.) |
| **Flathub** (Linux) | the files in `flathub/` | a pull request to github.com/flathub/flathub (new-app branch), following docs.flathub.org/docs/for-app-authors/submission. Flathub builds from source; the manifest needs trying with `flatpak-builder` first. |
| **Aminet** (Amiga) | TurboView + `aminet/TurboView.readme` | upload `TurboView.lha` and the readme at aminet.net/upload (or by FTP) |

Contact address used throughout: tcpturbocat@gmail.com.
