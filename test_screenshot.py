#!/usr/bin/env -S uvx --with pyqt5,watchdog,pyyaml python
import sys
import yaml
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from PyQt5.QtCore import Qt, QPoint
from src.cmdbuttons import MainWindow

app = QApplication(sys.argv)

# Use default config location
config_file = Path.home() / ".config" / "buttons" / "commands.yaml"

# Ensure the config file exists (empty)
config_file.parent.mkdir(parents=True, exist_ok=True)
with open(config_file, 'w') as f:
    yaml.dump([], f, default_flow_style=False)

window = MainWindow(config_file)
window.show()

QTest.qWait(500)  # Wait for window to render

# Add first command: ls -R /etc
QTest.mouseClick(window.name_input, Qt.LeftButton)
QTest.qWait(100)
QTest.keyClicks(window.name_input, "ls -R /etc")
QTest.qWait(100)

QTest.mouseClick(window.command_input, Qt.LeftButton)
QTest.qWait(100)
QTest.keyClicks(window.command_input, "ls -R /etc | head -100")
QTest.qWait(100)

QTest.mouseClick(window.add_button, Qt.LeftButton)
QTest.qWait(500)  # Wait for file watcher to update

# Add second command: echo test
window.name_input.clear()
window.command_input.clear()
QTest.qWait(100)

QTest.mouseClick(window.name_input, Qt.LeftButton)
QTest.qWait(100)
QTest.keyClicks(window.name_input, "echo test")
QTest.qWait(100)

QTest.mouseClick(window.command_input, Qt.LeftButton)
QTest.qWait(100)
QTest.keyClicks(window.command_input, "echo 'Hello from command 2!'")
QTest.qWait(100)

QTest.mouseClick(window.add_button, Qt.LeftButton)
QTest.qWait(500)  # Wait for file watcher to update

# Create test_outputs directory
output_dir = Path("test_outputs")
output_dir.mkdir(exist_ok=True)

# Take first snapshot after adding both commands
pixmap = window.grab()
screenshot_path = output_dir / "screenshot_after_add.png"
pixmap.save(str(screenshot_path))
print(f"Screenshot 1 saved to {screenshot_path}")

# Reorder the commands by dragging the second item's handle to the top
if window.command_list.count() >= 2:
    # Use the handle of the second item as the drag source
    source_item = window.command_list.item(1)
    source_container = window.command_list.itemWidget(source_item)

    handle = getattr(source_container, "drag_handle", None)
    target_rect = window.command_list.visualItemRect(window.command_list.item(0))
    target_pos = target_rect.center() + QPoint(0, -target_rect.height() // 2)

    if handle:
        # Press on the handle, move to the target position on the viewport, then release
        QTest.mousePress(handle, Qt.LeftButton, pos=handle.rect().center())
        QTest.qWait(100)
        QTest.mouseMove(window.command_list.viewport(), target_pos)
        QTest.qWait(100)
        QTest.mouseRelease(window.command_list.viewport(), Qt.LeftButton, pos=target_pos)
        QTest.qWait(750)  # Wait for reorder to complete

        # Verify the YAML order updated with the new top item
        with open(config_file) as f:
            command_list = yaml.safe_load(f) or []
        assert command_list and command_list[0]["name"] == "echo test"

# Take snapshot after reordering
pixmap = window.grab()
screenshot_path = output_dir / "screenshot_after_reorder.png"
pixmap.save(str(screenshot_path))
print(f"Screenshot 2 saved to {screenshot_path}")

# Click on the first command in the list to run it (which is now "echo test")
if window.command_list.count() > 0:
    item = window.command_list.item(0)
    container = window.command_list.itemWidget(item)
    if container and getattr(container, "button", None):
        # Trigger button click directly
        window.on_command_button_clicked(container.button.text())
        # Process events to let the thread start and output appear
        QTest.qWait(500)
        app.processEvents()
        QTest.qWait(1500)  # Wait longer for command output

# Take final snapshot after execution
pixmap = window.grab()
screenshot_path = output_dir / "screenshot_after_run.png"
pixmap.save(str(screenshot_path))
print(f"Screenshot 3 saved to {screenshot_path}")

app.quit()
