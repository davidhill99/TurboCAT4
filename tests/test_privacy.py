"""The privacy statement: PRIVACY.md is written from privacy.py (so the window and GitHub never
disagree), every site TurboCAT contacts is named in it, and the window and links show it."""
import os
import re
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from turbocat import privacy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PrivacyTest(unittest.TestCase):
    def test_privacy_md_matches_the_window(self):
        with open(os.path.join(ROOT, "PRIVACY.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), privacy.markdown(),
                             "PRIVACY.md is out of date: write it again from privacy.markdown()")

    def test_every_site_contacted_is_named(self):
        """A new site in the code must be added to the statement (or to the list of web pages that
        are only opened in the browser for the user to read)."""
        named = privacy.markdown().lower()
        where = {"aminet.net": "aminet", "tosecdev.org": "tosecdev", "archive.org": "internet archive",
                 "githubusercontent.com": "github", "api.github.com": "github", "ko-fi.com": "ko-fi.com",
                 "wikidata.org": "wikidata", "wikipedia.org": "wikipedia"}
        only_opened = {"github.com", "zakalwe.fi", "lib.openmpt.org", "xmp.sourceforge.net", "fs-uae.net",
                       "amiberry.com", "www.amigaforever.com", "amiga.abime.net",
                       "www.lemonamiga.com", "www.mobygames.com"}
        pkg = os.path.join(ROOT, "turbocat")
        for name in os.listdir(pkg):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(pkg, name), encoding="utf-8") as f:
                for host in re.findall(r"https?://([a-z0-9.-]+)", f.read()):
                    if host in only_opened:
                        continue
                    key = next((k for k in where if host.endswith(k)), None)
                    self.assertIsNotNone(key, f"{name} contacts {host}, which PRIVACY.md doesn't mention")
                    self.assertIn(where[key], named)


class PrivacyWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from turbocat import gui
        cls.app = QApplication.instance() or QApplication([])
        gui._pick_theme()

    def test_the_window_shows_the_statement(self):
        from turbocat import gui
        dlg = gui.PrivacyDialog()
        for heading in privacy.SECTIONS:
            self.assertIn(heading, dlg.text.text())

    def test_the_feedback_form_links_to_it(self):
        from unittest import mock
        from turbocat import gui
        form = gui.FeedbackDialog(None, "idea")
        with mock.patch.object(gui, "show_privacy") as shown:
            form.privacy_link.linkActivated.emit("privacy")
        shown.assert_called_once()


if __name__ == "__main__":
    unittest.main()
