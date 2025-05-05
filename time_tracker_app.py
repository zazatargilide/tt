import sys
import sqlite3
import time
import os
import math # <-- Added for drawing percentages
from collections import defaultdict, deque
# Import all necessary PyQt6 classes
from PyQt6.QtWidgets import (
    QMenu, QStyle, QSizePolicy, QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeWidgetItemIterator, QLineEdit, QLabel, QMessageBox, QListWidgetItem,
    QDialog, QDialogButtonBox, QInputDialog, QDateTimeEdit, QSpinBox, QCheckBox, QRadioButton,
    QDateEdit, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QTableView,
    QTreeWidget, QTreeWidgetItem, QMenu, QAbstractItemView, QStyledItemDelegate, QStyleOptionViewItem,
    QDoubleSpinBox, QFormLayout
)
from PyQt6.QtCore import (Qt, QRect, QSize, QPointF, QTimer, QAbstractTableModel, QModelIndex, QDate, QVariant,
pyqtSignal, QTimer, QRectF, QPoint, QDateTime, QLocale
)
from PyQt6.QtGui import QPainter, QPainterPath, QFontMetrics, QColor, QBrush, QPen, QFont, QPalette, QLinearGradient, QAction , QIcon
# --- Constants ---
DATABASE_NAME = 'time_tracker.db'
COUNTDOWN_SAVE_THRESHOLD = 0.10  # 10% OVERRUN to suggest saving
COUNTDOWN_MIN_ENTRIES_FOR_SAVE = 1 # Minimum number of entries to suggest saving
MAX_OVERRUN_SECONDS_FOR_RED = 60 # Seconds of overrun for maximum redness (60 seconds)

# Habit Types Enum (using constants for clarity)
HABIT_TYPE_NONE = 0
HABIT_TYPE_BINARY = 1
HABIT_TYPE_PERCENTAGE = 2
HABIT_TYPE_NUMERIC = 3

# Custom Data Roles for Habit Grid Items
HABIT_VALUE_ROLE = Qt.ItemDataRole.UserRole + 0
HABIT_TYPE_ROLE = Qt.ItemDataRole.UserRole + 1
HABIT_UNIT_ROLE = Qt.ItemDataRole.UserRole + 2
HABIT_DATE_ROLE = Qt.ItemDataRole.UserRole + 3
HABIT_ACTIVITY_ID_ROLE = Qt.ItemDataRole.UserRole + 4
HABIT_GOAL_ROLE = Qt.ItemDataRole.UserRole + 5 # Or next available UserRole + N

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

    def _add_column_if_not_exists(self, table_name, column_name, column_def):
        """Helper to add a column if it doesn't exist."""
        if not self.conn: return
        try:
            self.cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [info[1] for info in self.cursor.fetchall()]
            if column_name not in columns:
                print(f"Adding column '{column_name}' to table '{table_name}'...")
                self.cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
                self.conn.commit()
                print(f"Column '{column_name}' added.")
        except sqlite3.Error as e:
            print(f"Error checking/adding column {column_name} to {table_name}: {e}")
            self.conn.rollback()

    def get_habit_logs_for_date_range(self, start_date_str, end_date_str):
        """Gets all habit logs within a date range."""
        if not self.conn: return {}
        logs = {} # Format: {(activity_id, date_str): value}
        try:
            # Fetch logs between the start and end dates (inclusive)
            self.cursor.execute(
                "SELECT activity_id, log_date, value FROM habit_logs WHERE log_date BETWEEN ? AND ?",
                (start_date_str, end_date_str)
            )
            for row in self.cursor.fetchall():
                logs[(row[0], row[1])] = row[2]
            print(f"DB Manager: Fetched {len(logs)} logs between {start_date_str} and {end_date_str}")
            return logs
        except sqlite3.Error as e:
            print(f"Error retrieving habit logs for range {start_date_str} - {end_date_str}: {e}")
            return {}

    def _create_tables(self):
        if not self.conn: return
        try:
            # Activities table - Add habit_goal
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    parent_id INTEGER DEFAULT NULL,
                    habit_type INTEGER DEFAULT NULL, -- NULL/0: Not habit, 1: Binary, 2: Percentage, 3: Numeric
                    habit_unit TEXT DEFAULT NULL, -- Unit for Numeric type (e.g., 'pages', 'km', 'minutes')
                    habit_sort_order INTEGER,
                    habit_goal REAL DEFAULT NULL, -- <<< NEW COLUMN for daily goal (numeric habits)
                    FOREIGN KEY (parent_id) REFERENCES activities (id) ON DELETE SET NULL
                )
            ''')
            # Add columns if they don't exist (for existing databases)
            self._add_column_if_not_exists('activities', 'habit_type', 'INTEGER DEFAULT NULL')
            self._add_column_if_not_exists('activities', 'habit_unit', 'TEXT DEFAULT NULL')
            self._add_column_if_not_exists('activities', 'habit_sort_order', 'INTEGER')
            self._add_column_if_not_exists('activities', 'habit_goal', 'REAL DEFAULT NULL') # <<< ADD CHECK

            # Time Entries Table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS time_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_id INTEGER NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (activity_id) REFERENCES activities (id) ON DELETE CASCADE
                )
            ''')

            # Habit Logs Table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS habit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_id INTEGER NOT NULL,
                    log_date TEXT NOT NULL, -- Store as 'YYYY-MM-DD' string
                    value REAL, -- Flexible: 1.0 for Binary Done, 0/25/50/75/100 for Percentage, numeric value otherwise. NULL = no entry.
                    UNIQUE(activity_id, log_date),
                    FOREIGN KEY (activity_id) REFERENCES activities (id) ON DELETE CASCADE
                )
            ''')

            # Indexes
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_parent_id ON activities (parent_id);')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_habit_type ON activities (habit_type);')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_habit_sort_order ON activities (habit_sort_order);') # NEW INDEX
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_id_timestamp ON time_entries (activity_id, timestamp);')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp_date ON time_entries (timestamp);')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_habit_logs_date_activity ON habit_logs (log_date, activity_id);')

            self.conn.commit()
            print("Tables checked/created/updated.")
            self._initialize_habit_order()

        except sqlite3.Error as e:
            print(f"Error creating/updating tables: {e}")

    def _initialize_habit_order(self):
        """Sets initial sort order for habits that don't have one yet."""
        if not self.conn: return
        try:
            # Find max existing order, or start from 0
            self.cursor.execute("SELECT MAX(habit_sort_order) FROM activities WHERE habit_sort_order IS NOT NULL")
            max_order_result = self.cursor.fetchone()
            max_order = max_order_result[0] if max_order_result else None
            next_order = 0 if max_order is None else max_order + 1

            # Find habits with NULL order
            self.cursor.execute("SELECT id FROM activities WHERE habit_type IS NOT NULL AND habit_sort_order IS NULL ORDER BY id ASC")
            habits_to_order = self.cursor.fetchall()

            if habits_to_order:
                 print(f"Initializing sort order for {len(habits_to_order)} habits...")
                 for habit_id_tuple in habits_to_order:
                     habit_id = habit_id_tuple[0]
                     self.cursor.execute("UPDATE activities SET habit_sort_order = ? WHERE id = ?", (next_order, habit_id))
                     print(f"  Set order {next_order} for activity ID {habit_id}")
                     next_order += 1
                 self.conn.commit()
                 print("Habit order initialization complete.")

        except sqlite3.Error as e:
            print(f"Error initializing habit sort order: {e}")
            self.conn.rollback()

    def _check_activity_name_exists(self, name, parent_id):
        """Checks if an activity with this name exists under the same parent."""
        if not self.conn: return True
        try:
            if parent_id is None:
                self.cursor.execute("SELECT 1 FROM activities WHERE name = ? AND parent_id IS NULL", (name,))
            else:
                self.cursor.execute("SELECT 1 FROM activities WHERE name = ? AND parent_id = ?", (name, parent_id))
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            print(f"Error checking activity name: {e}")
            return True

    def add_activity(self, name, parent_id=None):
        """Adds an activity, optionally specifying a parent."""
        if not self.conn or not name: return None
        name = name.strip()
        if not name: return None

        if self._check_activity_name_exists(name, parent_id):
             print(f"Activity '{name}' already exists with the same parent (parent_id: {parent_id}).")
             QMessageBox.warning(None, "Duplicate", f"An activity named '{name}' already exists in this branch.")
             return None

        try:
            # Insert with default NULL for habit columns
            self.cursor.execute("INSERT INTO activities (name, parent_id) VALUES (?, ?)", (name, parent_id))
            self.conn.commit()
            new_id = self.cursor.lastrowid
            print(f"Activity '{name}' (ID: {new_id}, parent_id: {parent_id}) added.")
            return new_id
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
        """Builds the activity hierarchy, including habit info."""
        if not self.conn: return {}
        try:
            # Fetch all relevant columns
            self.cursor.execute("SELECT id, name, parent_id, habit_type, habit_unit FROM activities")
            activities_raw = self.cursor.fetchall()
            activities_dict = {
                act_id: {
                    'id': act_id, 'name': name, 'parent_id': parent_id,
                    'habit_type': habit_type, 'habit_unit': habit_unit, 'children': []
                } for act_id, name, parent_id, habit_type, habit_unit in activities_raw
            }
            top_level = []
            for act_id, data in activities_dict.items():
                parent_id = data['parent_id']
                if parent_id is None: top_level.append(data)
                elif parent_id in activities_dict: activities_dict[parent_id]['children'].append(data)
                else:
                    print(f"Warning: Parent ID {parent_id} for activity ID {act_id} not found.")
                    top_level.append(data)

            def sort_children_recursive(nodes):
                nodes.sort(key=lambda x: x['name'])
                for node in nodes:
                    if node['children']: sort_children_recursive(node['children'])
            sort_children_recursive(top_level)
            return top_level
        except sqlite3.Error as e:
            print(f"Error retrieving activity hierarchy: {e}")
            return []

    def get_descendant_activity_ids(self, activity_id):
        """Returns a set of IDs of all descendant activities."""
        if not self.conn or activity_id is None: return set()
        descendants = set()
        queue = deque([activity_id])
        while queue:
            current_id = queue.popleft()
            if current_id is None or current_id in descendants: continue
            descendants.add(current_id)
            try:
                self.cursor.execute("SELECT id FROM activities WHERE parent_id = ?", (current_id,))
                for child_id_tuple in self.cursor.fetchall():
                    if child_id_tuple[0] not in descendants: queue.append(child_id_tuple[0])
            except sqlite3.Error as e: print(f"Error finding descendants for ID {current_id}: {e}")
        return descendants

    def add_time_entry(self, activity_id, duration_seconds, timestamp=None):
        """Добавляет запись времени. Можно указать конкретный timestamp (всегда сохраняет как UTC)."""
        if not self.conn or not activity_id or duration_seconds <= 0: return False
        duration_seconds = int(duration_seconds)
        try:
            ts_str_for_db = None
            if timestamp:
                # timestamp здесь - это локальный QDateTime из QDateTimeEdit
                if not isinstance(timestamp, QDateTime):
                     # Попытка преобразовать, если это не QDateTime (маловероятно)
                     try:
                         timestamp = QDateTime.fromString(str(timestamp), "yyyy-MM-dd HH:mm:ss")
                     except Exception:
                         print("Предупреждение: Не удалось распознать переданный timestamp, используется CURRENT_TIMESTAMP.")
                         timestamp = None # Сбрасываем, чтобы использовать CURRENT_TIMESTAMP

                if timestamp and timestamp.isValid():
                    # --- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Конвертируем локальное время в UTC ---
                    utc_dt = timestamp.toUTC()
                    # --- КОНЕЦ ИЗМЕНЕНИЯ ---
                    ts_str_for_db = utc_dt.toString("yyyy-MM-dd HH:mm:ss") # Форматируем UTC время для БД

            if ts_str_for_db: # Если был передан корректный timestamp
                self.cursor.execute(
                    "INSERT INTO time_entries (activity_id, duration_seconds, timestamp) VALUES (?, ?, ?)",
                    (activity_id, duration_seconds, ts_str_for_db) # Вставляем строку UTC
                )
                ts_info = f"с timestamp (UTC) {ts_str_for_db}"
            else: # Если timestamp не был передан или был некорректным
                # Используем DEFAULT CURRENT_TIMESTAMP базы данных (который обычно UTC)
                self.cursor.execute(
                    "INSERT INTO time_entries (activity_id, duration_seconds) VALUES (?, ?)",
                    (activity_id, duration_seconds)
                )
                ts_info = "с текущим timestamp (UTC по умолчанию)"

            self.conn.commit()
            print(f"Запись времени ({duration_seconds} сек) добавлена для activity_id {activity_id} {ts_info}.")
            return True
        except sqlite3.Error as e:
            print(f"Ошибка добавления записи времени: {e}")
            # Полезно добавить откат транзакции в случае ошибки
            if self.conn:
                try:
                    self.conn.rollback()
                except sqlite3.Error as rb_err:
                    print(f"Ошибка при откате транзакции: {rb_err}")
            return False
        
    def get_durations(self, activity_id):
        """Gets durations only for *this* specific activity."""
        if not self.conn or not activity_id: return []
        try:
            self.cursor.execute("SELECT duration_seconds FROM time_entries WHERE activity_id = ?", (activity_id,))
            return [row[0] for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Error retrieving durations: {e}")
            return []

    def calculate_total_duration_for_activity_branch(self, activity_id):
        """Calculates the *total* duration for an activity and all its descendants."""
        if not self.conn or not activity_id: return 0
        descendant_ids = self.get_descendant_activity_ids(activity_id)
        if not descendant_ids: return 0
        try:
            placeholders = ', '.join('?' * len(descendant_ids))
            query = f"SELECT SUM(duration_seconds) FROM time_entries WHERE activity_id IN ({placeholders})"
            self.cursor.execute(query, list(descendant_ids))
            result = self.cursor.fetchone()
            return result[0] if result and result[0] is not None else 0
        except sqlite3.Error as e:
            print(f"Error calculating total duration for branch {activity_id}: {e}")
            return 0

    def calculate_average_duration(self, activity_id):
        """Calculates the average duration for *this* specific activity."""
        durations = self.get_durations(activity_id)
        return sum(durations) / len(durations) if durations else 0

    def get_entry_count(self, activity_id):
        """Gets the number of time entries for *this* specific activity."""
        if not self.conn or not activity_id: return 0
        try:
            self.cursor.execute("SELECT COUNT(*) FROM time_entries WHERE activity_id = ?", (activity_id,))
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
                (activity_id,))
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Error retrieving time entries: {e}")
            return []

    def update_time_entry(self, entry_id, new_duration_seconds):
        """Updates the duration of an existing time entry."""
        if not self.conn or not entry_id or new_duration_seconds <= 0: return False
        try:
            self.cursor.execute("UPDATE time_entries SET duration_seconds = ? WHERE id = ?", (int(new_duration_seconds), entry_id))
            self.conn.commit()
            if self.cursor.rowcount > 0:
                print(f"Time entry ID {entry_id} updated. New duration: {int(new_duration_seconds)} sec.")
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
        """Gets all time entries for the specified date (YYYY-MM-DD)."""
        if not self.conn or not date_str: return []
        try:
            self.cursor.execute("""
                SELECT a.id, a.name, te.duration_seconds, strftime('%Y-%m-%d %H:%M:%S', te.timestamp) as timestamp_str
                FROM time_entries te JOIN activities a ON te.activity_id = a.id
                WHERE DATE(te.timestamp) = ? ORDER BY te.timestamp ASC """, (date_str,))
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
             self.cursor.execute("SELECT id FROM activities WHERE name = ? AND (parent_id = ? OR (parent_id IS NULL AND ? IS NULL))", (new_name, parent_id, parent_id))
             existing = self.cursor.fetchone()
             if existing and existing[0] != activity_id:
                 print(f"Cannot rename: Activity '{new_name}' already exists.")
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
        """Deletes an activity and all its descendants (CASCADE handles related)."""
        if not self.conn or not activity_id: return False
        descendant_ids = self.get_descendant_activity_ids(activity_id)
        if not descendant_ids:
             print(f"Failed to get descendants for deleting activity ID {activity_id}.")
             return False
        try:
            placeholders = ', '.join('?' * len(descendant_ids))
            self.cursor.execute(f"DELETE FROM activities WHERE id IN ({placeholders})", list(descendant_ids))
            deleted_count = self.cursor.rowcount
            self.conn.commit()
            print(f"Activity ID {activity_id} and descendants deleted ({deleted_count} total).")
            return True
        except sqlite3.Error as e:
            print(f"Error deleting activity and descendants: {e}")
            self.conn.rollback()
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

    def set_activity_habit_config(self, activity_id, habit_type, habit_unit=None, habit_goal=None): # Add habit_goal parameter
        """Sets or clears habit configuration for an activity, including goal and initial sort order."""
        if not self.conn or activity_id is None: return False
        current_type, _, _ = self.get_activity_habit_config(activity_id) # Fetch current goal too
        is_newly_enabled = (current_type is None or current_type == HABIT_TYPE_NONE) and \
                           (habit_type is not None and habit_type != HABIT_TYPE_NONE)

        sort_order_sql = "" # Only update sort order if newly enabled
        final_habit_goal = None # Default goal to NULL

        if habit_type not in [HABIT_TYPE_BINARY, HABIT_TYPE_PERCENTAGE, HABIT_TYPE_NUMERIC]:
            # Clear all habit info if invalid type or disabling
            update_sql = "UPDATE activities SET habit_type = NULL, habit_unit = NULL, habit_sort_order = NULL, habit_goal = NULL WHERE id = ?"
            params = (activity_id,)
        else:
            # Set habit info
            if habit_type != HABIT_TYPE_NUMERIC:
                habit_unit = None # Clear unit if not numeric
                habit_goal = None # Clear goal if not numeric
            elif habit_unit is not None:
                habit_unit = habit_unit.strip() or None
            # Validate and set goal only for numeric
            if habit_type == HABIT_TYPE_NUMERIC and habit_goal is not None:
                 try:
                     goal_val = float(habit_goal)
                     final_habit_goal = goal_val if goal_val > 0 else None # Store only positive goals
                 except (ValueError, TypeError):
                     final_habit_goal = None # Invalid goal becomes NULL
            else:
                 final_habit_goal = None # Not numeric or no goal provided


            if is_newly_enabled:
                # Calculate next sort order
                self.cursor.execute("SELECT MAX(habit_sort_order) FROM activities WHERE habit_sort_order IS NOT NULL")
                max_order_result = self.cursor.fetchone()
                max_order = max_order_result[0] if max_order_result and max_order_result[0] is not None else -1 # Handle NULL/no rows
                sort_order = max_order + 1
                sort_order_sql = ", habit_sort_order = ?" # Add sort order to UPDATE
                print(f"Assigning initial sort order {sort_order} to new habit ID {activity_id}")
                params = (habit_type, habit_unit, final_habit_goal, sort_order, activity_id) # Add sort_order param
            else:
                # Modifying existing habit (type/unit/goal only)
                params = (habit_type, habit_unit, final_habit_goal, activity_id) # No sort order param

            update_sql = f"UPDATE activities SET habit_type = ?, habit_unit = ?, habit_goal = ?{sort_order_sql} WHERE id = ?"

        try:
            print(f"Executing SQL: {update_sql} with params {params}")
            self.cursor.execute(update_sql, params)
            self.conn.commit()
            print(f"Habit config updated for activity {activity_id}. Rows affected: {self.cursor.rowcount}")
            return self.cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Error updating habit config for activity {activity_id}: {e}")
            self.conn.rollback()
            return False

    def get_activity_habit_config(self, activity_id):
        """Gets the habit configuration (type, unit, goal) for a given activity."""
        if not self.conn or not activity_id: return (None, None, None) # Return tuple of 3
        try:
            # Select the new habit_goal column
            self.cursor.execute("SELECT habit_type, habit_unit, habit_goal FROM activities WHERE id = ?", (activity_id,))
            result = self.cursor.fetchone()
            # Return type, unit, goal
            return (result[0], result[1], result[2]) if result else (None, None, None)
        except sqlite3.Error as e:
            print(f"Error retrieving habit config for activity {activity_id}: {e}")
            return (None, None, None)

    def get_all_habits(self):
        """Gets a list of all configured habits (id, name, type, unit, goal), ORDERED by sort order."""
        if not self.conn: return []
        try:
            self.cursor.execute(
                # Select the new habit_goal column
                "SELECT id, name, habit_type, habit_unit, habit_goal FROM activities "
                "WHERE habit_type IS NOT NULL ORDER BY habit_sort_order ASC, name ASC"
            )
            # Returns list of tuples: [(id, name, type, unit, goal), ...]
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Error retrieving all habits: {e}")
            return []


    def log_habit(self, activity_id, date_str, value):
        """Logs or updates a habit entry for a specific date using UPSERT logic."""
        if not self.conn or activity_id is None or not date_str: return False
        try: QDate.fromString(date_str, "yyyy-MM-dd") # Basic date validation
        except ValueError: print(f"Error: Invalid date format '{date_str}'."); return False
        try:
            if value is None:
                 self.cursor.execute("DELETE FROM habit_logs WHERE activity_id = ? AND log_date = ?", (activity_id, date_str))
                 print(f"Habit log deleted for Activity ID {activity_id} on {date_str}")
            else:
                 self.cursor.execute("INSERT OR REPLACE INTO habit_logs (activity_id, log_date, value) VALUES (?, ?, ?)",
                                     (activity_id, date_str, float(value)))
                 print(f"Habit logged for Activity ID {activity_id} on {date_str} with value {value}")
            self.conn.commit(); return True
        except sqlite3.Error as e:
            print(f"Error logging habit for activity {activity_id} on {date_str}: {e}")
            self.conn.rollback(); return False

    def get_habit_logs_for_month(self, year, month):
        """Gets all habit logs for a given year and month."""
        if not self.conn: return {}
        month_pattern = f"{year:04d}-{month:02d}-%"
        try:
            self.cursor.execute("SELECT activity_id, log_date, value FROM habit_logs WHERE log_date LIKE ?", (month_pattern,))
            return {(row[0], row[1]): row[2] for row in self.cursor.fetchall()}
        except sqlite3.Error as e:
            print(f"Error retrieving habit logs for {year}-{month}: {e}")
            return {}

    def update_habit_order(self, ordered_activity_ids):
        """Updates the habit_sort_order for a list of activity IDs."""
        if not self.conn or not ordered_activity_ids: return False
        try:
            print(f"Updating habit order for {len(ordered_activity_ids)} items...")
            self.cursor.execute("BEGIN TRANSACTION")
            for index, activity_id in enumerate(ordered_activity_ids):
                 self.cursor.execute("UPDATE activities SET habit_sort_order = ? WHERE id = ?", (index, activity_id))
            self.cursor.execute("COMMIT TRANSACTION")
            print("Habit order updated successfully."); return True
        except sqlite3.Error as e:
            print(f"Error updating habit order: {e}")
            self.cursor.execute("ROLLBACK TRANSACTION"); return False

    def close(self):
        if self.conn:
            self.conn.close()
            print("Database disconnected.")
# --- End of DatabaseManager Class ---

# =============================================================
# ОПТИМИЗИРОВАННЫЙ HeatmapWidget
# =============================================================

class HeatmapWidget(QWidget):
    """
    Displays a heatmap of habit completion for a year.
    Includes aligned weekday labels and day numbers within cells.
    Day number font is black on gradient background, no outline.
    """
    def _calculate_minimum_size(self):
        """Calculates the minimum required size based on cells and labels."""
        # Ensure consistent rounding/casting to int for QSize
        width = int(self.weekday_label_width + 53 * (self.cell_size + self.cell_spacing) + self.cell_spacing)
        height = int(self.month_label_height + 7 * (self.cell_size + self.cell_spacing) + self.cell_spacing)
        return QSize(width, height)

    def __init__(self, db_manager: 'DatabaseManager', parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.year = QDate.currentDate().year()
        self.daily_done_counts = defaultdict(int) # {QDate: count}
        self.max_done_count = 1 # Not currently used for coloring, but kept
        self.habit_configs = {} # {activity_id: (type, unit, goal)}

        # --- Heatmap Appearance ---
        self.cell_size = 16
        self.cell_spacing = 3
        self.cell_radius = 3
        self.month_label_height = 20
        self.weekday_label_width = 30
        # self.heatmap_color = QColor(0, 100, 255) # Base color (Overridden by gradient)
        self.day_number_font_size = 7 # Font size for day number inside cell

        self.start_date = QDate(self.year, 1, 1)
        self.end_date = QDate(self.year, 12, 31)

        # --- Precalculated Layout Data ---
        self._cell_rects = {} # {QDate: QRectF} Store calculated cell positions
        self._month_labels = [] # List of (QPointF, str) for month label positions/text
        self._weekday_labels = [] # List of (QPointF, str) for weekday label positions/text
        self._needs_layout_update = True # Flag to recalculate geometry on resize/show

        # --- Animation Timer ---
        self.heatmap_animation_timer = QTimer(self)
        self.heatmap_animation_timer.timeout.connect(self.update) # Trigger repaint for animation
        # Timer started in showEvent

        self.setMinimumSize(self._calculate_minimum_size())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed) # Expands horizontally
        self.load_data() # Load data initially

    # --- Simplified drawing function (NO OUTLINE) ---
    def drawOutlinedText(self, painter: QPainter, rect: QRectF, flags: int,
                         text: str, text_color: QColor, font: QFont = None):
        """Draws text directly without any outline or shadow."""
        painter.save()
        if font:
            painter.setFont(font)

        alignment = Qt.AlignmentFlag(flags) # Ensure it's the correct type

        # Set the pen to the desired text color
        painter.setPen(text_color)

        # Draw the text directly using the provided rectangle and alignment
        painter.drawText(rect, alignment, text)

        painter.restore()
    # --- End drawing function ---

# Внутри класса HeatmapWidget:

    # --- Layout Calculation ---
    def _calculate_layout(self):
        """Calculates positions for cells and labels based on current widget size."""
        print("Recalculating heatmap layout...") # Добавим отладочный вывод
        self._cell_rects = {}
        self._month_labels = []
        self._weekday_labels = [] # Очищаем список перед заполнением

        widget_rect = self.rect()
        base_font = self.font()

        # --- Calculate Month Labels (No changes needed here) ---
        month_font = QFont(base_font); month_font.setBold(True)
        fm_month = QFontMetrics(month_font)
        current_month = -1
        first_day_of_year = QDate(self.year, 1, 1)
        for week in range(53):
            x_pos_start_of_week = self.weekday_label_width + week * (self.cell_size + self.cell_spacing) + self.cell_spacing
            first_day_of_year_weekday = first_day_of_year.dayOfWeek()
            days_offset = week * 7 - (first_day_of_year_weekday - 1)
            date_in_week = first_day_of_year.addDays(days_offset)

            if date_in_week.year() == self.year:
                month_of_week = date_in_week.month()
                if month_of_week != current_month:
                    month_text = QLocale().monthName(month_of_week, QLocale.FormatType.ShortFormat)
                    text_width = fm_month.horizontalAdvance(month_text)
                    if x_pos_start_of_week + text_width < widget_rect.width() - self.cell_spacing:
                        label_pos = QPointF(x_pos_start_of_week, fm_month.ascent() + 2.0)
                        self._month_labels.append((label_pos, month_text))
                    current_month = month_of_week

        # --- Calculate Weekday Labels (Show ALL 7 days using QLocale) ---
        start_y_week = float(self.month_label_height + self.cell_spacing)
        fm_weekday = QFontMetrics(base_font)
        text_height = fm_weekday.height()
        locale = QLocale() # Get default locale for day names
        print(f"Using locale: {locale.language()}, {locale.country()}") # Отладка локали

        for i in range(7): # Наш индекс цикла i = 0..6 соответствует строкам Пн..Вс
            qt_day_of_week = i + 1 # Конвертируем индекс 0..6 в номер дня Qt 1..7
            # Получаем стандартное короткое имя (например, "Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс" для русского)
            label_text = locale.dayName(qt_day_of_week, QLocale.FormatType.ShortFormat)

            # --- Опционально: Использовать одну букву, если "Пн", "Вт" и т.д. слишком широкие ---
            # Раскомментируйте одну из строк ниже, если стандартные короткие имена не помещаются
            # label_text = locale.dayName(qt_day_of_week, QLocale.FormatType.NarrowFormat) # Может дать "П", "В", "С" и т.д. (зависит от локали)
            # Или определить вручную (не зависит от локали):
            # single_letter_days = ["ᛗ", "ᛏ", "ᛟ", "ᚦ", "ᚠ", "ᛚ", "ᛋ"] # Пн -> Вс
            # label_text = single_letter_days[i]
            # --- Конец опциональной части ---

            # Рассчитываем вертикальный центр строки i-ой ячейки
            cell_center_y = start_y_week + i * (self.cell_size + self.cell_spacing) + self.cell_size / 2.0
            # Позиционируем базовую линию текста так, чтобы он выглядел выровненным по вертикали
            y_pos = cell_center_y + fm_weekday.ascent() / 2.0 - fm_weekday.descent() / 1.5 # Тонкая настройка смещения

            # Рассчитываем горизонтальную позицию - выравниваем по левому краю
            x_pos = float(self.cell_spacing)

            label_pos = QPointF(x_pos, y_pos)
            # Добавляем информацию о метке для КАЖДОГО дня в список (убрана проверка на пустую строку)
            self._weekday_labels.append((label_pos, label_text))
        # --- End Weekday Label Calculation ---

        # --- ОТЛАДКА: Выведем содержимое списка меток дней недели ---
        print(f"Calculated weekday labels: {self._weekday_labels}")
        # --- КОНЕЦ ОТЛАДКИ ---

        # --- Calculate Day Cell Rects (No changes needed here) ---
        start_x = float(self.weekday_label_width + self.cell_spacing)
        start_y = float(self.month_label_height + self.cell_spacing)
        current_date = self.start_date
        while current_date <= self.end_date:
            day_of_week_index = current_date.dayOfWeek() - 1 # 0 to 6
            first_day_weekday = self.start_date.dayOfWeek()
            col = (current_date.dayOfYear() + first_day_weekday - 2) // 7
            row = day_of_week_index

            x = start_x + col * (self.cell_size + self.cell_spacing)
            y = start_y + row * (self.cell_size + self.cell_spacing)
            self._cell_rects[current_date] = QRectF(x, y, float(self.cell_size), float(self.cell_size))
            current_date = current_date.addDays(1)

        self._needs_layout_update = False
        print("Heatmap layout recalculation finished.")
    def resizeEvent(self, event):
        """Mark layout as needing update on resize."""
        self._needs_layout_update = True
        super().resizeEvent(event)
        self.update() # Trigger repaint after resize

    # --- Data Handling ---
    def _calculate_minimum_size(self):
         width = self.weekday_label_width + 53 * (self.cell_size + self.cell_spacing) + self.cell_spacing
         height = self.month_label_height + 7 * (self.cell_size + self.cell_spacing) + self.cell_spacing
         return QSize(int(width), int(height))

    def minimumSizeHint(self) -> QSize: return self._calculate_minimum_size()
    def sizeHint(self) -> QSize: return self._calculate_minimum_size()

    def refresh_data(self):
        print("HeatmapWidget: Refreshing data...")
        self.load_data()
        self.update()

    def load_data(self):
        """Loads habit configurations and logs for the current year."""
        print(f"HeatmapWidget: Loading data for year {self.year}...")
        habits_raw = self.db_manager.get_all_habits()
        self.habit_configs = {h[0]: (h[2], h[3], h[4]) for h in habits_raw} # id -> (type, unit, goal)
        if not self.habit_configs:
             print("HeatmapWidget: No habits configured.")
             self.daily_done_counts={}
             self.max_done_count=1
             self._needs_layout_update = True # Need layout even if empty
             return

        # Fetch all logs for the entire year for efficiency
        logs = self.db_manager.get_habit_logs_for_date_range(
             self.start_date.toString("yyyy-MM-dd"), self.end_date.toString("yyyy-MM-dd"))

        self._calculate_daily_done_counts(logs)
        print(f"HeatmapWidget: Data loaded. Calculated done counts for {len(self.daily_done_counts)} days.")
        self._needs_layout_update = True # Recalculate layout after data load

    def _is_habit_done(self, activity_id, value):
        """Checks if a specific habit is considered 'done' based on its type, goal, and logged value."""
        if value is None: return False
        if activity_id not in self.habit_configs: return False
        habit_type, _, habit_goal = self.habit_configs[activity_id]

        if habit_type == HABIT_TYPE_BINARY: return value == 1.0
        elif habit_type == HABIT_TYPE_PERCENTAGE: return value >= 100.0
        elif habit_type == HABIT_TYPE_NUMERIC:
            # Done if a positive goal exists and the value meets or exceeds it
            return habit_goal is not None and habit_goal > 0 and value >= habit_goal
        else: return False # Unknown type or not a habit

    def _calculate_daily_done_counts(self, logs):
        """Calculates how many habits were 'done' for each day of the year."""
        self.daily_done_counts = defaultdict(int)
        temp_max_done = 0
        current_date = self.start_date
        today = QDate.currentDate()

        while current_date <= self.end_date:
            date_str = current_date.toString("yyyy-MM-dd")
            done_count_for_day = 0
            for habit_id in self.habit_configs.keys():
                 log_value = logs.get((habit_id, date_str)) # Get log for this habit/date
                 if self._is_habit_done(habit_id, log_value):
                     done_count_for_day += 1

            # Store count only if > 0 to keep dict smaller, or store 0s too?
            # Storing only > 0 is fine as .get(date, 0) handles missing keys later.
            if done_count_for_day > 0:
                 self.daily_done_counts[current_date] = done_count_for_day
                 # Track max done count only for past/present days for gradient scaling (optional)
                 if current_date <= today:
                     temp_max_done = max(temp_max_done, done_count_for_day)

            current_date = current_date.addDays(1)
        # self.max_done_count = max(1, temp_max_done) # Not used currently, but available


    # --- Main Painting Logic ---
    def paintEvent(self, event):
        """Draw the heatmap with animated gradient and day numbers."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._needs_layout_update or not self._cell_rects:
            self._calculate_layout()

        today = QDate.currentDate()
        palette = self.palette() # Get current theme palette

        # --- Define Colors (adapt better to theme) ---
        outline_future_color = palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Window).lighter(115)
        outline_past_color = palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Mid) # Slightly darker outline
        base_past_color = palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Base) # Background for 0 done days
        month_label_color = palette.color(QPalette.ColorRole.Text)
        weekday_label_color = palette.color(QPalette.ColorRole.Text)
        # Color for text when background is the plain base_past_color
        text_color_not_done = palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.WindowText) # Should contrast with Base

        # --- Draw Month Labels ---
        painter.setPen(month_label_color)
        month_font = QFont(self.font()); month_font.setBold(True); painter.setFont(month_font)
        for pos, text in self._month_labels:
             painter.drawText(pos, text)
        painter.setFont(self.font()) # Restore default font

        # --- Draw Weekday Labels ---
        painter.setPen(weekday_label_color)
        for pos, text in self._weekday_labels:
             painter.drawText(pos, text)

        # --- Draw Day Cells ---
        current_time = time.time()
        day_font = QFont(self.font())
        day_font.setPointSize(self.day_number_font_size)

        for date, cell_rect in self._cell_rects.items():
            if not cell_rect: continue

            path = QPainterPath()
            path.addRoundedRect(cell_rect, self.cell_radius, self.cell_radius)

            # --- Drawing Logic based on Date ---
            if date > today:
                # Future date: Faint outline only for the cell
                painter.setPen(QPen(outline_future_color, 0.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
            else:
                # Past or today: Fill based on done_count + Draw Day Number
                done_count = self.daily_done_counts.get(date, 0) # Default to 0 if no entry
                painter.setPen(QPen(outline_past_color, 0.5)) # Cell outline for past days

                # --- Determine Background and Text Color ---
                if done_count == 0:
                    # Not Done: Use theme's default text color for this background
                    day_number_text_color = text_color_not_done

                    # Draw background for 0 done
                    painter.setBrush(base_past_color)
                    painter.drawPath(path)
                else:
                    # Done (Gradient Background): Force text color to BLACK
                    day_number_text_color = Qt.GlobalColor.black # <<< FORCED BLACK FONT

                    # --- Gradient Calculation ---
                    total_habits = len(self.habit_configs) if self.habit_configs else 1
                    percentage_done = min(done_count / total_habits, 1.0) if total_habits > 0 else 0.0
                    hue1 = int(current_time * 150) % 360
                    hue2 = (hue1 + 40) % 360
                    # Adjust saturation/lightness based on percentage
                    # Lower base saturation/lightness might look better with black text
                    base_saturation = 80
                    base_lightness = 210 # Make base lighter
                    saturation = base_saturation + int(percentage_done * 150) # e.g., 80 -> 230
                    lightness = base_lightness - int(percentage_done * 50)  # e.g., 210 -> 160
                    saturation = max(0, min(255, saturation))
                    lightness = max(0, min(255, lightness))
                    color1 = QColor.fromHsl(hue1, saturation, lightness)
                    color2 = QColor.fromHsl(hue2, saturation, lightness)
                    gradient = QLinearGradient(cell_rect.topLeft(), cell_rect.bottomRight())
                    gradient.setColorAt(0, color1); gradient.setColorAt(1, color2)
                    # --- End Gradient Calculation ---

                    # Draw gradient background
                    painter.setBrush(QBrush(gradient))
                    painter.drawPath(path)

                # --- Draw Day Number (NO OUTLINE) ---
                day_number = date.day()
                # Call the simplified draw function (only requires text color)
                self.drawOutlinedText(painter, cell_rect,
                                      int(Qt.AlignmentFlag.AlignCenter), # Center alignment
                                      str(day_number),
                                      day_number_text_color, # Use the determined color
                                      day_font)
                # --- End Draw Day Number ---

    # --- Timer Management for Animation ---
    def hideEvent(self, event):
         """Stop animation timer when widget is hidden."""
         print("HeatmapWidget hidden, stopping animation timer.")
         self.heatmap_animation_timer.stop()
         super().hideEvent(event)

    def showEvent(self, event):
         """Start animation timer when widget is shown."""
         print("HeatmapWidget shown, starting animation timer.")
         # Ensure layout is calculated *before* starting updates if needed
         if self._needs_layout_update or not self._cell_rects:
             self._calculate_layout()
         # Start timer only if it wasn't already active (prevents multiple starts)
         if not self.heatmap_animation_timer.isActive():
             self.heatmap_animation_timer.start(100) # Update interval for animation
         # Flag layout update in case size changed while hidden
         self._needs_layout_update = True
         super().showEvent(event)

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
        self.setFixedSize(170, 50) # Adjusted size slightly

        self._mouse_press_pos = None
        self._mouse_move_pos = None

    def set_overrun(self, overrun, seconds=0):
        self.is_overrun = overrun
        self.overrun_seconds = seconds if overrun else 0
        self.update_background_color()
        self.update() # Trigger repaint

    def update_background_color(self):
        if not self.is_overrun:
            self.background_color = QColor(0, 0, 0, 180)
        else:
            red_factor = min(1.0, self.overrun_seconds / MAX_OVERRUN_SECONDS_FOR_RED)
            red_component = int(red_factor * 150)
            self.background_color = QColor(red_component, 0, 0, 190) # Slightly less transparent red

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self.background_color))
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        border_radius = 10.0
        rect = QRectF(self.rect())
        rect.adjust(0.5, 0.5, -0.5, -0.5) # Adjust for pixel-perfect border
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

# --- Entry Management Dialog (unchanged) ---
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
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)         # Timestamp
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
        for row, (entry_id, duration, timestamp_str) in enumerate(entries): # timestamp_str из БД (UTC)
            formatted_duration = MainWindow.format_time(None, duration)
            formatted_timestamp_display = timestamp_str # Значение по умолчанию, если конвертация не удастся

            if timestamp_str: # Убедимся, что строка не пустая
                try:
                    # 1. Парсим строку времени из БД
                    dt_utc = QDateTime.fromString(timestamp_str, "yyyy-MM-dd HH:mm:ss")

                    # --- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Указываем, что это время UTC ---
                    dt_utc.setTimeSpec(Qt.TimeSpec.UTC)
                    # --- КОНЕЦ ИЗМЕНЕНИЯ ---

                    # 2. Конвертируем UTC время в локальное время пользователя
                    dt_local = dt_utc.toLocalTime()

                    # 3. Форматируем локальное время для отображения
                    formatted_timestamp_display = dt_local.toString("yyyy-MM-dd HH:mm:ss") # Или другой формат, например "yyyy-MM-dd HH:mm"

                except Exception as e:
                    print(f"Ошибка парсинга/конвертации времени '{timestamp_str}': {e}")
                    # Оставляем исходную строку в случае ошибки

            id_item = QTableWidgetItem(str(entry_id))
            id_item.setData(Qt.ItemDataRole.UserRole, entry_id)
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            duration_item = QTableWidgetItem(formatted_duration)
            duration_item.setData(Qt.ItemDataRole.UserRole, duration)
            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Используем конвертированное локальное время для отображения
            timestamp_item = QTableWidgetItem(formatted_timestamp_display)
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

# --- Daily Snapshot Dialog (unchanged) ---
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

        direct_time_by_activity_id = defaultdict(int)

        # Заполнение таблицы деталей и агрегация времени
        for row, (activity_id, activity_name, duration, timestamp_str) in enumerate(entries): # timestamp_str из БД (UTC)
            total_duration_day_seconds += duration
            direct_time_by_activity_id[activity_id] += duration

            # --- Заполнение таблицы детальных записей ---
            formatted_duration = MainWindow.format_time(None, duration)
            formatted_timestamp_display = timestamp_str # Значение по умолчанию

            if timestamp_str:
                 try:
                    # 1. Парсим строку времени из БД
                    dt_utc = QDateTime.fromString(timestamp_str, "yyyy-MM-dd HH:mm:ss")
                    # 2. Указываем, что это время UTC
                    dt_utc.setTimeSpec(Qt.TimeSpec.UTC)
                    # 3. Конвертируем UTC время в локальное время пользователя
                    dt_local = dt_utc.toLocalTime()
                    # 4. Форматируем локальное время для отображения (здесь достаточно времени)
                    formatted_timestamp_display = dt_local.toString("HH:mm:ss")
                 except Exception as e:
                    print(f"Ошибка парсинга/конвертации времени '{timestamp_str}' в слепке дня: {e}")
                    # Оставляем исходную строку или только время из нее
                    parts = timestamp_str.split(' ')
                    if len(parts) > 1:
                        formatted_timestamp_display = parts[1]


            name_item = QTableWidgetItem(activity_name)
            duration_item = QTableWidgetItem(formatted_duration)
            # Используем конвертированное локальное время для отображения
            time_item = QTableWidgetItem(formatted_timestamp_display)
            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            duration_item.setData(Qt.ItemDataRole.UserRole, duration) # Для сортировки

            self.entries_table.setItem(row, 0, name_item)
            self.entries_table.setItem(row, 1, duration_item)
            self.entries_table.setItem(row, 2, time_item)

        self.entries_table.setSortingEnabled(True)

        # 4. Get the full activity hierarchy (no need for habit info here)
        activity_hierarchy = self.db_manager.get_activity_hierarchy() # Fetches habit info now, but not used here
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

# --- NEW: Configure Habit Dialog ---
class ConfigureHabitDialog(QDialog):
    def __init__(self, activity_id, activity_name, current_config, db_manager, parent=None):
        super().__init__(parent)
        self.activity_id = activity_id
        self.activity_name = activity_name
        self.db_manager = db_manager
        # Unpack all three values: type, unit, and the new goal
        self.current_type, self.current_unit, self.current_goal = current_config

        self.setWindowTitle(f"Configure Habit: {activity_name}")
        layout = QVBoxLayout(self)

        # --- Checkbox for enabling habit tracking ---
        self.track_checkbox = QCheckBox("Track this activity as a habit")
        layout.addWidget(self.track_checkbox)

        # --- Group for type selection ---
        self.type_group = QWidget()
        type_layout = QVBoxLayout(self.type_group)
        type_layout.setContentsMargins(10, 0, 0, 0) # Indent

        self.radio_binary = QRadioButton("Binary (Done / Not Done)")
        self.radio_percentage = QRadioButton("Percentage (0-100% in 25% steps)")
        self.radio_numeric = QRadioButton("Numeric Value")
        type_layout.addWidget(self.radio_binary)
        type_layout.addWidget(self.radio_percentage)
        type_layout.addWidget(self.radio_numeric)

        # --- Group for numeric options (Unit and Goal) ---
        self.numeric_options_group = QWidget()
        # Use QFormLayout for label/field pairs
        numeric_layout = QFormLayout(self.numeric_options_group)
        numeric_layout.setContentsMargins(20, 5, 0, 0) # Further indent

        # Unit Input
        self.unit_input = QLineEdit()
        self.unit_input.setPlaceholderText("e.g., pages, km, minutes")
        numeric_layout.addRow("Unit:", self.unit_input)

        # --- Элементы для цели ---
        self.goal_checkbox = QCheckBox("Set Daily Goal?")
        self.goal_input = QDoubleSpinBox() # Поле для ввода числа
        self.goal_input.setRange(0.01, 999999.99) # Настройте диапазон при необходимости
        self.goal_input.setDecimals(2)
        self.goal_input.setSuffix("") # Единица измерения отдельно
        self.goal_input.setEnabled(False) # Изначально неактивно
        self.goal_checkbox.toggled.connect(self.goal_input.setEnabled) # Связь галочки и поля ввода
        # Добавляем в форму метку (галочку) и поле ввода
        numeric_layout.addRow(self.goal_checkbox, self.goal_input)
        # --- Конец элементов для цели ---

        # Add numeric options group to the type layout
        type_layout.addWidget(self.numeric_options_group)
        # Add type group to the main layout
        layout.addWidget(self.type_group)

        # --- Button Box ---
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(button_box)


        # --- Connect Signals ---
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self.track_checkbox.toggled.connect(self.toggle_options)
        # Also toggle options when numeric is selected/deselected
        self.radio_numeric.toggled.connect(self.toggle_options)
         # Connect goal checkbox toggle to options update as well
        self.goal_checkbox.toggled.connect(self.toggle_options)


        # --- Set Initial State ---
        is_habit = self.current_type is not None and self.current_type != HABIT_TYPE_NONE
        self.track_checkbox.setChecked(is_habit)

        if is_habit:
            if self.current_type == HABIT_TYPE_BINARY: self.radio_binary.setChecked(True)
            elif self.current_type == HABIT_TYPE_PERCENTAGE: self.radio_percentage.setChecked(True)
            elif self.current_type == HABIT_TYPE_NUMERIC:
                self.radio_numeric.setChecked(True)
                self.unit_input.setText(self.current_unit or "")
                # Use the unpacked self.current_goal here
                if self.current_goal is not None and self.current_goal > 0:
                     self.goal_checkbox.setChecked(True)
                     self.goal_input.setValue(self.current_goal)
                else:
                     self.goal_checkbox.setChecked(False)
                     # Set a reasonable default if no goal exists yet, but habit is numeric
                     default_goal = 1.0 # Default to 1 if minimum is 0.01
                     try: # Try to use minimum if it makes sense
                          if self.goal_input.minimum() > 0:
                               default_goal = self.goal_input.minimum()
                     except AttributeError: pass # Just use 1.0 if minimum fails
                     self.goal_input.setValue(default_goal)

            else: self.radio_binary.setChecked(True) # Fallback
        else:
            # Defaults if not currently a habit
            self.radio_binary.setChecked(True) # Default selection if enabling
            self.goal_checkbox.setChecked(False)
             # Set a reasonable default
            default_goal = 1.0
            try:
                 if self.goal_input.minimum() > 0:
                      default_goal = self.goal_input.minimum()
            except AttributeError: pass
            self.goal_input.setValue(default_goal)


        # --- Final UI State Update ---
        self.toggle_options() # Call this at the end to set initial enabled states

    def toggle_options(self):
        """Enable/disable options based on selections."""
        is_tracking = self.track_checkbox.isChecked()
        self.type_group.setEnabled(is_tracking)

        # Check if numeric radio button exists and is checked
        is_numeric_selected = hasattr(self, 'radio_numeric') and self.radio_numeric.isChecked()
        is_numeric = is_numeric_selected and is_tracking

        # Enable/disable the whole numeric options group
        if hasattr(self, 'numeric_options_group'):
             self.numeric_options_group.setEnabled(is_numeric)

        # Explicitly enable/disable children IF the group itself is enabled
        if hasattr(self, 'unit_input'): self.unit_input.setEnabled(is_numeric)
        if hasattr(self, 'goal_checkbox'): self.goal_checkbox.setEnabled(is_numeric)

        # Goal input enabled only if numeric AND goal checkbox is checked
        is_goal_checked = hasattr(self, 'goal_checkbox') and self.goal_checkbox.isChecked()
        if hasattr(self, 'goal_input'): self.goal_input.setEnabled(is_numeric and is_goal_checked)


    def get_selected_config(self):
        """Gets the selected habit type, unit, and goal."""
        if not self.track_checkbox.isChecked():
            return None, None, None # Not a habit

        habit_type = HABIT_TYPE_NONE
        habit_unit = None
        habit_goal = None

        if self.radio_binary.isChecked():
            habit_type = HABIT_TYPE_BINARY
        elif self.radio_percentage.isChecked():
            habit_type = HABIT_TYPE_PERCENTAGE
        elif self.radio_numeric.isChecked():
            habit_type = HABIT_TYPE_NUMERIC
            habit_unit = self.unit_input.text().strip() or None
            if self.goal_checkbox.isChecked():
                 goal_val = self.goal_input.value()
                 # Store only positive goals, others become None
                 habit_goal = goal_val if goal_val > 0 else None
            else:
                 habit_goal = None # Goal not set

        return habit_type, habit_unit, habit_goal

    def accept(self):
        new_type, new_unit, new_goal = self.get_selected_config()
        # Pass goal to db manager
        if self.db_manager.set_activity_habit_config(self.activity_id, new_type, new_unit, new_goal):
            print("Habit configuration saved (including goal).")
            super().accept()
        else:
            QMessageBox.warning(self, "Error", "Failed to save habit configuration to the database.")
            # Don't close the dialog on error
# --- End of ConfigureHabitDialog ---

class HabitCellDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.margin = 3

    def drawOutlinedText(self, painter: QPainter, rect: QRectF, flags: int,
                         text: str, text_color: QColor, outline_color: QColor):
        painter.save()
        offset = 1
        painter.setPen(outline_color)
        painter.drawText(rect.translated(offset, offset), flags, text)
        painter.drawText(rect.translated(-offset, -offset), flags, text)
        painter.drawText(rect.translated(-offset, offset), flags, text)
        painter.drawText(rect.translated(offset, -offset), flags, text)
        painter.setPen(text_color)
        painter.drawText(rect, flags, text)
        painter.restore()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        print_debug = False # Отладка выключена

        painter.save()
        self.initStyleOption(option, index)

        value = index.data(HABIT_VALUE_ROLE)
        habit_type = index.data(HABIT_TYPE_ROLE)
        habit_unit = index.data(HABIT_UNIT_ROLE)
        habit_goal = index.data(HABIT_GOAL_ROLE)

        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget)
        content_rect = option.rect.adjusted(self.margin, self.margin, -self.margin, -self.margin)
        if not content_rect.isValid(): painter.restore(); return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        default_text_color = option.palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Text)
        default_outline_color = Qt.GlobalColor.black
        progress_bar_color = Qt.GlobalColor.white
        text_color_on_bar = Qt.GlobalColor.black
        outline_color_on_bar = Qt.GlobalColor.white
        text_color_on_gradient = Qt.GlobalColor.white
        outline_color_on_gradient = Qt.GlobalColor.black
        faint_text_color = option.palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)

        # --- Type-Specific Drawing ---
        if habit_type == HABIT_TYPE_BINARY:
            if value == 1.0: painter.fillRect(option.rect, progress_bar_color)

        elif habit_type == HABIT_TYPE_PERCENTAGE:
            display_text = None
            main_text_color = default_text_color # Цвет по умолчанию
            outline_color = default_outline_color # Обводка по умолчанию

            if value is not None and value > 0:
                val = value or 0.0
                display_text = f"{val:g}%" # Текст для отображения

                if val >= 100.0:
                    # --- Рисуем градиент ---
                    painter.save()
                    bar_rect = QRectF(content_rect)
                    current_time = time.time()
                    hue1 = int(current_time * 150) % 360; hue2 = (hue1 + 60) % 360
                    color1 = QColor.fromHsl(hue1, 220, 195); color2 = QColor.fromHsl(hue2, 230, 200)
                    gradient = QLinearGradient(bar_rect.topLeft(), bar_rect.bottomRight())
                    gradient.setColorAt(0, color1); gradient.setColorAt(1, color2)
                    painter.fillRect(bar_rect, gradient)
                    painter.restore()
                    # Устанавливаем цвета для текста на градиенте
                    main_text_color = text_color_on_gradient
                    outline_color = outline_color_on_gradient
                else: # < 100%
                    # --- Рисуем квадранты ---
                    fill_color = progress_bar_color; border_color = Qt.GlobalColor.lightGray
                    painter.setBrush(QBrush(fill_color)); painter.setPen(QPen(border_color, 0.5))
                    w, h = content_rect.width(), content_rect.height()
                    half_w, half_h = w / 2, h / 2; center_x = content_rect.left() + half_w; center_y = content_rect.top() + half_h
                    q1 = QRectF(content_rect.left(), content_rect.top(), half_w, half_h); q2 = QRectF(center_x, content_rect.top(), half_w, half_h)
                    q3 = QRectF(content_rect.left(), center_y, half_w, half_h); q4 = QRectF(center_x, center_y, half_w, half_h)
                    # Устанавливаем цвета для текста на белых квадрантах
                    main_text_color = text_color_on_bar
                    outline_color = outline_color_on_bar
                    # Рисуем квадранты поверх фона, но до текста
                    if val >= 25.0: painter.drawRect(q1);
                    if val >= 50.0: painter.drawRect(q2);
                    if val >= 75.0: painter.drawRect(q3);
                    # Квадрант 100% не рисуем здесь, т.к. он обрабатывается выше градиентом

            # --- Рисуем текст для Percentage (если есть) ---
            if display_text is not None:
                 self.drawOutlinedText(painter, option.rect, Qt.AlignmentFlag.AlignCenter,
                                       display_text, main_text_color, outline_color)


        elif habit_type == HABIT_TYPE_NUMERIC:
            # ... (вся логика для Numeric остается БЕЗ ИЗМЕНЕНИЙ, как в прошлом ответе) ...
            display_value_text = None; progress_percentage = None
            main_text_color = default_text_color; outline_color = default_outline_color
            if value is not None:
                unit_part = f"\n{habit_unit}" if habit_unit else ""
                display_value_text = f"{value:g}{unit_part}"
                if habit_goal is not None and habit_goal > 0:
                    progress_percentage = value / habit_goal
                    goal_part = f" / {habit_goal:g}"
                    display_value_text = f"{value:g}{goal_part}{unit_part}"

            if progress_percentage is not None:
                painter.save()
                bar_rect = QRectF(content_rect)
                if progress_percentage >= 1.0:
                    current_time = time.time()
                    hue1 = int(current_time * 150) % 360; hue2 = (hue1 + 60) % 360
                    color1 = QColor.fromHsl(hue1, 220, 195); color2 = QColor.fromHsl(hue2, 230, 200)
                    gradient = QLinearGradient(bar_rect.topLeft(), bar_rect.bottomRight())
                    gradient.setColorAt(0, color1); gradient.setColorAt(1, color2)
                    painter.fillRect(bar_rect, gradient)
                    main_text_color = text_color_on_gradient
                    outline_color = outline_color_on_gradient
                else:
                    fill_width = bar_rect.width() * progress_percentage
                    progress_fill_rect = QRectF(bar_rect.left(), bar_rect.top(), fill_width, bar_rect.height())
                    painter.fillRect(progress_fill_rect, progress_bar_color)
                    if progress_percentage > 0:
                         main_text_color = text_color_on_bar
                         outline_color = outline_color_on_bar
                painter.restore()

            if display_value_text is not None:
                 self.drawOutlinedText(painter, option.rect, Qt.AlignmentFlag.AlignCenter,
                                       display_value_text, main_text_color, outline_color)


        painter.restore()

# --- End of HabitCellDelegate ---
# --- End of HabitCellDelegate ---
# --- End of HabitCellDelegate ---# --- NEW: Habit Table Model ---
class HabitTableModel(QAbstractTableModel):
    """
    Data model for the habit tracker grid (QTableView).
    Manages fetching, caching, and updating habit data.
    Rows = Habits, Columns = Days of the month.
    """
    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        # Now expects tuples of 5: (id, name, type, unit, goal)
        self._habit_configs = []
        self._habit_logs_cache = {} # Cache: (activity_id, 'YYYY-MM-DD') -> value
        self._row_map = {}        # Cache: row_index -> activity_id
        self._col_map = {}        # Cache: col_index -> 'YYYY-MM-DD' date string
        self._current_year = -1
        self._current_month = -1
        self._days_in_month = 0
        self._today_date_str = QDate.currentDate().toString("yyyy-MM-dd")
        self._is_current_month_view = False
        self._today_day_of_month = -1
        self._daily_avg_completion = {} # {QDate: float (0.0-1.0)} - Хранилище среднего %
   
    def load_data(self, year, month):
        """Loads/reloads habit and log data for the given year and month."""
        print(f"Model: Loading data for {year}-{month:02d}")
        self.beginResetModel()  # Important: Signal start of major change

        self._current_year = year
        self._current_month = month
        current_month_qdate = QDate(year, month, 1)
        self._days_in_month = current_month_qdate.daysInMonth()
        today_qdate = QDate.currentDate()
        self._is_current_month_view = (year == today_qdate.year() and month == today_qdate.month())
        self._today_day_of_month = today_qdate.day() if self._is_current_month_view else -1
        self._today_date_str = today_qdate.toString("yyyy-MM-dd") # Keep today's date string updated

        # 1. Fetch ordered habit configurations (now includes goal)
        # Expected format: [(id, name, type, unit, goal), ...]
        self._habit_configs = self.db_manager.get_all_habits()

        # 2. Update row map (visual row index -> activity_id)
        self._row_map = {idx: config[0] for idx, config in enumerate(self._habit_configs)}

        # 3. Update column map (visual col index -> date_str)
        self._col_map = {
            idx: QDate(year, month, idx + 1).toString("yyyy-MM-dd")
            for idx in range(self._days_in_month)
        }

        # 4. Fetch logs for the month
        self._habit_logs_cache = self.db_manager.get_habit_logs_for_month(year, month)
        # --- Расчет среднего выполнения для дней месяца ---
        self._daily_avg_completion = {}
        today = QDate.currentDate()
        temp_date = QDate(year, month, 1)
        # Определяем конец месяца правильно
        days_in_month = temp_date.daysInMonth()
        month_end = QDate(year, month, days_in_month) # Последний день месяца

        while temp_date <= month_end:
             if temp_date <= today: # Считаем только для прошедших/текущего дня
                 date_str = temp_date.toString("yyyy-MM-dd")
                 total_progress = 0.0
                 habits_with_goals_count = 0
                 # Используем self._habit_configs, который уже загружен
                 for habit_id, config in enumerate(self._habit_configs):
                      # config здесь это (id, name, type, unit, goal)
                      h_id = config[0] # Получаем ID из кортежа
                      h_type = config[2]
                      h_goal = config[4]

                      if h_type == HABIT_TYPE_NUMERIC and h_goal is not None and h_goal > 0:
                          value = self._habit_logs_cache.get((h_id, date_str)) # Ищем лог по ID
                          habits_with_goals_count += 1
                          if value is not None:
                              total_progress += min(value / h_goal, 1.0)

                 average_completion = (total_progress / habits_with_goals_count) if habits_with_goals_count > 0 else 0.0
                 if average_completion > 0.7: # Сохраняем только если > 70%
                      self._daily_avg_completion[temp_date] = average_completion
             temp_date = temp_date.addDays(1)
             
        self.endResetModel()
        print(f"Model: Loaded {len(self._habit_configs)} habits. Precalculated {len(self._daily_avg_completion)} daily averages > 70%.")
    # --- Required Model Methods ---

    def rowCount(self, parent=QModelIndex()):
        return len(self._habit_configs) if not parent.isValid() else 0

    def columnCount(self, parent=QModelIndex()):
        return self._days_in_month if not parent.isValid() else 0

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """Returns the data for a given index and role."""
        if not index.isValid() or not (0 <= index.row() < self.rowCount()) or not (0 <= index.column() < self.columnCount()):
            return QVariant()

        row = index.row()
        col = index.column()

        try:
            activity_id = self._row_map.get(row)
            date_str = self._col_map.get(col)
            if activity_id is None or date_str is None:
                 print(f"Warning: Invalid row/col map lookup for {row},{col}")
                 return QVariant()

            config = self._habit_configs[row]
            if config[0] != activity_id: # Sanity check
                 print(f"Warning: Row map/config list mismatch at row {row}")
                 config = next((c for c in self._habit_configs if c[0] == activity_id), None)

            if not config:
                 print(f"Warning: Config not found for activity_id {activity_id}")
                 return QVariant()

            habit_type = config[2]
            habit_unit = config[3]
            habit_goal = config[4] # <<< Get goal (index 4)

            # --- Handle Roles ---
            if role == HABIT_VALUE_ROLE:
                return self._habit_logs_cache.get((activity_id, date_str), None)
            elif role == HABIT_TYPE_ROLE:
                return habit_type
            elif role == HABIT_UNIT_ROLE:
                return habit_unit
            elif role == HABIT_DATE_ROLE:
                return date_str
            elif role == HABIT_ACTIVITY_ID_ROLE:
                return activity_id
            elif role == HABIT_GOAL_ROLE: # <<< Handle goal role
                return habit_goal
            elif role == Qt.ItemDataRole.BackgroundRole:
                day_of_month = col + 1
                if self._is_current_month_view and day_of_month == self._today_day_of_month:
                    return QColor(60, 60, 60)
                return QVariant()
            elif role == Qt.ItemDataRole.ToolTipRole:
                 value = self._habit_logs_cache.get((activity_id, date_str))
                 name = config[1]
                 tt = f"{name}\n{date_str}"
                 # <<< Updated Tooltip for Goal >>>
                 goal_str = f" / Goal: {habit_goal:g}" if habit_type == HABIT_TYPE_NUMERIC and habit_goal is not None else ""
                 if value is not None:
                     if habit_type == HABIT_TYPE_BINARY: tt += f"\nStatus: {'Done' if value == 1.0 else 'Not Done'}"
                     elif habit_type == HABIT_TYPE_PERCENTAGE: tt += f"\nCompleted: {value:g}%"
                     elif habit_type == HABIT_TYPE_NUMERIC: tt += f"\nValue: {value:g}{f' {habit_unit}' if habit_unit else ''}{goal_str}"
                 else:
                      tt += "\nStatus: Not Logged"
                      if habit_type == HABIT_TYPE_NUMERIC and habit_goal is not None: tt += goal_str # Show goal even if not logged
                 return tt
                 # <<< End Tooltip Update >>>
            elif role == Qt.ItemDataRole.DisplayRole:
                 return "" # Let delegate handle visuals

        except Exception as e:
             print(f"Error in model data({row},{col}), role {role}: {e}")
             import traceback
             traceback.print_exc()
             return QVariant()

        return QVariant()

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != HABIT_VALUE_ROLE:
            return False
        row = index.row()
        col = index.column()
        activity_id = self._row_map.get(row)
        date_str = self._col_map.get(col)
        if activity_id is None or date_str is None: return False

        print(f"Model: setData triggered for A_ID={activity_id}, Date={date_str}, NewValue={value}")
        if self.db_manager.log_habit(activity_id, date_str, value):
            cache_key = (activity_id, date_str)
            if value is None: self._habit_logs_cache.pop(cache_key, None)
            else: self._habit_logs_cache[cache_key] = value
            self.dataChanged.emit(index, index, [role, Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.DisplayRole])
            print(f"Model: setData successful for {activity_id} on {date_str}")
            return True
        else:
            print(f"Model: setData FAILED DB update for {activity_id} on {date_str}")
            return False

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        """Возвращает данные заголовка, включая фон для >70% выполнения."""

        # --- Сначала обрабатываем ТЕКСТ заголовка ---
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                # Колонки: Номер дня
                return str(section + 1)

            if orientation == Qt.Orientation.Vertical:
                # Строки: Имя привычки
                if 0 <= section < len(self._habit_configs):
                    # Возвращаем имя привычки (индекс 1 в кортеже _habit_configs)
                    return self._habit_configs[section][1]
                else:
                    return QVariant() # На случай некорректного индекса строки

            # Если ориентация не горизонтальная и не вертикальная
            return QVariant()

        # --- Затем обрабатываем ФОН для горизонтального заголовка ---
        elif orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.BackgroundRole:
            col_index = section
            date_str = self._col_map.get(col_index)
            if date_str:
                current_date = QDate.fromString(date_str, "yyyy-MM-dd")
                # Проверяем предрасчитанное значение (оно хранится в self._daily_avg_completion)
                # Убедитесь, что _daily_avg_completion рассчитывается в load_data
                if current_date in getattr(self, '_daily_avg_completion', {}): # Безопасная проверка наличия атрибута
                    # Логика расчета градиента (такая же, как была)
                    current_time = time.time()
                    hue1 = int(current_time * 150) % 360
                    hue2 = (hue1 + 60) % 360
                    color1 = QColor.fromHsl(hue1, 200, 180)
                    color2 = QColor.fromHsl(hue2, 210, 185)
                    gradient = QLinearGradient(0, 0, 0, 1)
                    gradient.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
                    gradient.setColorAt(0, color1); gradient.setColorAt(1, color2)
                    return QBrush(gradient) # Возвращаем QBrush

            # Если условие >70% не выполнено или дата не найдена
            return QVariant()

        # Для всех остальных ролей и ориентаций
        return QVariant()

        # --- НОВОЕ: Фон для горизонтального заголовка (дней) ---
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.BackgroundRole:
            col_index = section # section - это и есть индекс колонки
            total_progress = 0.0
            habits_with_goals_count = 0

            # Итерация по всем привычкам (строкам) для данной колонки (дня)
            for row_index in range(self.rowCount()):
                habit_goal = self.data(self.index(row_index, col_index), HABIT_GOAL_ROLE)
                # Учитываем только числовые привычки с установленной целью > 0
                if habit_goal is not None and habit_goal > 0:
                    value = self.data(self.index(row_index, col_index), HABIT_VALUE_ROLE)
                    habits_with_goals_count += 1
                    if value is not None:
                        # Добавляем процент выполнения этой привычки (ограничиваем 1.0 сверху)
                        total_progress += min(value / habit_goal, 1.0)

            # Считаем средний процент выполнения по всем привычкам с целями за день
            average_completion = (total_progress / habits_with_goals_count) if habits_with_goals_count > 0 else 0.0

            # Если выполнено > 70%, возвращаем мигающий градиент
            if average_completion > 0.7:
                # Логика расчета градиента (такая же, как в делегате ячеек)
                current_time = time.time()
                hue1 = int(current_time * 150) % 360
                hue2 = (hue1 + 60) % 360
                # Используем чуть менее яркие цвета для заголовка, чтобы текст был читаем
                color1 = QColor.fromHsl(hue1, 200, 180)
                color2 = QColor.fromHsl(hue2, 210, 185)
                # Создаем градиент (например, вертикальный для заголовка)
                # Размеры секции заголовка нам тут неизвестны, создадим простой градиент
                # Стиль сам применит его к фону секции
                gradient = QLinearGradient(0, 0, 0, 1) # Простой вертикальный градиент
                gradient.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode) # Важно для заголовка!
                gradient.setColorAt(0, color1)
                gradient.setColorAt(1, color2)
                return QBrush(gradient) # Возвращаем QBrush

            # Иначе возвращаем пустой QVariant (будет использован фон по умолчанию)
            return QVariant()

        # Для всех остальных ролей и ориентаций
        return QVariant()

    def flags(self, index):
         if not index.isValid(): return Qt.ItemFlag.NoItemFlags
         return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # --- Custom Methods for Reordering ---
    def get_activity_id_for_row(self, row): return self._row_map.get(row)
    def _get_ordered_habit_ids(self): return [config[0] for config in self._habit_configs]
    def move_habit(self, source_row, destination_row):
         if not (0 <= source_row < self.rowCount()) or \
            not (0 <= destination_row < self.rowCount()) or \
            source_row == destination_row: return False
         print(f"Model: Attempting move from {source_row} to {destination_row}")
         actual_dest_signal_row = destination_row if destination_row < source_row else destination_row + 1
         if not self.beginMoveRows(QModelIndex(), source_row, source_row, QModelIndex(), actual_dest_signal_row):
              print("Model: beginMoveRows failed.")
              return False
         moved_item = self._habit_configs.pop(source_row)
         self._habit_configs.insert(destination_row, moved_item)
         ordered_ids = self._get_ordered_habit_ids()
         db_success = self.db_manager.update_habit_order(ordered_ids)
         if db_success:
             print("Model: DB order updated successfully.")
             self._row_map = {idx: config[0] for idx, config in enumerate(self._habit_configs)}
             self.endMoveRows()
             print(f"Model: Move from {source_row} to {destination_row} completed.")
             return True
         else:
             print("Model: DB order update FAILED. Rolling back internal move.")
             rollback_item = self._habit_configs.pop(destination_row)
             self._habit_configs.insert(source_row, rollback_item)
             self.endMoveRows()
             print(f"Model: Move from {source_row} to {destination_row} failed & rolled back.")
             return False
# --- End of HabitTableModel ---

class HabitTrackerDialog(QDialog):
    # Optional: Define a signal if this dialog needs to inform others of changes
    # habits_logged_signal = pyqtSignal(int, str) # activity_id, date_str

    def __init__(self, db_manager: DatabaseManager, main_window_parent=None): # Pass parent for signal connection
        super().__init__(main_window_parent) # Use main_window_parent
        self.db_manager = db_manager
        self.current_qdate = QDate.currentDate() # Tracks the month/year being viewed

        # --- Model ---
        self.habit_model = HabitTableModel(self.db_manager, self)

        self.setWindowTitle("Habit Tracker (Model/View)") # Updated title
        self.setMinimumSize(800, 600)

        # --- Main Layout ---
        layout = QVBoxLayout(self)

        self.grid_animation_timer = QTimer(self) # Назовем его так для ясности
        self.grid_animation_timer.timeout.connect(self._trigger_grid_update) # Слот для обновления сетки
        self.grid_animation_timer.start(100) # Интервал обновления
        
        # --- Navigation Layout (Remains the same) ---
        nav_layout = QHBoxLayout()
        self.prev_month_button = QPushButton("< Prev")
        self.prev_month_button.clicked.connect(self.go_prev_month)
        self.month_year_label = QLabel("Month Year")
        font = self.month_year_label.font(); font.setPointSize(14); font.setBold(True)
        self.month_year_label.setFont(font)
        self.month_year_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_month_button = QPushButton("Next >")
        self.next_month_button.clicked.connect(self.go_next_month)
        self.today_button = QPushButton("Today")
        self.today_button.clicked.connect(self.go_today)
        nav_layout.addWidget(self.prev_month_button)
        nav_layout.addWidget(self.month_year_label, 1)
        nav_layout.addWidget(self.next_month_button)
        nav_layout.addWidget(self.today_button)
        layout.addLayout(nav_layout)

        # --- Habit Grid (Now QTableView) ---
        self.habit_grid = QTableView()
        self.habit_grid.setModel(self.habit_model)
        self.habit_grid.setItemDelegate(HabitCellDelegate(self)) # Делегат рисует градиент
       
        # --- View Configuration ---
        self.habit_grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers) # We handle edits on double-click
        self.habit_grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # self.habit_grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems) # Default is usually fine

        # Configure Headers
        v_header = self.habit_grid.verticalHeader()
        h_header = self.habit_grid.horizontalHeader()

        # Увеличим высоту строк (подберите значение по вкусу)
        v_header.setDefaultSectionSize(45) # Было ResizeToContents или 30
        v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed) # Или Interactive, если хотите менять вручную

        # Увеличим ширину столбцов (подберите значение по вкусу)
        h_header.setDefaultSectionSize(80) # Было 45
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed) # Или Interactive

        v_header.setToolTip("Habits (Right-click to reorder)")
        h_header.setToolTip("Day of Month")
        
        # Enable context menu on vertical header for reordering
        v_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        v_header.customContextMenuRequested.connect(self.show_header_context_menu)

        # Connect double-click signal
        self.habit_grid.doubleClicked.connect(self.on_grid_double_clicked) # Connect to QModelIndex signal

        layout.addWidget(self.habit_grid)

        # --- Bottom Buttons ---
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        # Подключаем reject к нашему методу для остановки таймера
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

        # --- Connect to MainWindow's update signal if parent is passed ---
        if main_window_parent and hasattr(main_window_parent, 'habits_updated'):
            main_window_parent.habits_updated.connect(self.refresh_view_slot)
            print("HabitTrackerDialog connected to MainWindow.habits_updated signal.")

        self.refresh_view() # Initial load

    # --- Slot for External Updates ---
    def refresh_view_slot(self):
        """Slot to be connected to external signals indicating data might have changed."""
        print("HabitTrackerDialog received external update signal. Refreshing view.")
        # Reload data for the *currently viewed* month/year
        self.refresh_view()

    def _trigger_grid_update(self):
        """Слот для таймера, обновляющий сетку для анимации делегата."""
        if self.habit_grid.isVisible():
            # self.habit_grid.viewport().update() # Можно попробовать заменить на:
            self.habit_grid.update() # Часто работает надежнее для анимации
    # ----------------------------------------


# В классе HabitTrackerDialog:     
    # --- Переопределяем reject для остановки ТАЙМЕРА СЕТКИ ---
    def reject(self):
        """Останавливаем таймер анимации сетки перед закрытием."""
        print("Stopping grid animation timer and rejecting dialog.")
        self.grid_animation_timer.stop() # Останавливаем таймер сетки
        super().reject()
    # ------------------------------------------------------

    # --- Navigation Methods (Simplified) ---
    def go_prev_month(self):
        self.current_qdate = self.current_qdate.addMonths(-1)
        self.refresh_view()

    def go_next_month(self):
        self.current_qdate = self.current_qdate.addMonths(1)
        self.refresh_view()

    def go_today(self):
        today = QDate.currentDate()
        if self.current_qdate.year() != today.year() or self.current_qdate.month() != today.month():
            self.current_qdate = today
            self.refresh_view()
        else:
             # Scroll to today's column if already in the current month
             today_col_idx = today.day() - 1
             if 0 <= today_col_idx < self.habit_model.columnCount():
                 self.habit_grid.scrollTo(
                     self.habit_model.index(0, today_col_idx), # Scroll to first row, today's column
                     QAbstractItemView.ScrollHint.PositionAtCenter
                 )


    # --- Data Loading / Refresh Method (Simplified) ---
    def refresh_view(self):
        """Loads and displays habit data by telling the model to update."""
        year = self.current_qdate.year()
        month = self.current_qdate.month()

        # Update month/year label
        self.month_year_label.setText(self.current_qdate.toString("MMMM yyyy")) # Corrected format string

        # Tell the model to load data for the new period
        self.habit_model.load_data(year, month)

        # Optional: Auto-resize columns/rows after model reset if needed, though ResizeToContents might handle it.
        # self.habit_grid.resizeColumnsToContents()
        # self.habit_grid.resizeRowsToContents() # Already set resize mode

        print(f"HabitTrackerDialog view refreshed for {year}-{month:02d}.")


    # --- Context Menu Method (Uses Model) ---
    def show_header_context_menu(self, position):
        header = self.habit_grid.verticalHeader()
        # Use logicalIndexAt for visual row index corresponding to model row
        row = header.logicalIndexAt(position) # Get model row index
        if not (0 <= row < self.habit_model.rowCount()): return

        menu = QMenu(self)
        style = QApplication.style() # Get style for icons

        move_up_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp), "Move Up", self)
        if row == 0: move_up_action.setEnabled(False)
        # Use lambda to capture the current row index
        move_up_action.triggered.connect(lambda checked=False, r=row: self.move_habit_up(r))
        menu.addAction(move_up_action)

        move_down_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown), "Move Down", self)
        if row == self.habit_model.rowCount() - 1: move_down_action.setEnabled(False)
        move_down_action.triggered.connect(lambda checked=False, r=row: self.move_habit_down(r))
        menu.addAction(move_down_action)

        menu.exec(header.mapToGlobal(position))

    # --- Reordering Action Handlers (Use Model) ---
    def move_habit_up(self, row):
        """Tells the model to move the habit at the given row index up."""
        if row > 0:
            destination_row = row - 1
            if not self.habit_model.move_habit(row, destination_row):
                 QMessageBox.warning(self, "Error", "Failed to move habit up. Database update may have failed.")
            # View updates automatically via model signals if successful

    def move_habit_down(self, row):
        """Tells the model to move the habit at the given row index down."""
        if row < self.habit_model.rowCount() - 1:
             destination_row = row + 1
             if not self.habit_model.move_habit(row, destination_row):
                  QMessageBox.warning(self, "Error", "Failed to move habit down. Database update may have failed.")
             # View updates automatically via model signals if successful

    # --- Interaction Handling Method (Uses Model) ---
    def on_grid_double_clicked(self, index: QModelIndex): # Receives QModelIndex
        """Handles user interaction with a habit cell."""
        if not index.isValid(): return

        row = index.row()
        column = index.column()

        # Get data from the MODEL using the index and roles
        activity_id = self.habit_model.data(index, HABIT_ACTIVITY_ID_ROLE)
        date_str = self.habit_model.data(index, HABIT_DATE_ROLE)
        habit_type = self.habit_model.data(index, HABIT_TYPE_ROLE)
        habit_unit = self.habit_model.data(index, HABIT_UNIT_ROLE)
        current_value = self.habit_model.data(index, HABIT_VALUE_ROLE)
        habit_name = self.habit_model.headerData(row, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) # Get name from header

        if activity_id is None or habit_type is None or date_str is None:
            print(f"Error: Missing model data for index ({row},{column})")
            return

        new_value = None
        ok_to_set = False # Flag to proceed with setData

        # --- Determine New Value Based on Habit Type ---
        if habit_type == HABIT_TYPE_BINARY:
            # Simple toggle: 1.0 -> None, None/0.0 -> 1.0
            # Decide if 0.0 should be treated as None or explicitly 'Not Done'
            # Let's go with: Click toggles between Done (1.0) and Not Logged (None)
            new_value = None if current_value == 1.0 else 1.0
            ok_to_set = True

        elif habit_type == HABIT_TYPE_PERCENTAGE:
             # Cycle through None -> 25 -> 50 -> 75 -> 100 -> None
             val = current_value or 0.0 # Treat None as 0 for cycling start
             if val < 25.0: new_value = 25.0
             elif val < 50.0: new_value = 50.0
             elif val < 75.0: new_value = 75.0
             elif val < 100.0: new_value = 100.0
             else: new_value = None # Cycle back to None
             ok_to_set = True

        elif habit_type == HABIT_TYPE_NUMERIC:
            prompt = f"Enter value for '{habit_name}'"
            if habit_unit: prompt += f" ({habit_unit})"
            prompt += f" on {date_str}:\n(Enter 0 or Cancel to clear)" # Clarify clearing

            num_value, ok = QInputDialog.getDouble(
                 self, "Enter Numeric Value", prompt,
                 value=(current_value or 0.0), # Default to 0.0 if None
                 decimals=2 # Or adjust as needed
            )
            if ok:
                 # Allow setting 0 explicitly, treat Cancel or empty input as clearing
                 new_value = num_value if num_value != 0.0 else 0.0 # Store 0 if entered
                 # To clear, user must cancel or potentially enter specific text? Let's use 0/Cancel.
                 # If you want to clear it completely (set to None), need different logic.
                 # Let's stick to setting the entered value (0 is valid). If user wants None, maybe right-click->clear? Or handle 0 as None in setData?
                 # For simplicity now: OK saves the value entered (even 0).
                 # --- Modification: Let's treat OK with 0 as clearing to None for consistency ---
                 if num_value == 0.0:
                      # Ask to clarify if 0 means "clear" or "log zero"
                      reply = QMessageBox.question(self, "Confirm Zero",
                                                   f"Log value '0' for '{habit_name}' or clear the entry for this date?",
                                                   buttons=QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.No, # Rename No->Clear
                                                   defaultButton=QMessageBox.StandardButton.Cancel)
                      if reply == QMessageBox.StandardButton.Save: # Log Zero
                           new_value = 0.0
                           ok_to_set = True
                      elif reply == QMessageBox.StandardButton.No: # Clear (Set None)
                           new_value = None
                           ok_to_set = True
                      # else Cancelled, ok_to_set remains False
                 else: # Non-zero value entered
                     new_value = num_value
                     ok_to_set = True
            # else: User Cancelled, ok_to_set remains False

        else: # Unknown habit type
            print(f"Warning: Unknown habit type {habit_type} encountered.")
            ok_to_set = False


        # --- Update Model if Value Determined ---
        if ok_to_set:
            print(f"Dialog: Requesting model setData for index({row},{column}), NewValue={new_value}")
            # Let the model handle the DB interaction and notifying the view
            success = self.habit_model.setData(index, new_value, HABIT_VALUE_ROLE)
            if not success:
                 QMessageBox.warning(self, "Error", "Failed to save habit log update via model.")
            # else: View updates automatically via model's dataChanged signal
# --- End of HabitTrackerDialog Class ---

# --- Main Window (Significant changes) ---
class MainWindow(QMainWindow):
    habits_updated = pyqtSignal()
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

        # --- UI Elements ---
        self.activity_tree = None
        self.manage_entries_button = None
        self.snapshot_button = None
        self.habit_tracker_button = None # <-- New Button
        self.work_timer_button = None
        self.countdown_timer_button = None
        self.status_label = None
        self.heatmap_widget = None
        
        self.init_ui()
        self.apply_dark_theme()
        self.load_activities()

        # --- Connect Signal to Heatmap Refresh ---
        if self.heatmap_widget: # Ensure it was created in init_ui
             self.habits_updated.connect(self.heatmap_widget.refresh_data)
             print("Connected habits_updated signal to heatmap refresh.")
        # -----------------------------------------

    def init_ui(self):
        self.setWindowTitle("Ritual 0.08 - Habit Tracker") # Version bump
        self.setGeometry(100, 100, 750, 650) # Slightly larger

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Activity Tree ---
        main_layout.addWidget(QLabel("Activities (Right-click to add/manage):"))
        self.activity_tree = QTreeWidget()
        self.activity_tree.setColumnCount(1)
        self.activity_tree.setHeaderHidden(True)
        self.activity_tree.currentItemChanged.connect(self.activity_selected)
        self.activity_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.activity_tree.customContextMenuRequested.connect(self.show_activity_context_menu)
        self.activity_tree.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        main_layout.addWidget(self.activity_tree, 1) # Give tree some stretch factor

        # --- Management Buttons ---
        management_layout = QHBoxLayout()
        self.manage_entries_button = QPushButton("Manage Entries")
        self.manage_entries_button.clicked.connect(self.open_entry_management)
        self.manage_entries_button.setEnabled(False)

        self.snapshot_button = QPushButton("Daily Snapshot")
        self.snapshot_button.clicked.connect(self.open_daily_snapshot)

        # --- NEW Habit Tracker Button ---
        self.habit_tracker_button = QPushButton("Habit Tracker")
        self.habit_tracker_button.clicked.connect(self.open_habit_tracker) # Connect slot

        management_layout.addWidget(self.manage_entries_button)
        management_layout.addWidget(self.snapshot_button)
        management_layout.addWidget(self.habit_tracker_button) # Add to layout
        main_layout.addLayout(management_layout)

        # --- Timer Buttons ---
        timer_buttons_layout = QHBoxLayout()
        self.work_timer_button = QPushButton("Start Tracking")
        self.work_timer_button.setCheckable(True)
        self.work_timer_button.clicked.connect(self.toggle_timer)
        self.work_timer_button.setEnabled(False)

        self.countdown_timer_button = QPushButton("Start Countdown")
        self.countdown_timer_button.clicked.connect(self.start_countdown_timer)
        self.countdown_timer_button.setEnabled(False)

        timer_buttons_layout.addWidget(self.work_timer_button)
        timer_buttons_layout.addWidget(self.countdown_timer_button)
        main_layout.addLayout(timer_buttons_layout)

        # --- Status Bar ---
        self.status_label = QLabel("Select an activity")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.status_label)
        
        # --- NEW: Heatmap Widget ---
        main_layout.addWidget(QLabel("Yearly Habit Heatmap:")) # Add a label
        self.heatmap_widget = HeatmapWidget(self.db_manager, self)
        main_layout.addWidget(self.heatmap_widget, 0) # Add heatmap, no stretch factor initially
        # --------------------------

    def apply_dark_theme(self):
            # (Theme code remains unchanged from previous version)
            dark_palette = QPalette()
            dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
            # ... (rest of palette setup) ...
            dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(45, 45, 45)) # Slightly different disabled background

            app = QApplication.instance()
            if app:
                app.setPalette(dark_palette)
                # Stylesheet (ensure it covers new elements if needed)
                # --- Start commenting out sections below to debug ---
                app.setStyleSheet("""
                    QMainWindow { border: none; background-color: #353535; }
                    QWidget { color: white; background-color: #353535; } /* Default for widgets */
                    QDialog { background-color: #353535; } /* Ensure dialogs inherit */

                #    QPushButton {
                #        border: 1px solid #555; padding: 6px 12px; min-height: 20px;
                #        background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #555, stop: 1 #444);
                #        color: white; border-radius: 4px;
                #    }
                #    QPushButton:hover { background-color: #5E5E5E; }
                #    QPushButton:pressed { background-color: #707070; border: 1px solid #666; }
                #    QPushButton:checked { background-color: #4CAF50; border: 1px solid #3a8a40; } /* Used for Start/Stop state */
                #    QPushButton:disabled { background-color: #4F4F4F; color: #888; border: 1px solid #4F4F4F;}

                #    QLineEdit, QSpinBox, QDateTimeEdit, QDateEdit, QRadioButton, QCheckBox {
                #        border: 1px solid #555; padding: 5px; background-color: #2D2D2D; color: white;
                #        border-radius: 3px; selection-background-color: #2a82da; selection-color: white;
                #    }
                #    /* Specific overrides for Radio/Check background */
                #    QRadioButton, QCheckBox { background-color: transparent; border: none; }
                #    QRadioButton::indicator, QCheckBox::indicator { width: 13px; height: 13px; }
                #    /* Add more specific styles if needed for indicators */

                #    QLineEdit:focus, QSpinBox:focus, QDateTimeEdit:focus, QDateEdit:focus {
                #            border: 1px solid #2a82da;
                #    }
                #    QLineEdit:disabled, QSpinBox:disabled, QDateTimeEdit:disabled, QDateEdit:disabled {
                #        background-color: #454545; color: #888;
                #    }

                    /* Styles for QTreeWidget */
                #    QTreeWidget {
                #        border: 1px solid #555;
                #        background-color: #2D2D2D; /* Base color from palette */
                #        color: white;
                #        alternate-background-color: #353535; /* Alternate color from palette */
                #        selection-background-color: #2a82da; /* Highlight color */
                #        selection-color: white; /* Highlighted text color */
                #        outline: none; /* Removes focus dotted border */
                #    }
                #    QTreeWidget::item { padding: 4px; border-bottom: 1px solid #444; }
                #    QTreeWidget::item:selected { background-color: #2a82da; color: white; }
                #    /* QTreeWidget::item:alternate { background-color: #353535; } /* Already handled by alternate-background-color */ */
                #     /* Styles for tree branches */
                #     QTreeView::branch { background: transparent; }
                #     QTreeView::branch:has-children:!has-siblings:closed,
                #     QTreeView::branch:closed:has-children:has-siblings {
                #          border-image: none;
                #          image: url(:/qt-project.org/styles/commonstyle/images/branch-closed-16.png); /* Standard PyQt icon */
                #     }
                #     QTreeView::branch:open:has-children:!has-siblings,
                #     QTreeView::branch:open:has-children:has-siblings  {
                #          border-image: none;
                #          image: url(:/qt-project.org/styles/commonstyle/images/branch-open-16.png); /* Standard PyQt icon */
                #     }

                #    QHeaderView::section {
                #        background-color: #444; color: white; padding: 5px;
                #        border: 1px solid #555; border-bottom: 2px solid #666; font-weight: bold;
                #    }
                #    QHeaderView::section:checked { background-color: #2a82da; }

                #    QDateEdit::drop-down, QDateTimeEdit::drop-down {
                #        subcontrol-origin: padding; subcontrol-position: top right; width: 18px;
                #        border-left-width: 1px; border-left-color: #555; border-left-style: solid;
                #        border-top-right-radius: 3px; border-bottom-right-radius: 3px;
                #        background-color: #444;
                #    }
                #    /* QDateEdit::down-arrow { image: url(path/to/icon.png); } */

                #    QDateEdit QAbstractItemView, QDateTimeEdit QAbstractItemView {
                #        background-color: #2D2D2D; selection-background-color: #2a82da;
                #        color: white; outline: 1px solid #555; border: none;
                #    }
                #     QCalendarWidget QWidget#qt_calendar_navigationbar { background-color: #444; }
                #     QCalendarWidget QToolButton { color: white; background-color: #555; border: none; margin: 2px; padding: 3px; }
                #     QCalendarWidget QToolButton:hover { background-color: #666; }
                #     QCalendarWidget QMenu { background-color: #2D2D2D; color: white; }
                #     QCalendarWidget QSpinBox { background-color: #2D2D2D; color: white; }
                #     QCalendarWidget QWidget { alternate-background-color: #353535; } /* Day colors */
                #     QCalendarWidget QAbstractItemView:enabled { color: white; selection-background-color: #2a82da; } /* Text and selection color */
                #     QCalendarWidget QAbstractItemView:disabled { color: #888; } /* Other month days color */

                #    QSplitter { background-color: #353535; }
                #    QSplitter::handle:vertical { background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #666, stop:1 #555); height: 7px; border-top: 1px solid #777; border-bottom: 1px solid #444; margin: 1px 0; }
                #    QSplitter::handle:vertical:hover { background-color: #777; }
                #    QSplitter::handle:horizontal { background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #666, stop:1 #555); width: 7px; border-left: 1px solid #777; border-right: 1px solid #444; margin: 0 1px; }
                #    QSplitter::handle:horizontal:hover { background-color: #777; }

                #    QLabel { padding: 2px; color: white; background-color: transparent;}

                #    QDialogButtonBox QPushButton { min-width: 80px; }

                    /* Input Dialog Styles (make inputs readable) */
                #    QInputDialog { background-color: #353535; color: white; }
                #    QInputDialog QLabel { color: white; }
                #    QInputDialog QLineEdit { background-color: #FFF; color: black; border: 1px solid #AAA; padding: 4px; }
                #    QInputDialog QSpinBox { background-color: #FFF; color: black; border: 1px solid #AAA; padding: 4px; }
                #    QInputDialog QDateTimeEdit { background-color: #FFF; color: black; border: 1px solid #AAA; padding: 4px; }
                #    QInputDialog QDateEdit { background-color: #FFF; color: black; border: 1px solid #AAA; padding: 4px; }
                #    QInputDialog QDoubleSpinBox { background-color: #FFF; color: black; border: 1px solid #AAA; padding: 4px; } # <-- Add if using QInputDialog.getDouble
                #    QInputDialog QPushButton { color: white; background-color: #555; border: 1px solid #666; padding: 5px; min-width: 70px; }
                #    QInputDialog QPushButton:hover { background-color: #6E6E6E; }
                #    QInputDialog QPushButton:pressed { background-color: #808080; }

                #    QMessageBox { background-color: #353535; }
                #    QMessageBox QLabel { color: white; padding: 15px; qproperty-alignment: 'AlignCenter'; }
                #    QMessageBox QPushButton { min-width: 80px; padding: 6px 12px; }

                    /* Styles for QMenu */
                #     QMenu { background-color: #2D2D2D; border: 1px solid #555; color: white; padding: 5px; }
                #     QMenu::item { padding: 5px 25px 5px 20px; border: 1px solid transparent; }
                #     QMenu::item:selected { background-color: #2a82da; color: white; }
                #     QMenu::separator { height: 1px; background: #555; margin: 2px 10px; }
                #     QMenu::indicator { width: 13px; height: 13px; }

                    /* Table Widget specific style */
                #     QTableWidget { /* Applies to QTableView too unless overridden */
                #          border: 1px solid #555; background-color: #2D2D2D; color: white;
                #          alternate-background-color: #353535; gridline-color: #444;
                #          selection-background-color: #2a82da; selection-color: white; outline: none;
                #     }
                #     QTableView { /* More specific for your habit grid */
                #          border: 1px solid #555; background-color: #2D2D2D; color: white;
                #          alternate-background-color: #353535; gridline-color: #444;
                #          selection-background-color: #2a82da; selection-color: white; outline: none;
                #     }
                #     QTableView::item { padding: 2px; border: none;} /* Adjust padding for habit grid, remove default borders if any */
                    /* Selection handled by delegate / option.state */
                    /* QTableWidget::item:selected { background-color: #2a82da; color: white; } */
                """)
    def load_activities(self):
        """Loads the activity hierarchy into the QTreeWidget."""
        self.activity_tree.clear()
        self.activity_tree.setSortingEnabled(False) # Disable sorting during load

        # Get hierarchy: [{id:.., name:.., parent:.., children:[...], habit_type:.., habit_unit:..}, ...]
        hierarchy = self.db_manager.get_activity_hierarchy()

        # Recursive function to add nodes to the tree
        def add_items_recursive(parent_widget_item, activity_nodes):
            for node in activity_nodes:
                item = QTreeWidgetItem(parent_widget_item)
                # Optionally indicate habits in the tree visually (e.g., icon or suffix)
                prefix = ""
                if node['habit_type'] is not None:
                    prefix = "[H] " # Simple indication
                    # Or set an icon: item.setIcon(0, habit_icon)

                item.setText(0, prefix + node['name'])
                item.setData(0, Qt.ItemDataRole.UserRole, node['id']) # Store activity ID
                # Store habit config on item too for easy access in context menu
                item.setData(0, HABIT_TYPE_ROLE, node['habit_type'])  # CORRECTED: Added column index 0
                item.setData(0, HABIT_UNIT_ROLE, node['habit_unit'])  # CORRECTED: Added column index 0

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
        add_top_level_action = QAction(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder), "Add Top-Level Activity", self)
        add_top_level_action.triggered.connect(lambda: self.add_activity_action(parent_id=None))
        menu.addAction(add_top_level_action)

        # --- Actions available when an item is selected ---
        if selected_item:
            menu.addSeparator()

            # Add Sub-Activity
            add_sub_action = QAction(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder), f"Add Sub-Activity to '{selected_item.text(0)}'", self)
            add_sub_action.triggered.connect(lambda: self.add_activity_action(parent_id=selected_id))
            menu.addAction(add_sub_action)

            menu.addSeparator()

            # Rename
            rename_action = QAction(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), "Rename", self)
            rename_action.triggered.connect(self.rename_activity_action)
            menu.addAction(rename_action)

            # --- NEW: Configure Habit ---
            config_habit_action = QAction(QIcon.fromTheme("preferences-system", QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)), "Configure as Habit...", self) # Use a config-like icon
            config_habit_action.triggered.connect(self.configure_habit_action)
            menu.addAction(config_habit_action)

            menu.addSeparator()

            # Delete
            delete_action = QAction(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon), "Delete", self)
            delete_action.triggered.connect(self.delete_activity_action)
            menu.addAction(delete_action)

        menu.exec(self.activity_tree.viewport().mapToGlobal(position))

    def add_activity_action(self, parent_id=None):
        """Handler for the add activity action (from menu)."""
        parent_name_suffix = ""
        if parent_id:
            item = self._find_tree_item_by_id(parent_id)
            if item: parent_name_suffix = f" under '{item.text(0)}'"

        text, ok = QInputDialog.getText(self, "Add Activity", f"Enter name for the new activity{parent_name_suffix}:")
        if ok and text.strip():
            new_activity_id = self.db_manager.add_activity(text.strip(), parent_id)
            if new_activity_id is not None:
                self.load_activities() # Reload tree
                new_item = self._find_tree_item_by_id(new_activity_id)
                if new_item: self.activity_tree.setCurrentItem(new_item)
                # --- Emit Signal ---
                # Emitting here assumes adding *any* activity might be relevant
                # If only adding *habits* should trigger, check type before emitting
                self.habits_updated.emit()
                print("MainWindow emitted habits_updated after add.")
        elif ok: # Clicked OK, but text is empty
             QMessageBox.warning(self, "Error", "Activity name cannot be empty.")

    def rename_activity_action(self):
        """Handler for the rename activity action."""
        selected_item = self.activity_tree.currentItem()
        if not selected_item: return

        activity_id = selected_item.data(0, Qt.ItemDataRole.UserRole)
        # Get name without prefix if it exists
        current_display_name = selected_item.text(0)
        current_name = current_display_name.replace("[H] ", "", 1) if current_display_name.startswith("[H] ") else current_display_name

        parent_item = selected_item.parent()
        parent_id = parent_item.data(0, Qt.ItemDataRole.UserRole) if parent_item and self.activity_tree.indexOfTopLevelItem(parent_item) == -1 else None

        new_name, ok = QInputDialog.getText(self, "Rename Activity", "Enter new name:", QLineEdit.EchoMode.Normal, current_name)

        if ok and new_name.strip() and new_name.strip() != current_name:
             db_parent_id = self.db_manager.get_activity_parent_id(activity_id)
             if self.db_manager.update_activity_name(activity_id, new_name.strip(), db_parent_id):
                 # Update item text in the tree (keeping prefix if it was there)
                 prefix = "[H] " if current_display_name.startswith("[H] ") else ""
                 selected_item.setText(0, prefix + new_name.strip())
                 # Update status if it was the selected activity
                 if activity_id == self.current_activity_id:
                     self.current_activity_name = new_name.strip() # Store name without prefix
                     self.activity_selected(selected_item) # Will update status bar text
        elif ok and not new_name.strip():
             QMessageBox.warning(self, "Error", "Activity name cannot be empty.")

    # --- NEW: Configure Habit Action ---
    def configure_habit_action(self):
        """Handler for the configure habit action."""
        selected_item = self.activity_tree.currentItem()
        if not selected_item: return

        activity_id = selected_item.data(0, Qt.ItemDataRole.UserRole)
        # Get name without prefix for dialog title
        display_name = selected_item.text(0)
        activity_name = display_name.replace("[H] ", "", 1) if display_name.startswith("[H] ") else display_name

        # Get current config from DB for accuracy
        current_config = self.db_manager.get_activity_habit_config(activity_id)

        dialog = ConfigureHabitDialog(activity_id, activity_name, current_config, self.db_manager, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            print(f"Habit config potentially updated for {activity_name}. Reloading activities.")
            self.load_activities() # Reload tree
            new_item = self._find_tree_item_by_id(activity_id)
            if new_item: self.activity_tree.setCurrentItem(new_item)
            # --- Emit Signal ---
            self.habits_updated.emit()
            print("MainWindow emitted habits_updated after configure.")

    def delete_activity_action(self):
        """Handler for the delete activity action."""
        selected_item = self.activity_tree.currentItem()
        if not selected_item: return

        activity_id = selected_item.data(0, Qt.ItemDataRole.UserRole)
        activity_name = selected_item.text(0)
        base_activity_name = activity_name.replace("[H] ", "", 1) if activity_name.startswith("[H] ") else activity_name

        warning_message = ""
        all_descendants = self.db_manager.get_descendant_activity_ids(activity_id)
        descendant_count = len(all_descendants) - 1 if activity_id in all_descendants else len(all_descendants)

        if descendant_count > 0:
            warning_message = f"\n\nWARNING: This will also delete all {descendant_count} child activities!"

        # Add warning about associated data
        warning_message += "\nAll associated time entries and habit logs will also be deleted!"

        reply = QMessageBox.question(
            self, "Confirm Deletion",
            f"Are you sure you want to delete activity '{base_activity_name}' (ID: {activity_id})?{warning_message}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
             # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
             # Принимаем все три значения, игнорируем второе и третье
             was_habit, _, _ = self.db_manager.get_activity_habit_config(activity_id)
             # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

             is_habit = was_habit is not None and was_habit != HABIT_TYPE_NONE

             if self.db_manager.delete_activity(activity_id):
                 if activity_id == self.current_activity_id:
                     self.current_activity_id = None
                     self.current_activity_name = None
                 self.load_activities() # Reload tree
                 if is_habit:
                      self.habits_updated.emit()
                      print("MainWindow emitted habits_updated after delete.")
             else:
                 QMessageBox.critical(self, "Deletion Error", f"Failed to delete activity '{base_activity_name}'. Check console for details.")

    def _find_tree_item_by_id(self, activity_id):
        """Helper method to find a QTreeWidgetItem by activity ID."""
        if activity_id is None: return None
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
            # Get name without prefix
            display_name = current_item.text(0)
            self.current_activity_name = display_name.replace("[H] ", "", 1) if display_name.startswith("[H] ") else display_name

            # Calculate average time only for *this* specific activity
            avg_duration_specific = self.db_manager.calculate_average_duration(self.current_activity_id)
            # Calculate total time for the branch (including children) - just for info
            total_duration_branch = self.db_manager.calculate_total_duration_for_activity_branch(self.current_activity_id)

            avg_text = f"Avg: {self.format_time(None, avg_duration_specific)}" if avg_duration_specific > 0 else "Avg: N/A"
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

    # --- NEW Slot to open Habit Tracker ---
    def open_habit_tracker(self):
        """Opens the 'Habit Tracker' dialog."""
        # Pass self as parent so dialog can connect to signal
        dialog = HabitTrackerDialog(self.db_manager, self)
        dialog.exec()
        # No need to reload activities here unless the dialog modifies them globally

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

    def start_work_timer(self):
        """Starts the 'Work' timer."""
        if self.timer_type is not None or not self.current_activity_id: return
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
        self.work_timer_button.setText("Stop Countdown")
        self.work_timer_button.setChecked(True)
        self.work_timer_button.setEnabled(True)
        self.set_controls_enabled(False)
        self.status_label.setText(f"Countdown: {self.current_activity_name} (from {self.format_time(None, self.countdown_average_duration)})")

    def stop_timer_logic(self):
        """Common logic for stopping any type of timer, includes habit logging prompt."""
        if not self.qtimer.isActive(): return
        self.qtimer.stop()
        self.timer_window.hide()
        self.timer_window.set_overrun(False)
        stop_time = time.time()
        actual_duration = int(stop_time - self.start_time) if self.start_time else 0

        # Save state before resetting
        saved_activity_id = self.current_activity_id
        saved_activity_name = self.current_activity_name # Name without prefix
        timer_stopped_type = self.timer_type
        avg_duration_at_start = self.average_duration_at_countdown_start

        # Reset timer state
        self.timer_type = None
        self.start_time = None
        self.countdown_average_duration = 0
        self.average_duration_at_countdown_start = 0
        needs_ui_update = False # Flag if status bar needs refresh

        # Saving logic for time_entries
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
                 # Check if we should prompt to save the time entry result
                 if self.check_and_prompt_save_countdown(actual_duration, saved_activity_id, saved_activity_name, avg_duration_at_start):
                     needs_ui_update = True # Saved time entry, need to update UI
             else:
                  print("Countdown timer stopped without saving (duration 0 or no activity selected).")

        # --- NEW: Habit Logging Prompt ---
        if saved_activity_id is not None and actual_duration >= 0: # Prompt even if duration is 0, as user intended to do it
             habit_config = self.db_manager.get_activity_habit_config(saved_activity_id)
             habit_type = habit_config[0] if habit_config else None

             if habit_type is not None and habit_type != HABIT_TYPE_NONE:
                 self.prompt_and_log_habit_after_timer(saved_activity_id, saved_activity_name, habit_config, actual_duration)
                 # Note: Habit logging doesn't affect average time calculation shown in status bar, so no 'needs_ui_update' here.

        # Restore button states and controls
        self.work_timer_button.setText("Start Tracking")
        self.work_timer_button.setChecked(False)
        self.set_controls_enabled(True) # Unlock controls AFTER potentially logging habit

        # Explicitly update selected activity status if time entry data was saved
        if needs_ui_update:
             current = self.activity_tree.currentItem()
             if current:
                 self.activity_selected(current) # Re-select to refresh the status bar
             else:
                 self.activity_selected(None)

    # --- NEW: Helper for Habit Logging after Timer Stop ---
    def prompt_and_log_habit_after_timer(self, activity_id, activity_name, habit_config, actual_duration_seconds):
        habit_type, habit_unit, _ = habit_config
        today_str = QDate.currentDate().toString("yyyy-MM-dd")

        reply = QMessageBox.question(
            self, "Log Habit?",
            f"Activity '{activity_name}' is also tracked as a habit.\n\n"
            f"Would you like to log its completion for today ({today_str}) based on the session?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return # User declined

        new_value = None
        ok_to_log = False

        # --- Binary ---
        if habit_type == HABIT_TYPE_BINARY:
             bin_reply = QMessageBox.question(self, "Confirm Habit", f"Mark habit '{activity_name}' as DONE for today?",
                                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
             if bin_reply == QMessageBox.StandardButton.Yes:
                 new_value = 1.0
                 ok_to_log = True

        # --- Percentage ---
        elif habit_type == HABIT_TYPE_PERCENTAGE:
             # Use a simple dialog with buttons for percentages
             percent_dialog = QDialog(self)
             percent_dialog.setWindowTitle(f"Log Percentage: {activity_name}")
             p_layout = QVBoxLayout(percent_dialog)
             p_layout.addWidget(QLabel(f"How much of '{activity_name}' did you complete today?"))
             btn_layout = QHBoxLayout()
             result = {'value': None} # Use dict to pass value out of lambda

             percentages = [25.0, 50.0, 75.0, 100.0]
             for p in percentages:
                 button = QPushButton(f"{p:g}%")
                 # Need lambda default arg trick to capture current 'p'
                 button.clicked.connect(lambda checked=False, pct=p: (result.update({'value': pct}), percent_dialog.accept()))
                 btn_layout.addWidget(button)

             p_layout.addLayout(btn_layout)
             cancel_button = QPushButton("Cancel")
             cancel_button.clicked.connect(percent_dialog.reject)
             p_layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignRight)

             if percent_dialog.exec() == QDialog.DialogCode.Accepted and result['value'] is not None:
                 new_value = result['value']
                 ok_to_log = True

        # --- Numeric ---
        elif habit_type == HABIT_TYPE_NUMERIC:
             prompt_text = f"Enter value for '{activity_name}'"
             if habit_unit: prompt_text += f" ({habit_unit})"
             prompt_text += f" for {today_str}:"

             # Pre-fill with duration if unit seems time-related
             default_value = 0.0
             if habit_unit and habit_unit.lower() in ['minutes', 'min', 'm']:
                 default_value = round(actual_duration_seconds / 60.0, 2)
             elif habit_unit and habit_unit.lower() in ['hours', 'hrs', 'h']:
                 default_value = round(actual_duration_seconds / 3600.0, 2)
             elif habit_unit and habit_unit.lower() in ['seconds', 'sec', 's']:
                 default_value = float(actual_duration_seconds)

             num_value, ok = QInputDialog.getDouble(
                 self, "Log Numeric Habit", prompt_text,
                 value=default_value,
                 min=-999999.0, max=999999.0, decimals=2 # Adjust as needed
             )
             if ok:
                 new_value = num_value
                 ok_to_log = True

        # --- Log if confirmed ---
        if ok_to_log:
            if self.db_manager.log_habit(activity_id, today_str, new_value):
                 QMessageBox.information(self, "Habit Logged", f"Habit '{activity_name}' logged successfully for today.")
                 # --- Emit Signal ---
                 self.habits_updated.emit()
                 print("MainWindow emitted habits_updated after timer log.")
            else:
                 QMessageBox.warning(self, "Error", f"Failed to log habit '{activity_name}'.")

    def check_and_prompt_save_countdown(self, actual_duration, activity_id, activity_name, average_duration_at_start):
        """Checks if the countdown time significantly differs from the average and prompts to save time entry."""
        if actual_duration <= 0 or activity_id is None or average_duration_at_start <= 0:
            return False # Nothing to save or compare

        entry_count = self.db_manager.get_entry_count(activity_id)

        if entry_count >= COUNTDOWN_MIN_ENTRIES_FOR_SAVE:
            difference_ratio = abs(actual_duration - average_duration_at_start) / average_duration_at_start
            if difference_ratio > COUNTDOWN_SAVE_THRESHOLD:
                percentage_diff = int(difference_ratio * 100)
                formatted_actual = self.format_time(None, actual_duration)
                formatted_average = self.format_time(None, average_duration_at_start)
                direction = 'more' if actual_duration > average_duration_at_start else 'less'

                reply = QMessageBox.question(
                    self, "Save Time Entry?", # Changed title for clarity
                    f"Countdown session for '{activity_name}' lasted {formatted_actual}, "
                    f"which is {percentage_diff}% {direction} than the planned average ({formatted_average}).\n\n"
                    f"Add this duration ({formatted_actual}) as a new time entry?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
                )

                if reply == QMessageBox.StandardButton.Yes:
                    print(f"Saving countdown result as time entry: {actual_duration} sec for ID {activity_id}.")
                    if self.db_manager.add_time_entry(activity_id, actual_duration):
                        return True # Successfully saved time entry
                    else:
                        QMessageBox.warning(self, "Error", "Failed to save time entry.")
                        return False # Error saving
        # Didn't prompt or user declined saving time entry
        return False

    def update_timer(self):
        """Updates the time display in the timer window."""
        if self.start_time is None or self.timer_type is None:
            self.qtimer.stop() # Stop timer if state is inconsistent
            return

        elapsed = time.time() - self.start_time

        if self.timer_type == 'work':
            self.timer_window.setText(self.format_time(None, elapsed))
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
        # Habit config menu item is handled by activity tree context menu logic

        # Enable standard management buttons if controls are generally enabled
        if self.snapshot_button:
             self.snapshot_button.setEnabled(enabled)
        if self.habit_tracker_button:
             self.habit_tracker_button.setEnabled(enabled)

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
        if self.qtimer.isActive(): # Проверяем ОСНОВНОЙ таймер работы/обратного отсчета
            reply = QMessageBox.question(
                self, "Timer Active",
                "The timer is still running. Stop the timer and exit?\n"
                "(Current progress might be saved or prompted for saving)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_timer_logic() # Останавливаем основной таймер
            else:
                event.ignore() # Отменяем закрытие окна
                return

        # --- Close main application resources ---
        self.db_manager.close()
        self.timer_window.close() # Закрываем маленькое окно таймера
        # --- Убедитесь, что здесь НЕТ self.flash_timer.stop() или self.grid_animation_timer.stop() ---
        print("Application closing.")
        event.accept() # Разрешаем закрытие окна
        
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