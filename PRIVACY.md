# TurboCAT privacy statement

Last updated 15 November 2026.

TurboCAT collects nothing about you. There are no accounts, no analytics, no tracking and no usage statistics. Your disk images, your file lists and your catalogue never leave your computer.

## What TurboCAT sends over the internet

Only when you use these features:

| Feature | Contacts | What it sends |
|---|---|---|
| Find pictures online | GitHub (the libretro-thumbnails collection) and the Internet Archive | The titles of games and the names of magazines it looks up. Once you switch it on, new disks are looked up after each scan; Tools › Find pictures online is where it starts. |
| Find out about games online | Wikidata and Wikipedia | Nothing about your disks to Wikidata: it downloads its whole list of Amiga games and programs and matches the names on your computer. Wikipedia is asked for the article of each title found, by its title. Once you switch it on, new disks are looked up after each scan. Links to Hall of Light, Lemon Amiga and MobyGames only open in your web browser if you click them. |
| Identify disks online | tosecdev.org and GitHub (the libretro database) | Nothing about your disks: it downloads the whole list of known Amiga disks and matches the checksums on your computer. |
| Look on Aminet for missing files | aminet.net | The names of the damaged files it looks for. It downloads only files with exactly the same name and size. |
| Report a problem, Suggest an idea | GitHub, through your own web browser | Only what the form shows you under “What will be sent”, and only if you submit it there. Your home folder is shown as ~ and your user name is taken out first. |
| Support TurboCAT (Ko-fi) | ko-fi.com, through your own web browser | Nothing: it only opens TurboCAT's Ko-fi page. Anything you give is between you and Ko-fi (and PayPal or Stripe); TurboCAT never sees it. |

## What it never does

- Nothing is sent in the background unless you started it (or switched it on, as with pictures and game information).
- No disk images, file lists, catalogue or checksums are sent anywhere.
- Error reports are never sent by themselves: TurboCAT shows you the report and you decide.

## What it keeps, all on your computer

- **Your catalogue**: where you chose (normally ~/turbocat.db on Linux; AppData\Roaming\TurboCAT on Windows; Library/Application Support/TurboCAT on macOS), with safety copies in a folder beside it
- **Pictures, disk lists, game information and Aminet files it downloaded**: ~/.cache/turbocat on Linux; AppData\Local\TurboCAT on Windows; Library/Caches/TurboCAT on macOS
- **Logs of repaired copies and renamed files**: ~/.local/share/turbocat on Linux; beside the catalogue on Windows and macOS
- **Repaired and tidied copies of disks**: TurboCAT/Repaired in your home folder

All of it stays on your computer. Delete any of these folders and TurboCAT starts afresh.

## Reports on GitHub

Reports filed on GitHub are public on TurboCAT's GitHub page, and GitHub keeps them under its own privacy policy, not TurboCAT's. Reports sent by email go to tcpturbocat@gmail.com, read only by the people working on TurboCAT, and are never passed on.
