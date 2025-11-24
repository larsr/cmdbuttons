#!/usr/bin/env -S uvx --with pyqt5,watchdog,pyyaml python
# nix-shell -p 'python310.withPackages (p:[p.pyqt5 p.watchdog])' qt5Full

import fcntl
import os
import select
import sys
import argparse
import subprocess
import yaml
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QTextEdit, QLineEdit, QLabel, QSplitter, QListWidget, QAbstractItemView, QListWidgetItem, QStyle
from PyQt5.QtCore import pyqtSlot, QThread, pyqtSignal, Qt, QObject
from PyQt5.QtGui import QTextCursor, QDrag
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PyQt5.QtGui import QFont

def read_commands_from_yaml(filepath):
    if not filepath.exists():
        return {}
    try:
        with open(filepath, 'r') as yamlfile:
            data = yaml.safe_load(yamlfile)
        if data is None or not isinstance(data, list):
            return {}
        data = {x["name"]: x["command"] for x in data if isinstance(x, dict) and "name" in x and "command" in x}
        return data
    except Exception as e:
        print(f"Error reading YAML file: {e}")
        return {}

def save_command_to_yaml(filepath, name, command):
    with open(filepath, 'r') as yamlfile:
        data = yaml.safe_load(yamlfile)
    
    # Check if name already exists
    existing_entry = None
    for entry in data:
        if entry["name"] == name:
            existing_entry = entry
            break
    
    if existing_entry:
        # Update existing command
        existing_entry["command"] = command
    else:
        # Add new command
        data.append({"name": name, "command": command})
    
    with open(filepath, 'w') as yamlfile:
        yaml.dump(data, yamlfile, default_flow_style=False)

def remove_command_from_yaml(filepath, name):
    with open(filepath, 'r') as yamlfile:
        data = yaml.safe_load(yamlfile)
    
    # Remove entry with matching name
    data = [entry for entry in data if entry["name"] != name]
    
    with open(filepath, 'w') as yamlfile:
        yaml.dump(data, yamlfile, default_flow_style=False)

# Thread class for running the command
class CommandThread(QThread):
    output_signal = pyqtSignal(str)

    def __init__(self, command, directory):
        QThread.__init__(self)
        self.command = command
        self.directory = directory
        self.running = False

    def run(self):
        command = f'cd {self.directory} && {self.command}'
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=0)
        self.process = process
        self.running = True

        def make_nonblocking(file_handle):
            flags_stdout = fcntl.fcntl(file_handle, fcntl.F_GETFL)
            fcntl.fcntl(file_handle, fcntl.F_SETFL, flags_stdout | os.O_NONBLOCK)

        make_nonblocking(process.stdout)
        make_nonblocking(process.stderr)

        def read_and_emit():
            ready_to_read, _, _ = select.select([process.stdout, process.stderr], [], [], 0.1)
            for output in ready_to_read:
                line = output.read()
                if self.running:
                    self.output_signal.emit(line)

        while self.running:
            self.running = self.running and process.poll() is None
            read_and_emit()

    def stop(self):
        if self.running:
            self.process.terminate()
            self.process.kill()
            self.process.wait()
            self.running = False
        self.wait()

class FileModifiedSignalEmitter(QObject):
    file_modified_signal = pyqtSignal(str)


class DragHandleLabel(QLabel):
    def __init__(self, list_widget, parent=None):
        super().__init__(parent)
        self.list_widget = list_widget
        self.drag_start_position = None
        self.list_item = None
        self.setCursor(Qt.OpenHandCursor)
        self.setAlignment(Qt.AlignCenter)

    def set_list_item(self, item):
        self.list_item = item

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if self.drag_start_position is None:
            return
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return
        if self.list_item:
            self.list_widget.initiate_drag_for_item(self.list_item)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)


class CommandListItemWidget(QWidget):
    def __init__(self, command_name, list_widget, click_handler, parent=None):
        super().__init__(parent)
        self.command_name = command_name
        self.list_widget = list_widget

        layout = QHBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(4)

        self.drag_handle = DragHandleLabel(self.list_widget, self)
        handle_icon = self.style().standardIcon(QStyle.SP_TitleBarShadeButton)
        self.drag_handle.setPixmap(handle_icon.pixmap(12, 12))
        layout.addWidget(self.drag_handle)

        self.button = QPushButton(command_name, self)
        self.button.clicked.connect(lambda checked=False: click_handler(command_name))
        layout.addWidget(self.button, 1)

    def set_list_item(self, item):
        self.drag_handle.set_list_item(item)

# Custom QListWidget with reorder detection
class ReorderableListWidget(QListWidget):
    items_reordered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def initiate_drag_for_item(self, item):
        if not item:
            return
        self.setCurrentItem(item)
        drag = QDrag(self)
        mime_data = self.model().mimeData(self.selectedIndexes())
        drag.setMimeData(mime_data)
        drag.exec_(Qt.MoveAction)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.items_reordered.emit()

# File watcher class
class CommandFileEventHandler(FileSystemEventHandler):
    def __init__(self, signal_emitter, command_file):
        super().__init__()
        self.signal_emitter = signal_emitter
        self.command_file = Path(command_file).resolve()

    def on_modified(self, event):
        if Path(event.src_path).resolve() == self.command_file:
            self.signal_emitter.file_modified_signal.emit(event.src_path)


# Main window class
class MainWindow(QWidget):
    def __init__(self, command_file):
        super().__init__()
        self.command_file = command_file
        self.commands = read_commands_from_yaml(self.command_file)
        self.command_thread = None

        self.init_ui()

        self.signal_emitter = FileModifiedSignalEmitter()
        self.observer = Observer()
        self.event_handler = CommandFileEventHandler(self.signal_emitter, self.command_file)
        self.signal_emitter.file_modified_signal.connect(self.update_commands_from_signal)
        self.observer.schedule(self.event_handler, path=str(self.command_file.parent), recursive=False)
        self.observer.start()

    def init_ui(self):
        self.setWindowTitle('Bash Command Executor')
        self.main_layout = QVBoxLayout(self)
        self.splitter = QSplitter(Qt.Horizontal)

        # Left column widget
        self.left_widget = QWidget()
        self.left_column = QVBoxLayout()

        # Top row with name input
        self.name_input = QLineEdit(self)
        self.name_input.setPlaceholderText("Name")
        self.left_column.addWidget(self.name_input)

        # Command list with actual button widgets
        self.command_list = ReorderableListWidget(self)
        self.command_list.setSpacing(4)  # Add spacing between items
        for command_name in self.commands:
            self._add_button_to_list(command_name)
        self.command_list.items_reordered.connect(self.on_items_reordered)

        self.left_column.addWidget(self.command_list)
        self.left_widget.setLayout(self.left_column)

        # Right column widget
        self.right_widget = QWidget()
        self.command_input = QLineEdit(self)
        self.command_input.setPlaceholderText("Command")
        self.command_input.returnPressed.connect(self.on_return_pressed)

        self.add_button = QPushButton("+", self)
        self.add_button.setFixedSize(30, 30)
        self.add_button.clicked.connect(self.on_add_button_clicked)

        self.remove_button = QPushButton("-", self)
        self.remove_button.setFixedSize(30, 30)
        self.remove_button.clicked.connect(self.on_remove_button_clicked)

        self.font_button = QPushButton("Aa", self)
        self.font_button.setFixedSize(30, 30)
        self.font_button.clicked.connect(self.on_font_button_clicked)

        self.output_text = QTextEdit(self)
        self.output_text.setReadOnly(True)
        self.fixed_width_font = True
        fixed_width_font = QFont("Monospace")
        fixed_width_font.setStyleHint(QFont.TypeWriter)
        self.output_text.setFont(fixed_width_font)

        self.input_layout = QHBoxLayout()
        self.input_layout.addWidget(self.command_input)
        self.input_layout.addWidget(self.add_button)
        self.input_layout.addWidget(self.remove_button)
        self.input_layout.addWidget(self.font_button)

        self.right_layout = QVBoxLayout()
        self.right_layout.addLayout(self.input_layout)
        self.right_layout.addWidget(self.output_text)
        self.right_widget.setLayout(self.right_layout)

        # Add widgets to splitter
        self.splitter.addWidget(self.left_widget)
        self.splitter.addWidget(self.right_widget)
        self.splitter.setStretchFactor(0, 0)  # Left doesn't stretch
        self.splitter.setStretchFactor(1, 1)  # Right stretches

        self.main_layout.addWidget(self.splitter)

        self.setLayout(self.main_layout)

    def _add_button_to_list(self, command_name):
        """Add a command button to the list widget"""
        item = QListWidgetItem(self.command_list)
        item.setFlags(item.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsEnabled | Qt.ItemIsSelectable)

        container = CommandListItemWidget(command_name, self.command_list, self.on_command_button_clicked, self)
        container.set_list_item(item)

        item.setSizeHint(container.sizeHint())
        self.command_list.addItem(item)
        self.command_list.setItemWidget(item, container)

    @pyqtSlot()
    def on_add_button_clicked(self):
        name = self.name_input.text().strip()
        command = self.command_input.text().strip()
        
        if not name:
            # Generate a unique name if empty
            base_name = "Command"
            counter = 1
            name = base_name
            while name in self.commands:
                name = f"{base_name}{counter}"
                counter += 1
        
        if command:
            save_command_to_yaml(self.command_file, name, command)
            # The file watcher will trigger update_commands automatically

    @pyqtSlot()
    def on_remove_button_clicked(self):
        name = self.name_input.text().strip()
        if name and name in self.commands:
            remove_command_from_yaml(self.command_file, name)
            # The file watcher will trigger update_commands automatically
            self.name_input.clear()
            self.command_input.clear()

    @pyqtSlot()
    def on_font_button_clicked(self):
        self.fixed_width_font = not self.fixed_width_font
        if self.fixed_width_font:
            font = QFont("Monospace")
            font.setStyleHint(QFont.TypeWriter)
        else:
            font = QFont()
        self.output_text.setFont(font)

    def update_commands_from_signal(self, filepath):
        # This method will be called in the main thread
        self.update_commands()

    @pyqtSlot()
    def update_commands(self):
        print("Updating commands")
        # Read the new commands from the YAML file
        new_commands = read_commands_from_yaml(self.command_file)

        # Find out which commands are new or have been removed
        new_command_names = set(new_commands.keys())
        old_command_names = set(self.commands.keys())
        added_commands = new_command_names - old_command_names
        removed_commands = old_command_names - new_command_names

        # Remove items for commands that have been removed
        for command_name in removed_commands:
            for i in range(self.command_list.count()):
                item = self.command_list.item(i)
                container = self.command_list.itemWidget(item)
                if container and getattr(container, "command_name", None) == command_name:
                    self.command_list.takeItem(i)
                    break

        # Add new items for added commands
        for command_name in added_commands:
            self._add_button_to_list(command_name)

        # Update the commands dictionary
        self.commands = new_commands

    def on_command_button_clicked(self, command_name):
        """Handle command button click"""
        command = self.commands[command_name]

        self.name_input.setText(command_name)
        self.command_input.setText(command)

        modifiers = QApplication.keyboardModifiers()
        if modifiers == Qt.ShiftModifier:
            # If Shift is pressed, just insert the text and do not execute the command
            return

        if self.command_thread and self.command_thread.isRunning():
            self.command_thread.stop()

        self.output_text.clear()

        self.command_thread = CommandThread(command, '.')
        self.command_thread.output_signal.connect(self.append_output)
        self.command_thread.start()

    @pyqtSlot()
    def on_items_reordered(self):
        # Get the new order from the list widget buttons
        ordered_commands = []
        for i in range(self.command_list.count()):
            item = self.command_list.item(i)
            container = self.command_list.itemWidget(item)
            if container:
                command_name = getattr(container, "command_name", None)
                if command_name:
                    ordered_commands.append({"name": command_name, "command": self.commands[command_name]})

        # Save to YAML
        with open(self.command_file, 'w') as yamlfile:
            yaml.dump(ordered_commands, yamlfile, default_flow_style=False)

    @pyqtSlot()
    def on_return_pressed(self):
        command = self.command_input.text()
        self.output_text.clear()

        if self.command_thread and self.command_thread.isRunning():
            self.command_thread.stop()

        self.command_thread = CommandThread(command, '.')
        self.command_thread.output_signal.connect(self.append_output)
        self.command_thread.start()

    @pyqtSlot(str)
    def append_output(self, text):
        self.output_text.moveCursor(QTextCursor.End)
        self.output_text.insertPlainText(text)

    def closeEvent(self, event):
        if self.command_thread and self.command_thread.isRunning():
            self.command_thread.stop()
        self.observer.stop()
        self.observer.join()
        super().closeEvent(event)


def parse_args():
    parser = argparse.ArgumentParser(description='Button command runner')
    parser.add_argument(
        'command_file', 
        nargs='?',
        default=(Path.home() / ".config" / "buttons" / "commands.yaml"),
        type=lambda x: Path(x).absolute(),
        help='Path to commands yaml file (default: ~/.config/buttons/commands.yaml)'
    ) 
    return parser.parse_args()

def main():
    args = parse_args()
    print(f'Reading commands from {args.command_file}')
    if not args.command_file.exists():
        print(f'Command file {args.command_file} does not exist. Creating it with an empty list.')
        args.command_file.parent.mkdir(parents=True, exist_ok=True)
        with open(args.command_file, 'w') as f:
            import yaml
            yaml.dump([], f, default_flow_style=False)

    app = QApplication(sys.argv)
    mainWin = MainWindow(command_file = args.command_file)
    mainWin.show()

    try:
        ret = app.exec_()
    except Exception as e:
        ret = -1
        print(e)
        with open('/tmp/crashlog','w+') as f:
            f.write(str(e)+'\n\n')

    sys.exit(ret)

if __name__ == "__main__":
    main()
