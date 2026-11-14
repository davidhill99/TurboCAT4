"""Pictures TurboCAT draws for disks with none: a Workbench window of the disk's icons, or a
Shell listing; and what kind of utility a disk is, for its generic picture."""
import os
import struct
import unittest
import qt_cleanup  # noqa: F401  (deletes leftover windows before Qt shuts down)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from turbocat import amigaimg, madepics, utilities  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402  (a full one: other tests open windows)
APP = QGuiApplication.instance() or QApplication([])


def info(x, y):
    """A minimal .info header with an icon position."""
    data = bytearray(78)
    data[0:2] = b"\xe3\x10"
    data[58:66] = struct.pack(">ii", x, y)
    return bytes(data)


class MadeTest(unittest.TestCase):
    def test_icon_position(self):
        self.assertEqual(madepics.icon_position(info(20, 30)), (20, 30))
        self.assertIsNone(madepics.icon_position(info(madepics.NO_POSITION, 0)))

    def test_workbench_window(self):
        icon = amigaimg.Image(8, 4, bytes([255, 255, 255, 255]) * 32, 2, "Workbench 1.3")
        png = madepics.workbench_window("Utils", [("Copy", icon, (10, 10)), ("Tool", icon, None)])
        img = QImage.fromData(png)
        self.assertFalse(img.isNull())
        self.assertEqual(img.pixelColor(img.width() // 2, img.height() - 10).name(), "#0055aa")  # 1.3 blue

    def test_shell_window(self):
        png = madepics.shell_window("Tools", [("c", True), ("ReadMe", False), ("X-Copy", False)])
        self.assertFalse(QImage.fromData(png).isNull())

    def test_categories(self):
        for name, label in (("VirusX 4.01", "Virus killer"), ("ProTracker 2.3", "Music tools"),
                            ("X-Copy Pro", "Disk tools"), ("Deluxe Paint III", "Graphics"),
                            ("A.B.P.D Utility Disk U099", "Utility disk")):
            self.assertEqual(utilities.category(name)[1], label, name)


if __name__ == "__main__":
    unittest.main()
