"""TurboCAT's privacy statement, in one place: Help › Privacy shows it, the feedback forms link to
it, and PRIVACY.md in the repository is written from it (a test checks they match).

Keep it true: when a feature starts contacting a new site, or sends something new, add it here.
"""
import html

UPDATED = "14 November 2026"

INTRO = ("TurboCAT collects nothing about you. There are no accounts, no analytics, no tracking and "
         "no usage statistics. Your disk images, your file lists and your catalogue never leave your "
         "computer.")

# (feature, the sites it contacts, what it sends)
ONLINE = [
    ("Find pictures online",
     "GitHub (the libretro-thumbnails collection) and the Internet Archive",
     "The titles of games and the names of magazines it looks up. Once you switch it on, new "
     "disks are looked up after each scan; Tools › Find pictures online is where it starts."),
    ("Identify disks online",
     "tosecdev.org and GitHub (the libretro database)",
     "Nothing about your disks: it downloads the whole list of known Amiga disks and matches the "
     "checksums on your computer."),
    ("Look on Aminet for missing files",
     "aminet.net",
     "The names of the damaged files it looks for. It downloads only files with exactly the same "
     "name and size."),
    ("Report a problem, Suggest an idea",
     "GitHub, through your own web browser",
     "Only what the form shows you under “What will be sent”, and only if you submit it "
     "there. Your home folder is shown as ~ and your user name is taken out first."),
    ("Support TurboCAT (Ko-fi)",
     "ko-fi.com, through your own web browser",
     "Nothing: it only opens TurboCAT's Ko-fi page. Anything you give is between you and Ko-fi "
     "(and PayPal or Stripe); TurboCAT never sees it."),
]

NEVER = [
    "Nothing is sent in the background unless you started it (or switched it on, as with pictures).",
    "No disk images, file lists, catalogue or checksums are sent anywhere.",
    "Error reports are never sent by themselves: TurboCAT shows you the report and you decide.",
]

KEPT = [
    ("Your catalogue", "where you chose (normally ~/turbocat.db on Linux; AppData\\Roaming\\TurboCAT on "
                       "Windows; Library/Application Support/TurboCAT on macOS), with safety copies in a "
                       "folder beside it"),
    ("Pictures, disk lists and Aminet files it downloaded", "~/.cache/turbocat on Linux; "
                                                            "AppData\\Local\\TurboCAT on Windows; "
                                                            "Library/Caches/TurboCAT on macOS"),
    ("Logs of repaired copies and renamed files", "~/.local/share/turbocat on Linux; beside the "
                                                  "catalogue on Windows and macOS"),
    ("Repaired and tidied copies of disks", "TurboCAT/Repaired in your home folder"),
]
KEPT_NOTE = "All of it stays on your computer. Delete any of these folders and TurboCAT starts afresh."

GITHUB = ("Reports filed on GitHub are public on TurboCAT's GitHub page, and GitHub keeps them under "
          "its own privacy policy, not TurboCAT's. Reports sent by email go to tcpturbocat@gmail.com, "
          "read only by the people working on TurboCAT, and are never passed on.")

SECTIONS = ["What TurboCAT sends over the internet", "What it never does",
            "What it keeps, all on your computer", "Reports on GitHub"]


def markdown():
    """The statement as Markdown: what PRIVACY.md holds."""
    out = ["# TurboCAT privacy statement", "", f"Last updated {UPDATED}.", "", INTRO, "",
           f"## {SECTIONS[0]}", "", "Only when you use these features:", "",
           "| Feature | Contacts | What it sends |", "|---|---|---|"]
    out += [f"| {f} | {c} | {w} |" for f, c, w in ONLINE]
    out += ["", f"## {SECTIONS[1]}", ""] + [f"- {x}" for x in NEVER]
    out += ["", f"## {SECTIONS[2]}", ""] + [f"- **{k}**: {v}" for k, v in KEPT]
    out += ["", KEPT_NOTE, "", f"## {SECTIONS[3]}", "", GITHUB, ""]
    return "\n".join(out)


def rich_text(accent="#1d4f91"):
    """The statement as Qt rich text, for the Privacy window."""
    e = html.escape
    h = lambda t: f"<h3 style='margin-top:14px'>{e(t)}</h3>"
    parts = [f"<p>{e(INTRO)}</p>", h(SECTIONS[0]), "<p>Only when you use these features:</p>"]
    for f, c, w in ONLINE:
        parts.append(f"<p><b>{e(f)}</b><br><span style='color:{accent}'>{e(c)}</span><br>{e(w)}</p>")
    parts.append(h(SECTIONS[1]))
    parts.append("<ul>" + "".join(f"<li>{e(x)}</li>" for x in NEVER) + "</ul>")
    parts.append(h(SECTIONS[2]))
    parts.append("<ul>" + "".join(f"<li><b>{e(k)}</b>: {e(v)}</li>" for k, v in KEPT) + "</ul>")
    parts.append(f"<p>{e(KEPT_NOTE)}</p>")
    parts.append(h(SECTIONS[3]))
    parts.append(f"<p>{e(GITHUB)}</p>")
    parts.append(f"<p style='color:gray'>Last updated {e(UPDATED)}.</p>")
    return "".join(parts)
