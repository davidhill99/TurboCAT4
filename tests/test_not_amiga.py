"""Files that aren't Amiga (Word documents, zipped PDFs or WhatsApp chats, Game Boy games) are left
out of the catalogue, while Amiga zips with no disk image inside (demo programs, IPF disks, ROMs)
stay."""
import os
import tempfile
import unittest
import zipfile

from turbocat import readers, scanner
from turbocat.catalogue import Catalogue
from test_repair import make_adf


class RuleTest(unittest.TestCase):
    def test_not_amiga(self):
        no = readers.not_amiga
        self.assertEqual(no(["[Content_Types].xml", "_rels/.rels", "word/document.xml"]), "an Office document")
        self.assertEqual(no(["mimetype", "content.xml"]), "a LibreOffice document or e-book")
        self.assertEqual(no(["META-INF/MANIFEST.MF", "a/B.class"]), "a Java or Android program")
        self.assertEqual(no(["Rodland (U).gb"]), "a game for another computer or console")
        self.assertEqual(no(["WhatsApp Chat with Mum.txt"]), "PC documents, pictures or media")
        self.assertEqual(no(["a.pdf", "b.pdf", "c/"]), "PC documents, pictures or media")
        self.assertEqual(no(["Work/.dropbox", "Work/a.pdf", "__MACOSX/._a.pdf"]),
                         "PC documents, pictures or media")

    def test_amiga_zips_stay(self):
        for names in (["Crack Intro (TRSI).exe"], ["Lemmings 2 Disk1.ipf"], ["Nordic Power v1.5.rom"],
                      ["Game.adf"], ["Game.lha"], ["mod.tune"], ["Tool", "Tool.info"],
                      ["ReadMe.txt", "Tool"], []):
            self.assertIsNone(readers.not_amiga(names), names)


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = os.path.join(self.tmp.name, "Dropbox")
        os.makedirs(self.d)
        self.zip("CV.docx", {"[Content_Types].xml": b"<x/>", "word/document.xml": b"<w/>"})
        self.zip("Chat.zip", {"WhatsApp Chat.txt": b"hello"})
        self.zip("Rodland (U).zip", {"Rodland (U).gb": b"\0" * 512})
        self.zip("Crack Intro (19xx)(TRSI).zip", {"Crack Intro.exe": b"\0\0\x03\xf3" + b"\0" * 60})
        with open(os.path.join(self.d, "Disk.adf"), "wb") as f:
            f.write(make_adf("Disk", {"ReadMe": b"Amiga" * 40}))
        self.cat = Catalogue(os.path.join(self.tmp.name, "cat.db"))

    def tearDown(self):
        self.cat.db.close()
        self.tmp.cleanup()

    def zip(self, name, files):
        with zipfile.ZipFile(os.path.join(self.d, name), "w") as z:
            for n, data in files.items():
                z.writestr(n, data)

    def names(self):
        return sorted(os.path.basename(s) for s in self.cat.top_sources())

    def test_scan_leaves_them_out(self):
        s = scanner.scan([self.d], self.cat, progress=None)
        self.assertEqual(self.names(), ["Crack Intro (19xx)(TRSI).zip", "Disk.adf"])
        self.assertEqual(sorted(os.path.basename(p) for p, _ in s["not_amiga"]),
                         ["CV.docx", "Chat.zip", "Rodland (U).zip"])

    def test_ones_catalogued_before_go_on_the_next_rescan(self):
        real = readers.zip_not_amiga
        readers.zip_not_amiga = lambda path: None          # as TurboCAT was before
        try:
            scanner.scan([self.d], self.cat, progress=None)
        finally:
            readers.zip_not_amiga = real
        self.assertEqual(len(self.names()), 5)
        s = scanner.rescan_all(self.cat, progress=None)
        self.assertEqual(self.names(), ["Crack Intro (19xx)(TRSI).zip", "Disk.adf"])
        self.assertEqual(len(s["not_amiga"]), 3)
        scanner.rescan_all(self.cat, progress=None)          # and they don't come back
        self.assertEqual(len(self.names()), 2)


if __name__ == "__main__":
    unittest.main()
