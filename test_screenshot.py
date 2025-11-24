#!/usr/bin/env python
import sys
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from src.cmdbuttons import MainWindow

app = QApplication(sys.argv)

# Use default config location
config_file = Path.home() / ".config" / "buttons" / "commands.yaml"
window = MainWindow(config_file)
window.show()

QTest.qWait(500)  # Wait for window to render

pixmap = window.grab()
pixmap.save("screenshot.png")
print("Screenshot saved to screenshot.png")

app.quit()
