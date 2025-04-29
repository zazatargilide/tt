import sys
import sqlite3
import time
import os
from collections import defaultdict, deque # <--- Added deque
# Import all necessary PyQt6 classes
from PyQt6.QtWidgets import (
    QMenu, QStyle, QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeWidgetItemIterator, QLineEdit, QLabel, QMessageBox, QListWidgetItem, # QListWidgetItem kept for compatibility, but not needed for the tree
    QDialog, QDialogButtonBox, QInputDialog, QDateTimeEdit, QSpinBox,
    QDateEdit, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QTreeWidget, QTreeWidgetItem, QMenu, QAbstractItemView # <--- Added QTreeWidget, QTreeWidgetItem, QMenu, QAbstractItemView
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPoint, QDateTime, QDate # <--- Added Qt (for Orientation, ItemDataRole etc.)
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QPalette, QLinearGradient, QAction , QIcon # <--- Added QAction

# --- Constants ---
DATABASE_NAME = 'time_tracker.db'
COUNTDOWN_SAVE_THRESHOLD = 0.10  # 10% OVERRUN to suggest saving
COUNTDOWN_MIN_ENTRIES_FOR_SAVE = 1 # Minimum number of entries to suggest saving
MAX_OVERRUN_SECONDS_FOR_RED = 60 # Seconds of overrun for maximum redness (60 seconds)

# --- Database ---
class DatabaseManager:
    def __init__(self, db_name=DATABASE_NAME):
        self.db_name = db_name
        self.conn = None
        self.cursor = None
        self._connect()
        self._create_tables()

    def _connect(self):
        try:
            self.conn = sqlite3.connect(self.db_name, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
            self.conn.execute("PRAGMA foreign_keys = ON;")
            self.cursor = self.conn.cursor()
            print("Database connected.")
        except sqlite3.Error as e:
            print(f"Database connection error: {e}")
            self.conn = None
            self.cursor = None

    def _create_tables(self):
        if not self.conn: return
        try:
            # Activities table with hierarchy support
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    parent_id INTEGER DEFAULT NULL, -- Reference to the parent activity
                    FOREIGN KEY (parent_id) REFERENCES activities (id) ON DELETE SET NULL -- On parent deletion, children become top-level
                )
            ''')
            # Unique index for name within the same parent (including NULL for top level)
            # SQLite doesn't support UNIQUE NULLS NOT DISTINCT, so we check in code
            # self.cursor.execute('''
            #    CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_parent_name ON activities (parent_id, name);
            # ''')
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS time_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_id INTEGER NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (activity_id) REFERENCES activities (id) ON DELETE CASCADE -- If activity is deleted, delete entries too
                )
            ''')
            self.cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_activity_parent_id ON activities (parent_id);
            ''')
            self.cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_activity_id_timestamp ON time_entries (activity_id, timestamp);
            ''')
            self.cursor.execute('''
                 CREATE INDEX IF NOT EXISTS idx_timestamp_date ON time_entries (timestamp);
            ''')
            self.conn.commit()
            print("Tables checked/created.")
        except sqlite3.Error as e:
            print(f"Error creating tables: {e}")

    def _check_activity_name_exists(self, name, parent_id):
        """Checks if an activity with this name exists under the same parent."""
        if not self.conn: return True # Assume exists if no connection
        try:
            if parent_id is None:
                self.cursor.execute("SELECT 1 FROM activities WHERE name = ? AND parent_id IS NULL", (name,))
            else:
                self.cursor.execute("SELECT 1 FROM activities WHERE name = ? AND parent_id = ?", (name, parent_id))
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            print(f"Error checking activity name: {e}")
            return True # Better prevent duplicate creation in case of error

    def add_activity(self, name, parent_id=None):
        """Adds an activity, optionally specifying a parent."""
        if not self.conn or not name: return None
        name = name.strip()
        if not name: return None

        if self._check_activity_name_exists(name, parent_id):
             print(f"Activity '{name}' already exists with the same parent (parent_id: {parent_id}).")
             QMessageBox.warning(None, "Duplicate", f"An activity named '{name}' already exists in this branch.")
             return None # Return None in case of duplicate

        try:
            self.cursor.execute("INSERT INTO activities (name, parent_id) VALUES (?, ?)", (name, parent_id))
            self.conn.commit()
            new_id = self.cursor.lastrowid
            print(f"Activity '{name}' (ID: {new_id}, parent_id: {parent_id}) added.")
            return new_id # Return the ID of the new activity
        except sqlite3.IntegrityError: # This check is now less likely due to _check_activity_name_exists
            print(f"Activity '{name}' already exists (IntegrityError).")
            return None
        except sqlite3.Error as e:
            print(f"Error adding activity: {e}")
            return None

    def get_activities(self):
        """Gets all activities (id, name, parent_id)."""
        if not self.conn: return []
        try:
            self.cursor.execute("SELECT id, name, parent_id FROM activities ORDER BY name")
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Error retrieving activities: {e}")
            return []

    def get_activity_hierarchy(self):
        """Builds the activity hierarchy."""
        if not self.conn: return {}
        try:
            self.cursor.execute("SELECT id, name, parent_id FROM activities")
            activities_raw = self.cursor.fetchall()
            # Dictionary: id -> {activity data}
            activities_dict = {act_id: {'id': act_id, 'name': name, 'parent_id': parent_id, 'children': []}
                               for act_id, name, parent_id in activities_raw}
            # Dictionary: parent_id -> [child nodes] - This is not directly returned, used for building
            top_level = []

            for act_id, data in activities_dict.items():
                parent_id = data['parent_id']
                if parent_id is None:
                    top_level.append(data)
                elif parent_id in activities_dict:
                    activities_dict[parent_id]['children'].append(data)
                else:
                     # If parent not found (data error?), consider it top-level
                     print(f"Warning: Parent ID {parent_id} for activity ID {act_id} not found.")
                     top_level.append(data)

            # Sort children by name at each level
            def sort_children_recursive(nodes):
                nodes.sort(key=lambda x: x['name'])
                for node in nodes:
                    if node['children']:
                        sort_children_recursive(node['children'])

            sort_children_recursive(top_level)
            return top_level # Returns a list of top-level nodes, each containing its children recursively

        except sqlite3.Error as e:
            print(f"Error retrieving activity hierarchy: {e}")
            return []

    def get_descendant_activity_ids(self, activity_id):
        """Returns a set of IDs of all descendant activities (including nested) for the given ID, including the ID itself."""
        if not self.conn or activity_id is None: return set()

        descendants = set()
        queue = deque([activity_id]) # Queue for breadth-first traversal

        while queue:
            current_id = queue.popleft()
            if current_id is None: continue # Skip None IDs

            # Check if this ID has already been processed to avoid infinite loops in case of data errors
            if current_id in descendants:
                continue
            descendants.add(current_id)

            try:
                # Find direct children of the current ID
                self.cursor.execute("SELECT id FROM activities WHERE parent_id = ?", (current_id,))
                children = self.cursor.fetchall()
                for child_id_tuple in children:
                    child_id = child_id_tuple[0]
                    if child_id not in descendants: # Add to queue only if not already there
                        queue.append(child_id)
            except sqlite3.Error as e:
                print(f"Error finding descendants for ID {current_id}: {e}")
                # Continue processing, part of the tree might be skipped

        return descendants


    def add_time_entry(self, activity_id, duration_seconds, timestamp=None):
        """Adds a time entry. Can specify a specific timestamp."""
        if not self.conn or not activity_id or duration_seconds <= 0: return False
        duration_seconds = int(duration_seconds)
        try:
            if timestamp:
                # Ensure timestamp is a datetime object or string in the correct format
                if isinstance(timestamp, QDateTime):
                    ts_str = timestamp.toString("yyyy-MM-dd HH:mm:ss")
                elif isinstance(timestamp, str):
                    # Validate format? Or trust SQLite? Trusting for now.
                    ts_str = timestamp
                else: # Try current time
                    ts_str = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")

                self.cursor.execute(
                    "INSERT INTO time_entries (activity_id, duration_seconds, timestamp) VALUES (?, ?, ?)",
                    (activity_id, duration_seconds, ts_str)
                )
            else:
                self.cursor.execute(
                    "INSERT INTO time_entries (activity_id, duration_seconds) VALUES (?, ?)",
                    (activity_id, duration_seconds)
                )
            self.conn.commit()
            ts_info = f"with timestamp {ts_str}" if timestamp else "with current timestamp"
            print(f"Time entry ({duration_seconds} sec) added for activity_id {activity_id} {ts_info}.")
            return True
        except sqlite3.Error as e:
            print(f"Error adding time entry: {e}")
            return False

    def get_durations(self, activity_id):
        """Gets durations only for *this* specific activity."""
        if not self.conn or not activity_id: return []
        try:
            self.cursor.execute(
                "SELECT duration_seconds FROM time_entries WHERE activity_id = ?",
                (activity_id,)
            )
            return [row[0] for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Error retrieving durations: {e}")
            return []

    def calculate_total_duration_for_activity_branch(self, activity_id):
        """Calculates the *total* duration for an activity and all its descendants."""
        if not self.conn or not activity_id: return 0
        descendant_ids = self.get_descendant_activity_ids(activity_id)
        if not descendant_ids:
            return 0

        try:
            # Create placeholders for IN (?, ?, ...)
            placeholders = ', '.join('?' * len(descendant_ids))
            query = f"SELECT SUM(duration_seconds) FROM time_entries WHERE activity_id IN ({placeholders})"
            self.cursor.execute(query, list(descendant_ids))
            result = self.cursor.fetchone()
            return result[0] if result and result[0] is not None else 0
        except sqlite3.Error as e:
            print(f"Error calculating total duration for branch {activity_id}: {e}")
            return 0

    def calculate_average_duration(self, activity_id):
        """Calculates the average duration for *this* specific activity (excluding children)."""
        durations = self.get_durations(activity_id)
        if not durations:
            return 0
        return sum(durations) / len(durations)

    def get_entry_count(self, activity_id):
        """Gets the number of entries for *this* specific activity."""
        if not self.conn or not activity_id: return 0
        try:
            self.cursor.execute(
                "SELECT COUNT(*) FROM time_entries WHERE activity_id = ?",
                (activity_id,)
            )
            result = self.cursor.fetchone()
            return result[0] if result else 0
        except sqlite3.Error as e:
            print(f"Error getting entry count: {e}")
            return 0

    def get_time_entries_for_activity(self, activity_id):
        """Gets all time entries (id, duration, timestamp_str) for *this* activity."""
        if not self.conn or not activity_id: return []
        try:
            self.cursor.execute(
                "SELECT id, duration_seconds, strftime('%Y-%m-%d %H:%M:%S', timestamp) as timestamp_str FROM time_entries WHERE activity_id = ? ORDER BY timestamp DESC",
                (activity_id,)
            )
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Error retrieving time entries: {e}")
            return []

    def update_time_entry(self, entry_id, new_duration_seconds):
        """Updates the duration of an existing time entry."""
        if not self.conn or not entry_id or new_duration_seconds <= 0: return False
        try:
            new_duration_seconds = int(new_duration_seconds)
            self.cursor.execute(
                "UPDATE time_entries SET duration_seconds = ? WHERE id = ?",
                (new_duration_seconds, entry_id)
            )
            self.conn.commit()
            if self.cursor.rowcount > 0:
                print(f"Time entry ID {entry_id} updated. New duration: {new_duration_seconds} sec.")
                return True
            else:
                print(f"Time entry ID {entry_id} not found for update.")
                return False
        except sqlite3.Error as e:
            print(f"Error updating time entry: {e}")
            return False

    def delete_time_entry(self, entry_id):
        """Deletes a time entry by ID."""
        if not self.conn or not entry_id: return False
        try:
            self.cursor.execute("DELETE FROM time_entries WHERE id = ?", (entry_id,))
            self.conn.commit()
            if self.cursor.rowcount > 0:
                print(f"Time entry ID {entry_id} deleted.")
                return True
            else:
                print(f"Time entry ID {entry_id} not found for deletion.")
                return False
        except sqlite3.Error as e:
            print(f"Error deleting time entry: {e}")
            return False

    def get_entries_for_date(self, date_str):
        """Gets all time entries for the specified date (YYYY-MM-DD), including activity ID and name."""
        if not self.conn or not date_str: return []
        try:
            # Now also retrieves the activity ID
            self.cursor.execute("""
                SELECT a.id, a.name, te.duration_seconds, strftime('%Y-%m-%d %H:%M:%S', te.timestamp) as timestamp_str
                FROM time_entries te
                JOIN activities a ON te.activity_id = a.id
                WHERE DATE(te.timestamp) = ?
                ORDER BY te.timestamp ASC
            """, (date_str,))
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Error retrieving entries for date {date_str}: {e}")
            return []

    def update_activity_name(self, activity_id, new_name, parent_id):
        """Updates the name of an activity."""
        if not self.conn or not activity_id or not new_name: return False
        new_name = new_name.strip()
        if not new_name: return False

        if self._check_activity_name_exists(new_name, parent_id):
             # Additionally check if it's not the same activity
             self.cursor.execute("SELECT id FROM activities WHERE name = ? AND (parent_id = ? OR (parent_id IS NULL AND ? IS NULL))", (new_name, parent_id, parent_id))
             existing = self.cursor.fetchone()
             if existing and existing[0] != activity_id:
                 print(f"Cannot rename: Activity '{new_name}' already exists with the same parent (parent_id: {parent_id}).")
                 QMessageBox.warning(None, "Duplicate", f"An activity named '{new_name}' already exists in this branch.")
                 return False

        try:
            self.cursor.execute("UPDATE activities SET name = ? WHERE id = ?", (new_name, activity_id))
            self.conn.commit()
            if self.cursor.rowcount > 0:
                print(f"Activity ID {activity_id} renamed to '{new_name}'.")
                return True
            else:
                print(f"Activity ID {activity_id} not found for renaming.")
                return False
        except sqlite3.Error as e:
            print(f"Error renaming activity: {e}")
            return False

    def delete_activity(self, activity_id):
        """Deletes an activity and all its descendants."""
        if not self.conn or not activity_id: return False
        descendant_ids = self.get_descendant_activity_ids(activity_id)
        if not descendant_ids:
             print(f"Failed to get descendants for deleting activity ID {activity_id}.")
             return False

        try:
            placeholders = ', '.join('?' * len(descendant_ids))
            # Delete time entries first (could rely on CASCADE, but this is safer)
            # self.cursor.execute(f"DELETE FROM time_entries WHERE activity_id IN ({placeholders})", list(descendant_ids))
            # print(f"Deleted {self.cursor.rowcount} time entries for the activities being deleted.")

            # Delete the activities themselves
            self.cursor.execute(f"DELETE FROM activities WHERE id IN ({placeholders})", list(descendant_ids))
            deleted_count = self.cursor.rowcount
            self.conn.commit()
            print(f"Activity ID {activity_id} and its {len(descendant_ids) - 1} descendants ({deleted_count} total) deleted.")
            return True
        except sqlite3.Error as e:
            print(f"Error deleting activity and its descendants: {e}")
            self.conn.rollback() # Roll back transaction in case of error
            return False

    def get_activity_parent_id(self, activity_id):
        """Gets the parent_id for a given activity."""
        if not self.conn or not activity_id: return None
        try:
            self.cursor.execute("SELECT parent_id FROM activities WHERE id = ?", (activity_id,))
            result = self.cursor.fetchone()
            return result[0] if result else None
        except sqlite3.Error as e:
            print(f"Error retrieving parent_id for activity {activity_id}: {e}")
            return None

    def close(self):
        if self.conn:
            self.conn.close()
            print("Database disconnected.")

# --- Timer Window (unchanged) ---
class TimerWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_overrun = False
        self.overrun_seconds = 0
        self.background_color = QColor(0, 0, 0, 180)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.label = QLabel("00:00:00", self)
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        self.label.setFont(font)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("QLabel { color : white; background-color: transparent; padding: 5px; }")

        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        self.setFixedSize(170, 50)

        self._mouse_press_pos = None
        self._mouse_move_pos = None

    def set_overrun(self, overrun, seconds=0):
        self.is_overrun = overrun
        self.overrun_seconds = seconds if overrun else 0
        self.update_background_color()
        self.update()

    def update_background_color(self):
        if not self.is_overrun:
            self.background_color = QColor(0, 0, 0, 180)
        else:
            red_factor = min(1.0, self.overrun_seconds / MAX_OVERRUN_SECONDS_FOR_RED)
            red_component = int(red_factor * 150)
            self.background_color = QColor(red_component, 0, 0, 190)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self.background_color))
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        border_radius = 10.0
        rect = QRectF(self.rect())
        rect.adjust(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rect, border_radius, border_radius)

    def setText(self, text):
        self.label.setText(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_press_pos = event.globalPosition().toPoint()
            self._mouse_move_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._mouse_press_pos:
            current_pos = self.pos()
            global_pos = event.globalPosition().toPoint()
            diff = global_pos - self._mouse_move_pos
            self.move(current_pos + diff)
            self._mouse_move_pos = global_pos
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._mouse_press_pos:
            self._mouse_press_pos = None
            self._mouse_move_pos = None
            event.accept()

# --- Entry Management Dialog (minimal changes) ---
class EntryManagementDialog(QDialog):
    def __init__(self, activity_id, activity_name, db_manager, parent=None):
        super().__init__(parent)
        self.activity_id = activity_id
        self.activity_name = activity_name
        self.db_manager = db_manager
        self.needs_update = False # Signals the main window that the average time might have changed

        self.setWindowTitle(f"Entries for: {self.activity_name}")
        self.setMinimumSize(450, 300)

        layout = QVBoxLayout(self)
        # Use QTableWidget for better date/time display
        self.entries_table = QTableWidget()
        self.entries_table.setColumnCount(3)
        self.entries_table.setHorizontalHeaderLabels(["ID", "Duration", "Date & Time"])
        self.entries_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.entries_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.entries_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.entries_table.verticalHeader().setVisible(False)
        header = self.entries_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # ID
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents) # Duration
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)          # Timestamp
        self.entries_table.setSortingEnabled(True)
        self.entries_table.sortByColumn(2, Qt.SortOrder.DescendingOrder) # Sort by date descending
        self.entries_table.doubleClicked.connect(self.edit_selected_entry) # Edit on double-click

        layout.addWidget(QLabel("Entries (double-click to edit):"))
        layout.addWidget(self.entries_table)

        buttons_layout = QHBoxLayout()
        add_button = QPushButton("Add")
        add_button.clicked.connect(self.add_entry)
        edit_button = QPushButton("Edit")
        edit_button.clicked.connect(self.edit_selected_entry)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self.delete_selected_entry)
        buttons_layout.addWidget(add_button)
        buttons_layout.addWidget(edit_button)
        buttons_layout.addWidget(delete_button)
        layout.addLayout(buttons_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)
        self.setLayout(layout)
        self.load_entries()

    def load_entries(self):
        """Loads entries into the QTableWidget."""
        self.entries_table.setSortingEnabled(False) # Disable sorting during population
        self.entries_table.setRowCount(0)
        entries = self.db_manager.get_time_entries_for_activity(self.activity_id)
        buttons_to_disable = ["Edit", "Delete"] # Use English text now

        if not entries:
            # Can add a placeholder row or just leave the table empty
            # self.entries_table.setRowCount(1)
            # placeholder = QTableWidgetItem("No entries for this activity.")
            # placeholder.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # self.entries_table.setItem(0, 0, placeholder)
            # self.entries_table.setSpan(0, 0, 1, 3)
            self.entries_table.setEnabled(False)
            for button in self.findChildren(QPushButton):
                if button.text() in buttons_to_disable:
                    button.setEnabled(False)
            self.entries_table.setSortingEnabled(True)
            return

        self.entries_table.setEnabled(True)
        for button in self.findChildren(QPushButton):
             if button.text() in buttons_to_disable:
                 button.setEnabled(True)

        self.entries_table.setRowCount(len(entries))
        for row, (entry_id, duration, timestamp_str) in enumerate(entries):
            formatted_duration = MainWindow.format_time(None, duration)
            try:
                dt_obj = QDateTime.fromString(timestamp_str, "yyyy-MM-dd HH:mm:ss")
                formatted_timestamp = dt_obj.toString("yyyy-MM-dd HH:mm:ss")
            except Exception:
                formatted_timestamp = timestamp_str # Fallback

            id_item = QTableWidgetItem(str(entry_id))
            id_item.setData(Qt.ItemDataRole.UserRole, entry_id) # Store ID in data
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            duration_item = QTableWidgetItem(formatted_duration)
            duration_item.setData(Qt.ItemDataRole.UserRole, duration) # Store duration in seconds
            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            timestamp_item = QTableWidgetItem(formatted_timestamp)
            timestamp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.entries_table.setItem(row, 0, id_item)
            self.entries_table.setItem(row, 1, duration_item)
            self.entries_table.setItem(row, 2, timestamp_item)

        self.entries_table.setSortingEnabled(True) # Enable sorting again

    def get_selected_entry_data(self):
        """Returns the ID and current duration of the selected entry."""
        selected_rows = self.entries_table.selectionModel().selectedRows()
        if not selected_rows:
            return None, None
        selected_row_index = selected_rows[0].row()
        id_item = self.entries_table.item(selected_row_index, 0)
        duration_item = self.entries_table.item(selected_row_index, 1)
        if not id_item or not duration_item:
            return None, None

        entry_id = id_item.data(Qt.ItemDataRole.UserRole)
        current_duration = duration_item.data(Qt.ItemDataRole.UserRole)
        return entry_id, current_duration

    def get_duration_input(self, title="Enter Duration", current_seconds=0):
        """Gets duration input (H:M:S) from the user via a dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)

        label = QLabel("Specify duration:")
        layout.addWidget(label)

        time_input_layout = QHBoxLayout()
        hours_spin = QSpinBox()
        hours_spin.setRange(0, 999) # Allow more than 23 hours
        hours_spin.setSuffix(" h")
        mins_spin = QSpinBox()
        mins_spin.setRange(0, 59)
        mins_spin.setSuffix(" m")
        secs_spin = QSpinBox()
        secs_spin.setRange(0, 59)
        secs_spin.setSuffix(" s")

        if current_seconds > 0:
             h, rem = divmod(current_seconds, 3600)
             m, s = divmod(rem, 60)
             hours_spin.setValue(h)
             mins_spin.setValue(m)
             secs_spin.setValue(s)
        else:
             mins_spin.setValue(10) # Default 10 minutes

        time_input_layout.addWidget(hours_spin)
        time_input_layout.addWidget(mins_spin)
        time_input_layout.addWidget(secs_spin)
        layout.addLayout(time_input_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            total_seconds = hours_spin.value() * 3600 + mins_spin.value() * 60 + secs_spin.value()
            return total_seconds if total_seconds > 0 else None
        return None


    def add_entry(self):
        # --- Use a new dialog for time input ---
        # duration_seconds = self.get_duration_input("Add New Entry")
        # if duration_seconds is None: return # User canceled

        # --- Option to select date and time ---
        dt_dialog = QDialog(self)
        dt_dialog.setWindowTitle("Add Entry")
        dt_layout = QVBoxLayout(dt_dialog)

        dt_edit = QDateTimeEdit(QDateTime.currentDateTime())
        dt_edit.setCalendarPopup(True)
        dt_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        dt_layout.addWidget(QLabel("Entry date and time:"))
        dt_layout.addWidget(dt_edit)

        # Get duration input after setting up the rest of the dialog
        duration_seconds = self.get_duration_input("Specify Duration", 0)
        if duration_seconds is None: return # User canceled duration input

        formatted_duration = MainWindow.format_time(None, duration_seconds)
        # Add a label to show the chosen duration *before* showing the OK/Cancel buttons
        dt_layout.addWidget(QLabel(f"Duration: {formatted_duration} ({duration_seconds} sec)"))

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(dt_dialog.accept)
        button_box.rejected.connect(dt_dialog.reject)
        dt_layout.addWidget(button_box)

        if dt_dialog.exec() == QDialog.DialogCode.Accepted:
            selected_dt = dt_edit.dateTime()
            if self.db_manager.add_time_entry(self.activity_id, duration_seconds, selected_dt):
                self.needs_update = True
                self.load_entries()
            else:
                QMessageBox.warning(self, "Error", "Failed to add entry.")


    def edit_selected_entry(self):
        entry_id, current_duration = self.get_selected_entry_data()

        if entry_id is None:
            QMessageBox.information(self, "Information", "Please select an entry in the table first.")
            return

        new_duration_seconds = self.get_duration_input("Edit Entry", current_duration)

        if new_duration_seconds is not None and new_duration_seconds > 0:
             if new_duration_seconds != current_duration:
                 if self.db_manager.update_time_entry(entry_id, new_duration_seconds):
                     self.needs_update = True
                     self.load_entries()
                 else:
                     QMessageBox.warning(self, "Error", "Failed to update entry.")
             else:
                 print("Duration not changed.")

    def delete_selected_entry(self):
        entry_id, _ = self.get_selected_entry_data()

        if entry_id is None:
            QMessageBox.information(self, "Information", "Please select an entry in the table first.")
            return

        # Find the text of the selected row for the message
        selected_rows = self.entries_table.selectionModel().selectedRows()
        row_index = selected_rows[0].row()
        duration_text = self.entries_table.item(row_index, 1).text()
        timestamp_text = self.entries_table.item(row_index, 2).text()
        confirm_text = f"Delete entry: {timestamp_text} - {duration_text} (ID: {entry_id})?"

        reply = QMessageBox.question(
            self, "Confirmation", confirm_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self.db_manager.delete_time_entry(entry_id):
                self.needs_update = True
                self.load_entries()
            else:
                QMessageBox.warning(self, "Error", "Failed to delete entry.")

# --- Daily Snapshot Dialog (Significant changes) ---
class DailySnapshotDialog(QDialog):
    def __init__(self, db_manager, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.setWindowTitle("Daily Snapshot")
        self.setMinimumSize(700, 550) # Slightly larger size

        layout = QVBoxLayout(self)
        date_layout = QHBoxLayout()
        date_layout.addWidget(QLabel("Select date:"))
        self.date_edit = QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        show_button = QPushButton("Show")
        show_button.clicked.connect(self.load_snapshot)
        date_layout.addWidget(self.date_edit)
        date_layout.addWidget(show_button)
        date_layout.addStretch()
        layout.addLayout(date_layout)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- Widget for hierarchical summary ---
        summary_widget = QWidget()
        summary_layout = QVBoxLayout(summary_widget)
        summary_layout.setContentsMargins(0,0,0,0)
        summary_layout.addWidget(QLabel("Daily Activity Summary (including sub-activities):"))
        self.summary_tree = QTreeWidget() # <--- Replaced QTableWidget with QTreeWidget
        self.summary_tree.setColumnCount(2)
        self.summary_tree.setHeaderLabels(["Activity", "Total Duration"])
        header_summary = self.summary_tree.header()
        header_summary.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_summary.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.summary_tree.setSortingEnabled(True)
        self.summary_tree.sortByColumn(1, Qt.SortOrder.DescendingOrder) # Sort by time descending
        summary_layout.addWidget(self.summary_tree)
        splitter.addWidget(summary_widget)

        # --- Widget for detailed entries (remains QTableWidget) ---
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0,0,0,0)
        details_layout.addWidget(QLabel("All Entries for the Day:"))
        self.entries_table = QTableWidget()
        self.entries_table.setColumnCount(3)
        self.entries_table.setHorizontalHeaderLabels(["Activity", "Duration", "Start/Entry Time"])
        header_details = self.entries_table.horizontalHeader()
        header_details.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_details.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_details.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.entries_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.entries_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.entries_table.setSortingEnabled(True)
        details_layout.addWidget(self.entries_table)
        splitter.addWidget(details_widget)

        splitter.setSizes([200, 350]) # Give the tree a bit more space
        layout.addWidget(splitter)

        self.summary_label = QLabel("Total time for the day: 00:00:00")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        font = self.summary_label.font()
        font.setBold(True)
        self.summary_label.setFont(font)
        layout.addWidget(self.summary_label)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        self.setLayout(layout)
        self.load_snapshot() # Load on opening

    def load_snapshot(self):
        """Loads, aggregates, and displays data for the selected date, considering hierarchy."""
        selected_date = self.date_edit.date().toString("yyyy-MM-dd")
        print(f"Loading snapshot for {selected_date}...")

        # 1. Get all entries for this date (activity_id, activity_name, duration, timestamp_str)
        entries = self.db_manager.get_entries_for_date(selected_date)

        # 2. Clear widgets
        self.entries_table.setSortingEnabled(False)
        self.entries_table.setRowCount(0)
        self.summary_tree.clear()
        self.summary_tree.setSortingEnabled(False)

        total_duration_day_seconds = 0
        if not entries:
            print(f"No entries for {selected_date}.")
            self.summary_label.setText("Total time for the day: 00:00:00")
            self.entries_table.setSortingEnabled(True)
            self.summary_tree.setSortingEnabled(True)
            return

        # 3. Populate the detailed entries table and calculate total time
        self.entries_table.setRowCount(len(entries))
        # Dictionary to store *direct* time spent per activity ID
        direct_time_by_activity_id = defaultdict(int)

        for row, (activity_id, activity_name, duration, timestamp_str) in enumerate(entries):
            total_duration_day_seconds += duration
            direct_time_by_activity_id[activity_id] += duration

            # Fill details table
            formatted_duration = MainWindow.format_time(None, duration)
            try:
                dt_obj = QDateTime.fromString(timestamp_str, "yyyy-MM-dd HH:mm:ss")
                formatted_timestamp = dt_obj.toString("HH:mm:ss") # Show only time in details
            except Exception:
                formatted_timestamp = timestamp_str

            name_item = QTableWidgetItem(activity_name)
            duration_item = QTableWidgetItem(formatted_duration)
            time_item = QTableWidgetItem(formatted_timestamp)
            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # Store numeric value for sorting
            duration_item.setData(Qt.ItemDataRole.UserRole, duration)

            self.entries_table.setItem(row, 0, name_item)
            self.entries_table.setItem(row, 1, duration_item)
            self.entries_table.setItem(row, 2, time_item)

        self.entries_table.setSortingEnabled(True)

        # 4. Get the full activity hierarchy
        # activity_hierarchy format: [{id: 1, name: 'A', parent_id: None, children: [{id: 2, ...}, ...]}, ...]
        activity_hierarchy = self.db_manager.get_activity_hierarchy()
        # Dictionary to store ID -> hierarchy node for quick access
        activity_nodes_map = {}
        # Dictionary to store aggregated time (including descendants) per ID
        aggregated_time_by_activity_id = defaultdict(int)

        # 5. Recursive function to traverse hierarchy and aggregate time
        def process_node(node):
            activity_id = node['id']
            activity_nodes_map[activity_id] = node # Store node in map

            # Time directly recorded for this activity
            current_node_direct_time = direct_time_by_activity_id.get(activity_id, 0)
            total_time_for_node = current_node_direct_time

            # Recursively process child nodes
            for child_node in node['children']:
                child_total_time = process_node(child_node)
                total_time_for_node += child_total_time # Add descendants' time to parent

            aggregated_time_by_activity_id[activity_id] = total_time_for_node
            return total_time_for_node

        # Start processing for all top-level nodes
        for top_level_node in activity_hierarchy:
            process_node(top_level_node)

        # 6. Recursive function to build the QTreeWidget summary
        def build_summary_tree(parent_item, nodes):
             for node_data in nodes:
                 activity_id = node_data['id']
                 activity_name = node_data['name']
                 total_seconds = aggregated_time_by_activity_id.get(activity_id, 0)

                 # Add item to the tree only if time was spent on it or its descendants
                 if total_seconds > 0:
                     formatted_total_duration = MainWindow.format_time(None, total_seconds)

                     tree_item = QTreeWidgetItem(parent_item)
                     tree_item.setText(0, activity_name) # Activity name
                     tree_item.setText(1, formatted_total_duration) # Aggregated time
                     tree_item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)

                     # Store numeric seconds value for sorting in the second column
                     tree_item.setData(1, Qt.ItemDataRole.UserRole, total_seconds)
                     # Store activity ID for potential future actions
                     tree_item.setData(0, Qt.ItemDataRole.UserRole, activity_id)

                     # Recursively build for child nodes
                     if node_data['children']:
                         build_summary_tree(tree_item, node_data['children'])

        # Build the tree starting from the QTreeWidget's invisible root item
        build_summary_tree(self.summary_tree.invisibleRootItem(), activity_hierarchy)
        self.summary_tree.expandAll() # Expand all nodes by default
        self.summary_tree.setSortingEnabled(True)
        # Restore default sorting (by time descending)
        self.summary_tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)

        # 7. Update the label with the total time for the day
        formatted_total_duration_day = MainWindow.format_time(None, total_duration_day_seconds)
        self.summary_label.setText(f"Total time for the day: {formatted_total_duration_day}")
        print(f"Snapshot for {selected_date} loaded. Entries: {len(entries)}. Total time: {formatted_total_duration_day}")


# --- Main Window (Significant changes) ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager()
        self.timer_window = TimerWindow()
        self.qtimer = QTimer(self)
        self.qtimer.timeout.connect(self.update_timer)

        self.current_activity_id = None
        self.current_activity_name = None
        self.timer_type = None # 'work' or 'countdown'
        self.start_time = None
        self.countdown_average_duration = 0 # The average duration used for the current countdown
        self.average_duration_at_countdown_start = 0 # Average for the *specific* activity when countdown started

        # --- Replace QListWidget with QTreeWidget ---
        self.activity_tree = None # Initialized in init_ui
        self.manage_entries_button = None
        self.snapshot_button = None

        self.init_ui()
        self.apply_dark_theme()
        self.load_activities()

    def init_ui(self):
        # Window title translated - "Ritual" might be specific, "Time Tracker" could be an alternative
        self.setWindowTitle("Ritual 0.07")
        self.setGeometry(100, 100, 500, 450) # Slightly wider

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Activity adding section (now via tree context menu) ---
        # Removed the input field and "Add Activity" button from here

        # --- Activity Tree ---
        main_layout.addWidget(QLabel("Activities (Right-click to add/manage):")) # Label above the tree
        self.activity_tree = QTreeWidget()
        self.activity_tree.setColumnCount(1) # Only name in the main view
        self.activity_tree.setHeaderHidden(True) # Hide the column header
        self.activity_tree.currentItemChanged.connect(self.activity_selected)
        # Enable context menu
        self.activity_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.activity_tree.customContextMenuRequested.connect(self.show_activity_context_menu)
        self.activity_tree.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop) # Disable Drag & Drop for now
        main_layout.addWidget(self.activity_tree)

        # --- Management Buttons ---
        management_layout = QHBoxLayout()
        self.manage_entries_button = QPushButton("Manage Entries")
        self.manage_entries_button.clicked.connect(self.open_entry_management)
        self.manage_entries_button.setEnabled(False) # Enabled on selection

        self.snapshot_button = QPushButton("Daily Snapshot")
        self.snapshot_button.clicked.connect(self.open_daily_snapshot)

        management_layout.addWidget(self.manage_entries_button)
        management_layout.addWidget(self.snapshot_button)
        main_layout.addLayout(management_layout)

        # --- Timer Buttons ---
        timer_buttons_layout = QHBoxLayout()
        self.work_timer_button = QPushButton("Start Tracking") # Initial text
        self.work_timer_button.setCheckable(True) # Used to manage start/stop state visually
        self.work_timer_button.clicked.connect(self.toggle_timer)
        self.work_timer_button.setEnabled(False) # Enabled on selection

        self.countdown_timer_button = QPushButton("Start Countdown")
        self.countdown_timer_button.clicked.connect(self.start_countdown_timer)
        self.countdown_timer_button.setEnabled(False) # Enabled if average time exists

        timer_buttons_layout.addWidget(self.work_timer_button)
        timer_buttons_layout.addWidget(self.countdown_timer_button)
        main_layout.addLayout(timer_buttons_layout)

        # --- Status Bar ---
        self.status_label = QLabel("Select an activity")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.status_label)

    def apply_dark_theme(self):
        # (Theme code remains unchanged, but includes styles for QTreeWidget now)
        dark_palette = QPalette()
        # ... (all palette color settings as before) ...
        dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
        dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.black)
        dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(127, 127, 127))
        dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(127, 127, 127))
        dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(127, 127, 127))

        app = QApplication.instance()
        if app:
            app.setPalette(dark_palette)
            # Stylesheet includes styles for QTreeWidget, QMenu, etc.
            app.setStyleSheet("""
                QMainWindow { border: none; background-color: #353535; }
                QWidget { color: white; background-color: #353535; }

                QPushButton {
                    border: 1px solid #555; padding: 6px 12px; min-height: 20px;
                    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #555, stop: 1 #444);
                    color: white; border-radius: 4px;
                }
                QPushButton:hover { background-color: #5E5E5E; }
                QPushButton:pressed { background-color: #707070; border: 1px solid #666; }
                QPushButton:checked { background-color: #4CAF50; border: 1px solid #3a8a40; } /* Used for Start/Stop state */
                QPushButton:disabled { background-color: #4F4F4F; color: #888; border: 1px solid #4F4F4F;}

                QLineEdit, QSpinBox, QDateTimeEdit, QDateEdit {
                    border: 1px solid #555; padding: 5px; background-color: #2D2D2D; color: white;
                    border-radius: 3px; selection-background-color: #2a82da; selection-color: white;
                }
                QLineEdit:focus, QSpinBox:focus, QDateTimeEdit:focus, QDateEdit:focus {
                     border: 1px solid #2a82da;
                }

                /* Styles for QTreeWidget */
                QTreeWidget {
                    border: 1px solid #555;
                    background-color: #2D2D2D;
                    color: white;
                    alternate-background-color: #353535;
                    selection-background-color: #2a82da;
                    selection-color: white;
                    outline: none; /* Removes focus dotted border */
                }
                QTreeWidget::item {
                    padding: 4px;
                    border-bottom: 1px solid #444; /* Separator between items */
                }
                QTreeWidget::item:selected {
                    background-color: #2a82da;
                    color: white;
                }
                QTreeWidget::item:alternate {
                    background-color: #353535;
                }
                 /* Styles for tree branches */
                QTreeView::branch {
                     background: transparent;
                 }
                 QTreeView::branch:has-children:!has-siblings:closed,
                 QTreeView::branch:closed:has-children:has-siblings {
                         border-image: none;
                         image: url(:/qt-project.org/styles/commonstyle/images/branch-closed-16.png); /* Standard PyQt icon */
                 }
                 QTreeView::branch:open:has-children:!has-siblings,
                 QTreeView::branch:open:has-children:has-siblings  {
                         border-image: none;
                         image: url(:/qt-project.org/styles/commonstyle/images/branch-open-16.png); /* Standard PyQt icon */
                 }

                QHeaderView::section {
                    background-color: #444; color: white; padding: 5px;
                    border: 1px solid #555; border-bottom: 2px solid #666; font-weight: bold;
                }
                QHeaderView::section:checked { background-color: #2a82da; }

                QDateEdit::drop-down, QDateTimeEdit::drop-down {
                    subcontrol-origin: padding; subcontrol-position: top right; width: 18px;
                    border-left-width: 1px; border-left-color: #555; border-left-style: solid;
                    border-top-right-radius: 3px; border-bottom-right-radius: 3px;
                    background-color: #444;
                }
                /* QDateEdit::down-arrow { image: url(path/to/icon.png); } */

                QDateEdit QAbstractItemView, QDateTimeEdit QAbstractItemView {
                    background-color: #2D2D2D; selection-background-color: #2a82da;
                    color: white; outline: 1px solid #555; border: none;
                }
                 QCalendarWidget QWidget#qt_calendar_navigationbar {
                     background-color: #444;
                 }
                 QCalendarWidget QToolButton {
                     color: white; background-color: #555; border: none; margin: 2px; padding: 3px;
                 }
                 QCalendarWidget QToolButton:hover { background-color: #666; }
                 QCalendarWidget QMenu { background-color: #2D2D2D; color: white; }
                 QCalendarWidget QSpinBox { background-color: #2D2D2D; color: white; }
                 QCalendarWidget QWidget { alternate-background-color: #353535; } /* Day colors */
                 QCalendarWidget QAbstractItemView:enabled { color: white; selection-background-color: #2a82da; } /* Text and selection color */
                 QCalendarWidget QAbstractItemView:disabled { color: #888; } /* Other month days color */

                QSplitter { background-color: #353535; }
                QSplitter::handle:vertical {
                     background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #666, stop:1 #555);
                     height: 7px; border-top: 1px solid #777; border-bottom: 1px solid #444; margin: 1px 0;
                }
                QSplitter::handle:vertical:hover { background-color: #777; }
                QSplitter::handle:horizontal { /* Not used, but kept */
                     background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #666, stop:1 #555);
                     width: 7px; border-left: 1px solid #777; border-right: 1px solid #444; margin: 0 1px;
                }
                QSplitter::handle:horizontal:hover { background-color: #777; }

                QDialog { background-color: #353535; }
                QLabel { padding: 2px; color: white; background-color: transparent;}

                QDialogButtonBox QPushButton { min-width: 80px; }

                /* Special styles for Input Dialogs to make inputs readable */
                QInputDialog { background-color: #353535; color: white; }
                QInputDialog QLabel { color: white; }
                QInputDialog QLineEdit { background-color: #FFF; color: black; border: 1px solid #AAA; padding: 4px; }
                QInputDialog QSpinBox { background-color: #FFF; color: black; border: 1px solid #AAA; padding: 4px; }
                QInputDialog QDateTimeEdit { background-color: #FFF; color: black; border: 1px solid #AAA; padding: 4px; }
                QInputDialog QDateEdit { background-color: #FFF; color: black; border: 1px solid #AAA; padding: 4px; }
                QInputDialog QPushButton { color: white; background-color: #555; border: 1px solid #666; padding: 5px; min-width: 70px; }
                QInputDialog QPushButton:hover { background-color: #6E6E6E; }
                QInputDialog QPushButton:pressed { background-color: #808080; }

                QMessageBox { background-color: #353535; }
                QMessageBox QLabel {
                    color: white;
                    padding: 15px;
                    qproperty-alignment: 'AlignCenter'; /* Center alignment */
                 }
                QMessageBox QPushButton {
                    min-width: 80px;
                    padding: 6px 12px;
                 }

                 /* Styles for QMenu */
                 QMenu {
                     background-color: #2D2D2D; /* Menu background color */
                     border: 1px solid #555; /* Menu border */
                     color: white; /* Text color */
                     padding: 5px; /* Padding inside menu */
                 }
                 QMenu::item {
                     padding: 5px 25px 5px 20px; /* Padding for menu items (right/left) */
                     border: 1px solid transparent; /* Transparent border by default */
                 }
                 QMenu::item:selected {
                     background-color: #2a82da; /* Background color on hover/selection */
                     color: white; /* Text color on hover/selection */
                 }
                 QMenu::separator {
                     height: 1px;
                     background: #555; /* Separator color */
                     margin-left: 10px;
                     margin-right: 10px;
                     margin-top: 2px;
                     margin-bottom: 2px;
                 }
                 QMenu::indicator { /* Style for checkmarks etc., if used */
                     width: 13px;
                     height: 13px;
                 }

                 /* Table Widget specific style */
                 QTableWidget {
                     border: 1px solid #555; background-color: #2D2D2D; color: white;
                     alternate-background-color: #353535; gridline-color: #444;
                     selection-background-color: #2a82da; selection-color: white; outline: none;
                 }
                 QTableWidget::item { padding: 4px; border-bottom: 1px solid #444;}
                 QTableWidget::item:selected { background-color: #2a82da; color: white; }
                 QTableWidget::item:alternate { background-color: #353535; }

            """)

    def load_activities(self):
        """Loads the activity hierarchy into the QTreeWidget."""
        self.activity_tree.clear()
        self.activity_tree.setSortingEnabled(False) # Disable sorting during load

        # Get hierarchy: [{id:.., name:.., parent:.., children:[...]}, ...]
        hierarchy = self.db_manager.get_activity_hierarchy()

        # Recursive function to add nodes to the tree
        def add_items_recursive(parent_widget_item, activity_nodes):
            for node in activity_nodes:
                item = QTreeWidgetItem(parent_widget_item)
                item.setText(0, node['name'])
                item.setData(0, Qt.ItemDataRole.UserRole, node['id']) # Store activity ID
                # Recursively add child elements
                if node['children']:
                    add_items_recursive(item, node['children'])

        # Add nodes starting from the tree's invisible root item
        add_items_recursive(self.activity_tree.invisibleRootItem(), hierarchy)

        self.activity_tree.expandAll() # Expand all nodes
        self.activity_tree.setSortingEnabled(True) # Enable sorting (by name, column 0)
        self.activity_tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        if not hierarchy:
            self.status_label.setText("Add the first activity (Right-click empty space)")
        else:
            self.status_label.setText("Select an activity")
        self.activity_selected(None) # Reset selection and update buttons

    def show_activity_context_menu(self, position):
        """Displays the context menu for the activity tree."""
        menu = QMenu(self)
        selected_item = self.activity_tree.currentItem()
        selected_id = selected_item.data(0, Qt.ItemDataRole.UserRole) if selected_item else None

        # --- Actions always available ---
        add_top_level_action = QAction("Add Top-Level Activity", self)
        # Get standard "Add" icon - DEFINE VARIABLE HERE
        add_icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        add_top_level_action.setIcon(add_icon)
        add_top_level_action.triggered.connect(lambda: self.add_activity_action(parent_id=None))
        menu.addAction(add_top_level_action)

        # --- Actions available when an item is selected ---
        if selected_item:
            add_sub_action = QAction(f"Add Sub-Activity to '{selected_item.text(0)}'", self)
            # Use the previously defined "Add" icon
            add_sub_action.setIcon(add_icon)
            add_sub_action.triggered.connect(lambda: self.add_activity_action(parent_id=selected_id))
            menu.addAction(add_sub_action)

            menu.addSeparator()

            rename_action = QAction("Rename", self)
            rename_icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView) # Edit/details icon
            rename_action.setIcon(rename_icon)
            rename_action.triggered.connect(self.rename_activity_action)
            menu.addAction(rename_action)

            delete_action = QAction("Delete", self)
            delete_icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon) # Get standard trash icon
            delete_action.setIcon(delete_icon) # Set icon
            delete_action.triggered.connect(self.delete_activity_action)
            menu.addAction(delete_action)
        menu.exec(self.activity_tree.viewport().mapToGlobal(position))

    def add_activity_action(self, parent_id=None):
        """Handler for the add activity action (from menu)."""
        parent_name_suffix = ""
        if parent_id:
             item = self._find_tree_item_by_id(parent_id)
             if item: parent_name_suffix = f" under '{item.text(0)}'" # Changed suffix for clarity

        text, ok = QInputDialog.getText(self, "Add Activity", f"Enter name for the new activity{parent_name_suffix}:")
        if ok and text.strip():
             new_activity_id = self.db_manager.add_activity(text.strip(), parent_id)
             if new_activity_id is not None:
                 self.load_activities() # Reload the entire tree
                 # Try to select the newly added item
                 new_item = self._find_tree_item_by_id(new_activity_id)
                 if new_item:
                     self.activity_tree.setCurrentItem(new_item)
        elif ok: # Clicked OK, but text is empty
             QMessageBox.warning(self, "Error", "Activity name cannot be empty.")

    def rename_activity_action(self):
        """Handler for the rename activity action."""
        selected_item = self.activity_tree.currentItem()
        if not selected_item: return

        activity_id = selected_item.data(0, Qt.ItemDataRole.UserRole)
        current_name = selected_item.text(0)
        parent_item = selected_item.parent()
        # Ensure parent_id is None for top-level items, not the invisible root's data
        parent_id = parent_item.data(0, Qt.ItemDataRole.UserRole) if parent_item and self.activity_tree.indexOfTopLevelItem(parent_item) == -1 else None

        new_name, ok = QInputDialog.getText(self, "Rename Activity", "Enter new name:", QLineEdit.EchoMode.Normal, current_name)

        if ok and new_name.strip() and new_name.strip() != current_name:
             # Get parent_id from DB for uniqueness check (parent_id from tree might not be reliable if tree structure differs)
             db_parent_id = self.db_manager.get_activity_parent_id(activity_id)
             if self.db_manager.update_activity_name(activity_id, new_name.strip(), db_parent_id):
                 # Update item text in the tree without full reload
                 selected_item.setText(0, new_name.strip())
                 # Update status if it was the selected activity
                 if activity_id == self.current_activity_id:
                     self.current_activity_name = new_name.strip()
                     self.activity_selected(selected_item) # Will update status bar text
             # else: # Error will be shown by update_activity_name (via QMessageBox)
                 pass
        elif ok and not new_name.strip():
             QMessageBox.warning(self, "Error", "Activity name cannot be empty.")

    def delete_activity_action(self):
        """Handler for the delete activity action."""
        selected_item = self.activity_tree.currentItem()
        if not selected_item: return

        activity_id = selected_item.data(0, Qt.ItemDataRole.UserRole)
        activity_name = selected_item.text(0)
        # child_count = selected_item.childCount() # Direct children only

        warning_message = ""
        # Use DB function to get all descendants for accurate warning
        all_descendants = self.db_manager.get_descendant_activity_ids(activity_id)
        # Exclude the item itself if it's returned in the set
        descendant_count = len(all_descendants) - 1 if activity_id in all_descendants else len(all_descendants)

        if descendant_count > 0:
             warning_message = f"\n\nWARNING: This will also delete all {descendant_count} child activities and all associated time entries!"

        reply = QMessageBox.question(
            self, "Confirm Deletion",
            f"Are you sure you want to delete activity '{activity_name}' (ID: {activity_id})?{warning_message}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
             if self.db_manager.delete_activity(activity_id):
                 # If the currently selected activity was deleted, reset selection
                 if activity_id == self.current_activity_id:
                     self.current_activity_id = None
                     self.current_activity_name = None
                 self.load_activities() # Reload the tree
             else:
                 QMessageBox.critical(self, "Deletion Error", f"Failed to delete activity '{activity_name}'. Check console for details.")

    def _find_tree_item_by_id(self, activity_id):
        """Helper method to find a QTreeWidgetItem by activity ID."""
        if activity_id is None: return None
        # Ensure QTreeWidgetItemIterator is available before use
        try:
             from PyQt6.QtWidgets import QTreeWidgetItemIterator
        except ImportError:
             print("Error: Failed to import QTreeWidgetItemIterator!")
             return None

        iterator = QTreeWidgetItemIterator(self.activity_tree)
        while iterator.value():
            item = iterator.value()
            if item.data(0, Qt.ItemDataRole.UserRole) == activity_id:
                return item
            iterator += 1
        return None

    def activity_selected(self, current_item, previous_item=None): # PyQt passes both
        """Handler for item selection in QTreeWidget."""
        # --- Logic to prevent changing selection if timer is active ---
        if self.qtimer.isActive():
            is_different_item = current_item and current_item.data(0, Qt.ItemDataRole.UserRole) != self.current_activity_id
            is_deselected = not current_item and self.current_activity_id is not None

            if is_different_item or is_deselected:
                # Restore selection to the previously active item
                previous_valid_item = self._find_tree_item_by_id(self.current_activity_id)
                if previous_valid_item:
                    self.activity_tree.blockSignals(True) # Block signals during set
                    self.activity_tree.setCurrentItem(previous_valid_item)
                    self.activity_tree.blockSignals(False) # Unblock
                if is_different_item:
                     QMessageBox.warning(self, "Timer Active", "Stop the timer before changing the activity.")
                return # Interrupt further selection processing

        # --- Update UI if timer is not active or the same item is clicked ---
        if current_item:
            self.current_activity_id = current_item.data(0, Qt.ItemDataRole.UserRole)
            self.current_activity_name = current_item.text(0)

            # Calculate average time only for *this* specific activity
            avg_duration_specific = self.db_manager.calculate_average_duration(self.current_activity_id)
            # Calculate total time for the branch (including children) - just for info
            total_duration_branch = self.db_manager.calculate_total_duration_for_activity_branch(self.current_activity_id)

            avg_text = f"Avg: {self.format_time(None, avg_duration_specific)}" if avg_duration_specific > 0 else "Avg: no data"
            total_text = f"Branch Total: {self.format_time(None, total_duration_branch)}"

            self.countdown_timer_button.setEnabled(avg_duration_specific > 0)
            self.status_label.setText(f"Selected: {self.current_activity_name} ({avg_text} | {total_text})")
            self.work_timer_button.setEnabled(True)
            if self.manage_entries_button:
                self.manage_entries_button.setEnabled(True)
        else: # Nothing selected
            self.current_activity_id = None
            self.current_activity_name = None
            self.status_label.setText("Select an activity")
            self.work_timer_button.setEnabled(False)
            self.countdown_timer_button.setEnabled(False)
            if self.manage_entries_button:
                self.manage_entries_button.setEnabled(False)

    def open_entry_management(self):
        """Opens the entry management dialog for the SELECTED activity."""
        if self.current_activity_id is None:
            QMessageBox.warning(self, "Error", "Please select an activity in the tree first.")
            return
        dialog = EntryManagementDialog(self.current_activity_id, self.current_activity_name, self.db_manager, self)
        dialog.exec()
        if dialog.needs_update:
             print("Updating activity info after managing entries...")
             current = self.activity_tree.currentItem()
             if current: # Update the status bar text
                 self.activity_selected(current)

    def open_daily_snapshot(self):
        """Opens the 'Daily Snapshot' dialog."""
        dialog = DailySnapshotDialog(self.db_manager, self)
        dialog.exec()

    def toggle_timer(self):
        """Toggles the main timer (Work/Stop or Countdown/Stop)."""
        if self.work_timer_button.isChecked() and not self.qtimer.isActive():
             # Attempting to start
             if not self.current_activity_id:
                 QMessageBox.warning(self, "Error", "Please select an activity first.")
                 self.work_timer_button.setChecked(False) # Uncheck button
                 return
             # Start the 'work' timer (countdown is started by its own button)
             self.start_work_timer()
        elif not self.work_timer_button.isChecked() and self.qtimer.isActive():
             # Attempting to stop (button was unchecked by user click)
             self.stop_timer_logic()
        # else: # Cases where button state and timer state match (e.g., clicking "Start Tracking" when already active)
        #    Maybe do nothing, or ensure button state matches timer state
        #    self.work_timer_button.setChecked(self.qtimer.isActive()) # Sync button

    def start_work_timer(self):
        """Starts the 'Work' timer."""
        if self.timer_type is not None or not self.current_activity_id: return # Another timer running or no activity selected
        print(f"Starting 'Work' timer for: {self.current_activity_name} (ID: {self.current_activity_id})")
        self.timer_type = 'work'
        self.start_time = time.time()
        self.timer_window.set_overrun(False)
        self.qtimer.start(1000) # Update every second
        self.timer_window.setText("00:00:00")
        self.show_and_position_timer_window()
        self.work_timer_button.setText("Stop Tracking") # Change button text
        self.work_timer_button.setChecked(True) # Set state to "pressed"
        self.set_controls_enabled(False) # Lock activity controls
        self.status_label.setText(f"Working on: {self.current_activity_name}")

    def start_countdown_timer(self):
        """Starts the 'Countdown' timer based on the SELECTED activity's average time."""
        if not self.current_activity_id:
             QMessageBox.warning(self, "Error", "Please select an activity first."); return
        if self.qtimer.isActive():
             QMessageBox.warning(self, "Timer Active", "Another timer is already running."); return

        # Use average time *only* for the selected activity
        average_duration = self.db_manager.calculate_average_duration(self.current_activity_id)
        if average_duration <= 0:
             QMessageBox.information(self, "Information", f"No average time data for '{self.current_activity_name}'. Cannot start countdown."); return

        print(f"Starting 'Countdown' timer for: {self.current_activity_name} (ID: {self.current_activity_id}) from {average_duration:.0f} sec.")
        self.timer_type = 'countdown'
        self.countdown_average_duration = int(average_duration)
        self.average_duration_at_countdown_start = self.countdown_average_duration # Store the initial average
        self.start_time = time.time()
        self.timer_window.set_overrun(False)
        self.qtimer.start(1000)
        self.timer_window.setText(self.format_time(None, self.countdown_average_duration))
        self.show_and_position_timer_window()
        # The "Start Tracking" button now controls stopping this timer
        self.work_timer_button.setText("Stop Countdown")
        self.work_timer_button.setChecked(True)
        self.work_timer_button.setEnabled(True) # Must be enabled to stop
        self.set_controls_enabled(False) # Lock activity changing
        self.status_label.setText(f"Countdown: {self.current_activity_name} (from {self.format_time(None, self.countdown_average_duration)})")

    def stop_timer_logic(self):
        """Common logic for stopping any type of timer."""
        if not self.qtimer.isActive(): return # If timer isn't active, do nothing
        self.qtimer.stop()
        self.timer_window.hide()
        self.timer_window.set_overrun(False) # Reset background color
        stop_time = time.time()
        # Ensure start_time exists before calculating duration
        actual_duration = int(stop_time - self.start_time) if self.start_time else 0

        # Save state before resetting
        saved_activity_id = self.current_activity_id
        saved_activity_name = self.current_activity_name
        timer_stopped_type = self.timer_type
        avg_duration_at_start = self.average_duration_at_countdown_start # Use the saved value

        # Reset timer state
        self.timer_type = None
        self.start_time = None
        self.countdown_average_duration = 0
        self.average_duration_at_countdown_start = 0 # Reset saved average
        needs_ui_update = False # Flag if UI needs refresh (status bar)

        # Saving logic based on timer type
        if timer_stopped_type == 'work':
             if actual_duration > 0 and saved_activity_id is not None:
                 print(f"Work timer stopped. Duration: {actual_duration} sec for '{saved_activity_name}'.")
                 if self.db_manager.add_time_entry(saved_activity_id, actual_duration):
                     needs_ui_update = True # Need to update average/total time
             else:
                 print("Work timer stopped without saving (duration 0 or no activity selected).")
        elif timer_stopped_type == 'countdown':
             print(f"Countdown timer stopped. Duration: {actual_duration} sec for '{saved_activity_name}'.")
             if actual_duration > 0 and saved_activity_id is not None:
                 # Check if we should prompt to save the result
                 if self.check_and_prompt_save_countdown(actual_duration, saved_activity_id, saved_activity_name, avg_duration_at_start):
                     needs_ui_update = True # Saved, need to update UI
             else:
                  print("Countdown timer stopped without saving (duration 0 or no activity selected).")

        # Restore button states and controls
        self.work_timer_button.setText("Start Work") # Restore original text
        self.work_timer_button.setChecked(False)    # Uncheck the button
        self.set_controls_enabled(True) # Unlock activity controls (will trigger activity_selected)

        # Explicitly update selected activity status if data was saved
        if needs_ui_update:
             current = self.activity_tree.currentItem()
             if current:
                 # Re-select to refresh the status bar with new avg/total times
                 self.activity_selected(current)
             else:
                 # If nothing is selected after unlock, ensure status is correct
                 self.activity_selected(None)


    def check_and_prompt_save_countdown(self, actual_duration, activity_id, activity_name, average_duration_at_start):
        """Checks if the countdown time significantly differs from the average and prompts to save."""
        if actual_duration <= 0 or activity_id is None or average_duration_at_start <= 0:
            return False # Nothing to save or compare

        # Get entry count only for *this* activity
        entry_count = self.db_manager.get_entry_count(activity_id)

        # Suggest saving if enough entries exist AND the difference is significant
        if entry_count >= COUNTDOWN_MIN_ENTRIES_FOR_SAVE:
            # Avoid division by zero if average somehow is zero here
            if average_duration_at_start > 0:
                difference_ratio = abs(actual_duration - average_duration_at_start) / average_duration_at_start
            else:
                 difference_ratio = 1.0 # Treat as 100% difference if avg is 0

            if difference_ratio > COUNTDOWN_SAVE_THRESHOLD:
                percentage_diff = int(difference_ratio * 100)
                formatted_actual = self.format_time(None, actual_duration)
                formatted_average = self.format_time(None, average_duration_at_start)
                direction = 'more' if actual_duration > average_duration_at_start else 'less'

                reply = QMessageBox.question(
                    self, "Save Result?",
                    f"Countdown session for '{activity_name}' lasted {formatted_actual}, "
                    f"which is {percentage_diff}% {direction} than the planned average ({formatted_average}).\n\n"
                    f"Add {formatted_actual} as a new time entry for '{activity_name}'?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
                )

                if reply == QMessageBox.StandardButton.Yes:
                    print(f"Saving countdown result: {actual_duration} sec for ID {activity_id}.")
                    if self.db_manager.add_time_entry(activity_id, actual_duration):
                        return True # Successfully saved
                    else:
                        QMessageBox.warning(self, "Error", "Failed to save entry.")
                        return False # Error saving
        # Didn't prompt or user declined
        return False

    def update_timer(self):
        """Updates the time display in the timer window."""
        if self.start_time is None or self.timer_type is None:
            self.qtimer.stop() # Stop timer if state is inconsistent
            return

        elapsed = time.time() - self.start_time

        if self.timer_type == 'work':
            self.timer_window.setText(self.format_time(None, elapsed))
            # For work timer, background is always normal
            if self.timer_window.is_overrun:
                 self.timer_window.set_overrun(False)

        elif self.timer_type == 'countdown':
            remaining = self.countdown_average_duration - elapsed
            if remaining < 0:
                # Time's up, show overrun
                overrun_seconds = abs(remaining)
                self.timer_window.set_overrun(True, overrun_seconds)
                self.timer_window.setText(f"-{self.format_time(None, overrun_seconds)}")
            else:
                # Time still counting down
                self.timer_window.set_overrun(False)
                self.timer_window.setText(self.format_time(None, remaining))

    @staticmethod
    def format_time(instance_or_none, total_seconds):
        """Formats seconds into HH:MM:SS. Static method."""
        total_seconds = abs(int(total_seconds))
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02}:{m:02}:{s:02}"

    def set_controls_enabled(self, enabled):
        """Enables or disables controls when timer is active/inactive."""
        self.activity_tree.setEnabled(enabled)
        # Add/Manage buttons are now in context menu, so just enable/disable the tree itself

        if self.snapshot_button:
             self.snapshot_button.setEnabled(True) # Daily snapshot always available

        # Timer buttons and manage entries depend on activity selection,
        # their state will be updated by activity_selected() when enabled=True
        if enabled:
            # Call activity_selected to correctly update buttons and status bar
            current = self.activity_tree.currentItem()
            self.activity_selected(current) # Pass current selection
        else:
            # When timer is active (enabled=False)
            # The Start/Stop button must always be enabled to allow stopping
            self.work_timer_button.setEnabled(True)
            # The "Start Countdown" button is disabled while another timer runs
            self.countdown_timer_button.setEnabled(False)
            # The "Manage Entries" button is disabled
            if self.manage_entries_button:
                self.manage_entries_button.setEnabled(False)


    def show_and_position_timer_window(self):
        """Shows and positions the timer window in the corner of the screen."""
        self.timer_window.show()
        try:
            screen = QApplication.primaryScreen()
            if screen:
                sg = screen.availableGeometry()
                tw = self.timer_window.width()
                th = self.timer_window.height()
                margin = 20 # Margin from edge
                # Position top-right
                self.timer_window.move(QPoint(sg.right() - tw - margin, sg.top() + margin))
            else:
                print("Failed to get primary screen for timer positioning.")
        except Exception as e:
            print(f"Error positioning timer window: {e}")

    def closeEvent(self, event):
        """Handler for the main window close event."""
        if self.qtimer.isActive():
            reply = QMessageBox.question(
                self, "Timer Active",
                "The timer is still running. Stop the timer and exit?\n(Current progress will be saved if it's a 'Work' timer, or save prompted for 'Countdown' if applicable)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_timer_logic() # Stop and potentially save
            else:
                event.ignore() # Cancel window closing
                return

        # Close all resources
        self.db_manager.close()
        self.timer_window.close() # Close the small timer window
        print("Application closing.")
        event.accept() # Allow window closing

# --- Application Launch ---
if __name__ == '__main__':
    # Improve rendering on HiDPI displays (optional)
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())