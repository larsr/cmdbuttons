#!/usr/bin/env -S uvx --with pyqt5,watchdog,pyyaml python
import sys
import yaml
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from PyQt5.QtCore import Qt
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

# Reorder the commands by moving the second item to the first position
if window.command_list.count() >= 2:
    # Get the container widget from the second item before moving
    item = window.command_list.item(1)
    container = window.command_list.itemWidget(item)

    # Take the item and its container
    item = window.command_list.takeItem(1)

    # Insert at position 0
    window.command_list.insertItem(0, item)

    # Restore the container to the moved item
    window.command_list.setItemWidget(item, container)

    # Manually trigger the reorder handler since we're not using drag-drop
    window.on_items_reordered()
    QTest.qWait(500)  # Wait for reorder to complete

# Take snapshot after reordering
pixmap = window.grab()
screenshot_path = output_dir / "screenshot_after_reorder.png"
pixmap.save(str(screenshot_path))
print(f"Screenshot 2 saved to {screenshot_path}")

# Click on the first command in the list to run it (which is now "echo test")
if window.command_list.count() > 0:
    item = window.command_list.item(0)
    container = window.command_list.itemWidget(item)
    if container:
        from src.cmdbuttons import DraggableButton
        button = container.findChild(DraggableButton)
        if button:
            # Trigger button click directly
            window.on_command_button_clicked(button.text())
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
