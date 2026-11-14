# TurboCAT 4 – auf Deutsch

*[English README](README.md)*

**TurboCAT 4 katalogisiert deine Amiga-Disketten-Images auf Windows, macOS und Linux – und mit
TurboView durchsuchst du die ganze Sammlung direkt auf dem Amiga, ob echt oder emuliert.**

TurboCAT ist die Neuauflage von TurboCAT und TurboCAT-Pro, einem Disketten-Katalogisierer für den
Amiga aus den Jahren 1994–1996. Version 4 setzt die alte Zählung fort.

> **Beta-Version.** TurboCAT selbst ist bisher auf Englisch. Eine deutsche Oberfläche ist geplant –
> wer beim Übersetzen oder Korrekturlesen helfen möchte, ist herzlich willkommen (Kontakt unten).

## Was TurboCAT kann

- **Alles einlesen:** ADF (DD und HD), DMS, ADZ, HDF-Festplatten-Images, LHA (auch WHDLoad-Pakete),
  LZX, ZIP (auch TOSEC-Pakete) und Ordner, die als Emulator-Festplatte dienen. Archive in Archiven
  werden mit geöffnet.
- **Suchen:** jede Datei, jeder Diskettenname, jedes WHDLoad-Spiel, sofort.
- **Prüfen:** beschädigte Disketten, verdächtige Bootblöcke (Verhalten von Bootblock-Viren) und
  Duplikate. Duplikate werden nur ausgeblendet, nie gelöscht.
- **Erkennen:** Spiele, Demos, Programme und Coverdisks anhand ihrer Prüfsummen (TOSEC-Listen),
  mehrteilige Diskettensätze auf einer Zeile, fehlende Disketten eines Satzes.
- **Bilder und Musik:** Titelbilder, Screenshots und Magazin-Cover; Musikmodule (MOD, MED und
  andere) direkt abspielen.
- **Spielen:** ein Klick startet die Diskette im Emulator (WinUAE, FS-UAE oder Amiberry). Die
  Kickstart-ROMs brauchst du selbst, z. B. von Amiga Forever oder deinem eigenen Amiga; *Check setup*
  erklärt, wo sie hingehören.
- **Gotek:** Disketten auf einen Gotek-USB-Stick kopieren.
- **Reparieren:** reparierte Kopien beschädigter Disketten anlegen und fehlende Dateien auf Aminet
  suchen. Deine Original-Images werden nie verändert.

## TurboView – die Sammlung auf dem Amiga

Wer einen Gotek benutzt, kennt das Problem: Hunderte Images auf dem Stick, und das Display zeigt nur
eine dreistellige Nummer. TurboView bringt den Katalog auf den Amiga selbst: Namen eintippen, und
TurboView sagt dir, welche Diskette bzw. welches Gotek-Image das Spiel, das Programm oder die Datei
enthält – ganz ohne PC.

- **Läuft auf jedem Amiga ab Kickstart 1.3** – als Fenster auf der Workbench ab 2.04, in der Shell
  unter 1.3.
- **Keine Festplatte nötig:** *Tools › TurboView on a real Amiga…* erstellt zwei selbststartende
  TurboView-Disketten (für den Gotek oder echte Disketten). Disk 1: alle Disketten und ihr Inhalt;
  Disk 2: ein schneller Index aller Dateinamen.
- **Oder auf Festplatte:** `TurboView:TurboView INSTALL DH0:TurboCAT`. Wie das Original ist TurboView
  ein Workbench-Tool: per Doppelklick starten, neben der Arbeit offen lassen, auf die Titelleiste
  verkleinern oder in WBStartup legen.
- **Bleibt aktuell:** Nach dem nächsten Scan einfach die Disketten neu erstellen – ein installiertes
  TurboView bemerkt die neue Disk 1 im Laufwerk und bietet an, sich selbst zu aktualisieren.
- **Im Emulator** startet der TurboView-Knopf es mit deinen Ordnern als Laufwerke, und es kann die
  gefundene Diskette gleich einlegen.

TurboView auf echter Hardware ist neu und noch nicht ausgiebig getestet. Berichte über *Help › How
TurboView went on your Amiga…* oder per E-Mail helfen sehr –
[Checkliste für Tester (englisch)](docs/testing-turboview-on-a-real-amiga.md).

## Herunterladen

Die fertigen Pakete stehen unter [Releases](https://github.com/davidhill99/TurboCAT4/releases). Alles
Nötige ist enthalten (Python, Qt, 7-Zip für LHA, xdms für DMS, libopenmpt für Musik) – nur Emulator
und Kickstart-ROMs installierst du selbst.

- **Windows:** `TurboCAT-…-Windows-Setup.exe` (installiert nur für dich, ohne Admin-Rechte) oder die
  portable ZIP-Datei. Weil das Paket noch nicht signiert ist, meldet Windows „Der Computer wurde
  durch Windows geschützt“: *Weitere Informationen › Trotzdem ausführen*.
- **macOS:** `TurboCAT-…-macOS-AppleSilicon.dmg` (M1 und neuer) oder `TurboCAT-…-macOS-Intel.dmg`
  (ältere Macs). Ebenfalls unsigniert, daher beim ersten Mal: Rechtsklick auf das Programm › *Öffnen*.
- **Linux:** `TurboCAT-…-x86_64.AppImage` – ausführbar machen und starten.

## Ein Stück Amiga-Geschichte

TurboCAT wurde zwischen 1994 und 1996 mit CanDo geschrieben und im britischen Magazin *Amiga Shopper*
gleich dreimal vorgestellt (Links zu den Scans im Internet Archive):

- **August 1995, Ausgabe 52:** TurboCat 3 als exklusive Version auf der Coverdisk – schon damals
  mit TurboView als „Begleitprogramm“ zum Durchsuchen der Sammlung.
  [Seite 6](https://archive.org/details/Amiga_Shopper_Issue_52_1995-08_Future_Publishing_GB/page/n5/mode/2up)
- **Februar 1996, Ausgabe 59:** TurboCAT-Pro 1.2, Wertung **85 %**.
  [Seiten 76–77](https://archive.org/details/Amiga_Shopper_Issue_59_1996-02_Future_Publishing_GB/page/n75/mode/2up)
- **Mai 1996, Ausgabe 62:** TurboCAT-Pro 2, Wertung **90 %** und *Star Buy* – „my favourite
  cataloguer“. [Seiten 70–71](https://archive.org/details/Amiga_Shopper_Issue_62_1996-05_Future_Publishing_GB/page/n69/mode/2up)

## Lizenz, Kontakt und Unterstützung

TurboCAT 4 ist freie Software unter der **GNU General Public License, Version 3 oder neuer**
([LICENSE](LICENSE)).

- **Kontakt:** tcpturbocat@gmail.com – gerne auch auf Deutsch. In TurboCAT: *Help › Report a
  problem…* bzw. *Suggest an idea…*
- **Datenschutz:** TurboCAT sammelt nichts über dich – keine Konten, keine Statistiken, kein Tracking.
  Deine Disketten und dein Katalog verlassen nie deinen Computer ([PRIVACY.md](PRIVACY.md), englisch).
- **Unterstützen:** TurboCAT ist und bleibt kostenlos. Wenn es dir geholfen hat, kannst du dem Autor
  einen Kaffee spendieren: [ko-fi.com/tcpturbocat](https://ko-fi.com/tcpturbocat)
