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
from PyQt5.QtWidgets import QApplication, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QTextEdit, QLineEdit, QLabel
from PyQt5.QtCore import pyqtSlot, QThread, pyqtSignal, Qt, QObject
from PyQt5.QtGui import QTextCursor
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PyQt5.QtGui import QFont

def read_commands_from_yaml(filepath):
    with open(filepath, 'r') as yamlfile:
        data = yaml.safe_load(yamlfile)
    data = {x["name"]: x["command"] for x in data}
    return data

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
        self.main_layout = QHBoxLayout(self)

        # Left column layout
        self.left_column = QVBoxLayout()
        
        # Top row with name input
        self.name_input = QLineEdit(self)
        self.name_input.setPlaceholderText("Name")
        self.left_column.addWidget(self.name_input)
        
        # Command buttons
        self.buttons_layout = QVBoxLayout()
        self.buttons = {}
        for command_name in self.commands:
            button = QPushButton(command_name, self)
            button.clicked.connect(self.on_button_clicked)
            self.buttons_layout.addWidget(button)
            self.buttons[command_name] = button
        
        self.left_column.addLayout(self.buttons_layout)
        self.left_column.addStretch()  # Push everything to the top

        # Right column: command input, buttons, and output
        self.command_input = QLineEdit(self)
        self.command_input.setPlaceholderText("Command")
        self.command_input.returnPressed.connect(self.on_return_pressed)

        self.add_button = QPushButton("+", self)
        self.add_button.setFixedSize(30, 30)
        self.add_button.clicked.connect(self.on_add_button_clicked)

        self.remove_button = QPushButton("-", self)
        self.remove_button.setFixedSize(30, 30)
        self.remove_button.clicked.connect(self.on_remove_button_clicked)

        self.output_text = QTextEdit(self)
        self.output_text.setReadOnly(True)
        fixed_width_font = QFont("Monaco")  # or "Courier", "Consolas", etc.
        self.output_text.setFont(fixed_width_font)

        self.input_layout = QHBoxLayout()
        self.input_layout.addWidget(self.command_input)
        self.input_layout.addWidget(self.add_button)
        self.input_layout.addWidget(self.remove_button)

        self.right_layout = QVBoxLayout()
        self.right_layout.addLayout(self.input_layout)
        self.right_layout.addWidget(self.output_text)

        self.main_layout.addLayout(self.left_column)
        self.main_layout.addLayout(self.right_layout)

        self.setLayout(self.main_layout)

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

        # Remove buttons for commands that have been removed
        for command_name in removed_commands:
            button = self.buttons.pop(command_name)
            self.buttons_layout.removeWidget(button)
            button.deleteLater()

        # Update existing buttons with new commands
        for command_name in new_command_names & old_command_names:
            if new_commands[command_name] != self.commands[command_name]:
                self.buttons[command_name].clicked.disconnect()
                self.buttons[command_name].clicked.connect(self.on_button_clicked)

        # Add new buttons for added commands
        for command_name in added_commands:
            button = QPushButton(command_name, self)
            button.clicked.connect(self.on_button_clicked)
            self.buttons_layout.addWidget(button)
            self.buttons[command_name] = button

        # Update the commands dictionary
        self.commands = new_commands

    @pyqtSlot()
    def on_button_clicked(self):
        button = self.sender()
        command_name = button.text()
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
