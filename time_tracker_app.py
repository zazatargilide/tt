import sys
from functools import partial
import uuid
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
pyqtSignal, QTimer, QRectF, QEvent, QPoint, QDateTime, QLocale
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

    def calculate_average_session_times(self, activity_id):
        """
        Calculates average work, break, and total time per session for an activity.
        A session is defined by having the same session_id.
        Returns a tuple: (avg_work_seconds, avg_break_seconds, avg_total_seconds)
        Returns (0, 0, 0) if no sessions with session_id are found.
        """
        if not self.conn or not activity_id:
            return (0, 0, 0)

        # Используем Common Table Expression (CTE) для удобства
        query = """
        WITH SessionDurations AS (
            SELECT
                session_id, -- Группируем по ID сессии
                SUM(CASE WHEN entry_type = 'work' THEN duration_seconds ELSE 0 END) as work_duration, -- Суммируем 'work' в рамках сессии
                SUM(CASE WHEN entry_type = 'break' THEN duration_seconds ELSE 0 END) as break_duration -- Суммируем 'break' в рамках сессии
            FROM time_entries
            WHERE activity_id = ? AND session_id IS NOT NULL -- Учитываем только записи с session_id для нужной активности
            GROUP BY session_id -- Группируем по сессиям
            HAVING work_duration > 0 OR break_duration > 0 -- Исключаем сессии с нулевой длительностью (если такие есть)
        )
        -- Считаем среднее по всем найденным сессиям
        SELECT
            AVG(work_duration),
            AVG(break_duration),
            AVG(work_duration + break_duration) -- Среднее общее время сессии
        FROM SessionDurations;
        """
        try:
            self.cursor.execute(query, (activity_id,))
            result = self.cursor.fetchone()
            # AVG вернет None, если в SessionDurations не было строк, или если все значения были NULL
            if result and result[0] is not None: # Проверяем, что AVG вернул не NULL (хотя бы одна сессия была)
                # Заменяем возможный None (если были только 'break' или только 'work' сессии) на 0
                avg_work = result[0] or 0
                avg_break = result[1] or 0
                avg_total = result[2] or 0
                return (avg_work, avg_break, avg_total)
            else:
                # Не найдено сессий с session_id или все сессии были нулевой длины
                return (0, 0, 0)
        except sqlite3.Error as e:
            print(f"Error calculating average session times for activity {activity_id}: {e}")
            return (0, 0, 0)

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
            # Activities table (без изменений)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    parent_id INTEGER DEFAULT NULL,
                    habit_type INTEGER DEFAULT NULL,
                    habit_unit TEXT DEFAULT NULL,
                    habit_sort_order INTEGER,
                    habit_goal REAL DEFAULT NULL,
                    FOREIGN KEY (parent_id) REFERENCES activities (id) ON DELETE SET NULL
                )
            ''')
            self._add_column_if_not_exists('activities', 'habit_type', 'INTEGER DEFAULT NULL')
            self._add_column_if_not_exists('activities', 'habit_unit', 'TEXT DEFAULT NULL')
            self._add_column_if_not_exists('activities', 'habit_sort_order', 'INTEGER')
            self._add_column_if_not_exists('activities', 'habit_goal', 'REAL DEFAULT NULL')

            # Time Entries Table - <<< ИЗМЕНЕНИЯ ЗДЕСЬ >>>
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS time_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_id INTEGER NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    entry_type TEXT DEFAULT 'work' NOT NULL CHECK(entry_type IN ('work', 'break')), -- НОВОЕ ПОЛЕ
                    session_id REAL, -- НОВОЕ ПОЛЕ (ID сессии, можно хранить float time.time())
                    FOREIGN KEY (activity_id) REFERENCES activities (id) ON DELETE CASCADE
                )
            ''')
            # Добавляем новые колонки, если их нет
            self._add_column_if_not_exists('time_entries', 'entry_type', "TEXT DEFAULT 'work' NOT NULL CHECK(entry_type IN ('work', 'break'))")
            self._add_column_if_not_exists('time_entries', 'session_id', 'REAL')
            # <<< КОНЕЦ ИЗМЕНЕНИЙ >>>

            # Habit Logs Table (без изменений)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS habit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_id INTEGER NOT NULL,
                    log_date TEXT NOT NULL,
                    value REAL,
                    UNIQUE(activity_id, log_date),
                    FOREIGN KEY (activity_id) REFERENCES activities (id) ON DELETE CASCADE
                )
            ''')

            # Indexes (Добавлен индекс для session_id)
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_parent_id ON activities (parent_id);')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_habit_type ON activities (habit_type);')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_habit_sort_order ON activities (habit_sort_order);')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_id_timestamp ON time_entries (activity_id, timestamp);')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp_date ON time_entries (timestamp);')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_habit_logs_date_activity ON habit_logs (log_date, activity_id);')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_time_entries_session_id ON time_entries (session_id);') # Новый индекс

            self.conn.commit()
            print("Tables checked/created/updated (with entry_type, session_id).")
            self._initialize_habit_order()

        except sqlite3.Error as e:
            print(f"Error creating/updating tables: {e}")
            if self.conn: self.conn.rollback()

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
        if not self.conn or not name:
            print("DB_ADD_ACTIVITY_ERROR: No connection or name provided.")
            return None
        name_stripped = name.strip() # Ensure name is stripped before checks and insert
        if not name_stripped:
            print("DB_ADD_ACTIVITY_ERROR: Name is empty after stripping.")
            return None

        # Check for duplicate name under the same parent first
        if self._check_activity_name_exists(name_stripped, parent_id):
            print(f"DB_ADD_ACTIVITY_WARN: Activity '{name_stripped}' already exists with the same parent (parent_id: {parent_id}).")
            # QMessageBox is a UI element, ideally not called directly from DB Manager.
            # This warning should be handled by the caller (MainWindow) if desired.
            # For now, we just print and return None.
            # QMessageBox.warning(None, "Duplicate", f"An activity named '{name_stripped}' already exists in this branch.")
            return None

        try:
            # --- EXTENDED DEBUGGING ---
            debug_msg_parts = [
                f"DB_ADD_ACTIVITY_ATTEMPT: Inserting '{name_stripped}'",
                f"with parent_id: {parent_id}",
                f"(type: {type(parent_id)})."
            ]

            if parent_id is not None:
                # Explicitly check if the parent_id exists in the activities table
                self.cursor.execute("SELECT 1 FROM activities WHERE id = ?", (parent_id,))
                parent_exists_in_db = self.cursor.fetchone()
                if parent_exists_in_db:
                    debug_msg_parts.append("Parent ID check: EXISTS in DB.")
                else:
                    # This is the most likely cause of FOREIGN KEY constraint failed
                    debug_msg_parts.append("Parent ID check: DOES NOT EXIST in DB! <<< LIKELY CAUSE OF ERROR")
            else:
                debug_msg_parts.append("Parent ID is None (top-level activity).")
            
            print(" ".join(debug_msg_parts))
            # --- END EXTENDED DEBUGGING ---

            self.cursor.execute("INSERT INTO activities (name, parent_id) VALUES (?, ?)", (name_stripped, parent_id))
            self.conn.commit()
            new_id = self.cursor.lastrowid
            print(f"DB_ADD_ACTIVITY_SUCCESS: Activity '{name_stripped}' (ID: {new_id}, parent_id: {parent_id}) added.")
            return new_id
        except sqlite3.Error as e:
            error_message = f"DB_ADD_ACTIVITY_ERROR: Error adding activity '{name_stripped}' with parent_id {parent_id}: {e}"
            print(error_message)
            # If it's a foreign key error, let's get more info about existing IDs for context
            if "FOREIGN KEY constraint failed" in str(e):
                try:
                    self.cursor.execute("SELECT id FROM activities ORDER BY id DESC LIMIT 10")
                    recent_ids = self.cursor.fetchall()
                    print(f"DB_ADD_ACTIVITY_DEBUG: Recent activity IDs in DB: {recent_ids}")
                    if parent_id is not None:
                         self.cursor.execute("SELECT * FROM activities WHERE id = ?", (parent_id,))
                         parent_row_details = self.cursor.fetchone()
                         print(f"DB_ADD_ACTIVITY_DEBUG: Details for attempted parent_id {parent_id} in DB: {parent_row_details}")

                except Exception as query_e:
                    print(f"DB_ADD_ACTIVITY_DEBUG: Could not fetch debug info on error: {query_e}")
            self.conn.rollback() # Ensure rollback on any error
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

    def add_time_entry(self, activity_id, duration_seconds, timestamp=None, entry_type='work', session_id=None):
        """
        Добавляет запись времени (работы или перерыва).
        Можно указать timestamp (локальный QDateTime), тип записи и ID сессии.
        """
        if not self.conn or activity_id is None or duration_seconds < 0:
            if duration_seconds < 0: print("Warning: Attempted to add negative duration entry.")
            return False
        duration_seconds = int(duration_seconds)
        if entry_type not in ('work', 'break'):
            print(f"Warning: Invalid entry_type '{entry_type}'. Defaulting to 'work'.")
            entry_type = 'work'

        try:
            ts_str_for_db = None
            # Обработка timestamp (если передан)
            if timestamp:
                if not isinstance(timestamp, QDateTime):
                    try: timestamp = QDateTime.fromString(str(timestamp), "yyyy-MM-dd HH:mm:ss")
                    except Exception: timestamp = None
                if timestamp and timestamp.isValid():
                    utc_dt = timestamp.toUTC()
                    ts_str_for_db = utc_dt.toString("yyyy-MM-dd HH:mm:ss")

            # Собираем SQL и параметры
            # Используем CURRENT_TIMESTAMP базы данных, если timestamp не передан
            sql = """
                INSERT INTO time_entries (activity_id, duration_seconds, entry_type, session_id, timestamp)
                VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """
            # Если ts_str_for_db есть, он подставится вместо COALESCE(?, ...)
            # Если ts_str_for_db is None, COALESCE(NULL, CURRENT_TIMESTAMP) вернет CURRENT_TIMESTAMP
            params = (activity_id, duration_seconds, entry_type, session_id, ts_str_for_db)

            self.cursor.execute(sql, params)
            self.conn.commit()

            ts_info = f"с timestamp (UTC) {ts_str_for_db}" if ts_str_for_db else "с текущим timestamp (UTC)"
            print(f"Запись времени ({entry_type}, {duration_seconds} сек, sess:{session_id}) добавлена для activity_id {activity_id} {ts_info}.")
            return True
        except sqlite3.Error as e:
            print(f"Ошибка добавления записи времени ({entry_type}): {e}")
            if self.conn:
                try: self.conn.rollback()
                except sqlite3.Error as rb_err: print(f"Ошибка при откате транзакции: {rb_err}")
            return False

    def get_entries_for_date_with_type(self, date_str):
        """Gets all time entries for a date, including entry type."""
        if not self.conn or not date_str: return []
        try:
            # Добавляем te.entry_type в SELECT
            self.cursor.execute("""
                SELECT a.id, a.name, te.duration_seconds, te.entry_type,
                       strftime('%Y-%m-%d %H:%M:%S', te.timestamp) as timestamp_str,
                       te.session_id -- Также получаем ID сессии
                FROM time_entries te JOIN activities a ON te.activity_id = a.id
                WHERE DATE(te.timestamp) = ?
                ORDER BY te.timestamp ASC, a.name ASC
            """, (date_str,))
            # Возвращает кортежи (id, name, duration, type, timestamp_str, session_id)
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Error retrieving entries with type for date {date_str}: {e}")
            return []

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
        """
        Gets all time entries (id, duration, timestamp_str_utc, entry_type) for *this* activity.
        Returns timestamp as UTC string.
        """
        if not self.conn or not activity_id: return []
        try:
            self.cursor.execute(
                """SELECT id, duration_seconds,
                          strftime('%Y-%m-%d %H:%M:%S', timestamp) as timestamp_str_utc,
                          entry_type
                   FROM time_entries
                   WHERE activity_id = ?
                   ORDER BY timestamp DESC""",
                (activity_id,)
            )
            # Returns list of tuples: [(id, duration, timestamp_str_utc, entry_type), ...]
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Error retrieving detailed time entries for activity {activity_id}: {e}")
            return []

    def update_time_entry(self, entry_id, new_duration_seconds=None, new_timestamp_qdatetime=None, new_entry_type=None):
        """
        Updates an existing time entry.
        Allows updating duration, timestamp, and/or entry_type.
        new_timestamp_qdatetime should be a QDateTime object (assumed to be local time).
        """
        if not self.conn or not entry_id:
            return False

        fields_to_update = []
        params = []

        if new_duration_seconds is not None:
            if int(new_duration_seconds) <= 0:
                print("Error: New duration must be positive.")
                return False
            fields_to_update.append("duration_seconds = ?")
            params.append(int(new_duration_seconds))

        if new_timestamp_qdatetime is not None and isinstance(new_timestamp_qdatetime, QDateTime) and new_timestamp_qdatetime.isValid():
            utc_dt = new_timestamp_qdatetime.toUTC()
            timestamp_str_utc = utc_dt.toString("yyyy-MM-dd HH:mm:ss")
            fields_to_update.append("timestamp = ?")
            params.append(timestamp_str_utc)
        elif new_timestamp_qdatetime is not None: 
             print(f"Warning: Invalid QDateTime provided for timestamp update of entry {entry_id}. Timestamp not updated.")


        if new_entry_type is not None:
            if new_entry_type not in ('work', 'break'):
                print(f"Error: Invalid entry_type '{new_entry_type}'. Must be 'work' or 'break'.")
                return False
            fields_to_update.append("entry_type = ?")
            params.append(new_entry_type)

        if not fields_to_update:
            print(f"No valid fields provided to update for entry ID {entry_id}.")
            return False 

        params.append(entry_id) 

        sql = f"UPDATE time_entries SET {', '.join(fields_to_update)} WHERE id = ?"

        try:
            print(f"Executing SQL for update: {sql} with params {params}") 
            self.cursor.execute(sql, tuple(params))
            self.conn.commit()
            if self.cursor.rowcount > 0:
                print(f"Time entry ID {entry_id} updated successfully. Fields: {fields_to_update}")
                return True
            else:
                print(f"Time entry ID {entry_id} not found for update, or no data changed.")
                return False 
        except sqlite3.Error as e:
            print(f"Error updating time entry ID {entry_id}: {e}")
            self.conn.rollback()
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
            label_text = locale.dayName(qt_day_of_week, QLocale.FormatType.NarrowFormat) # Может дать "П", "В", "С" и т.д. (зависит от локали)
            # Или определить вручную (не зависит от локали):
            # single_letter_days = ["ᛗ", "ᛏ", "ᛟ", "ᚦ", "ᚠ", "ᛚ", "ᛋ"] # Пн -> Вс
            # label_text = single_letter_days[i]
            #  -- Конец опциональной части ---

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

class TimerWindow(QWidget):
    # Сигналы для MainWindow
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    end_requested = pyqtSignal()

    # Состояния окна (для управления UI)
    STATE_TRACKING = 0
    STATE_PAUSED = 1

    def __init__(self, initial_color=QColor(0, 0, 0, 180), parent=None):
        super().__init__(parent)
        self._activity_name = "Activity" # Будет установлено позже
        self._background_color = initial_color
        self._display_color = initial_color
        self.state = self.STATE_TRACKING # Начальное состояние
        self.is_overrun = False
        self.overrun_seconds = 0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        # --- Верхняя метка (для Total Work/Total Pause) ---
        self.info_label = QLabel("Total Work: 00:00:00", self) # Начальный текст
        info_font = QFont()
        info_font.setPointSize(8)
        self.info_label.setFont(info_font)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("QLabel { color : white; background-color: transparent; }")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        # --- Главная метка времени (для текущего интервала или статуса паузы) ---
        self.time_label = QLabel("00:00:00", self)
        time_font = QFont()
        time_font.setPointSize(16)
        time_font.setBold(True)
        self.time_label.setFont(time_font)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet("QLabel { color : white; background-color: transparent; padding-bottom: 2px; }")
        layout.addWidget(self.time_label)

        # --- Кнопки ---
        button_layout = QHBoxLayout()
        button_layout.setSpacing(5)
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.end_button = QPushButton("End")

        button_style = """
            QPushButton {
                background-color: rgba(85, 85, 85, 180); border: 1px solid #555;
                color: white; padding: 2px 6px; border-radius: 3px; font-size: 9pt;
                min-width: 50px;
            }
            QPushButton:hover { background-color: rgba(100, 100, 100, 200); }
            QPushButton:pressed { background-color: rgba(120, 120, 120, 220); }
        """
        # ... (установка стиля и курсора для кнопок как в пред. версии) ...
        self.pause_button.setStyleSheet(button_style)
        self.resume_button.setStyleSheet(button_style)
        self.end_button.setStyleSheet(button_style)
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resume_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.end_button.setCursor(Qt.CursorShape.PointingHandCursor)

        # Подключаем сигналы кнопок к сигналам окна
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.resume_button.clicked.connect(self.resume_requested.emit)
        self.end_button.clicked.connect(self.end_requested.emit)

        button_layout.addWidget(self.pause_button)
        button_layout.addWidget(self.resume_button)
        button_layout.addWidget(self.end_button)
        layout.addLayout(button_layout)
        # --- Конец кнопок ---
        
        self.layout().setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize) # or QHBoxLayout, etc.
        self.setFixedSize(280, 150)
    
        self._mouse_press_pos = None
        self._mouse_move_pos = None

        self._update_button_visibility() # Устанавливаем видимость кнопок по состоянию
        self.update_background_color()
        # Tooltip будет установлен из MainWindow при создании

    def set_background_color(self, color: QColor):
        self._background_color = color
        self.update_background_color()

    def _set_internal_state(self, new_state):
        """Только изменяет внутреннее состояние и обновляет UI кнопок/фона."""
        if self.state != new_state:
            self.state = new_state
            self._update_button_visibility()
            self.update_background_color() # Обновляем фон при смене состояния

    def _update_button_visibility(self):
        """Показывает/скрывает кнопки Pause/Resume."""
        is_tracking = (self.state == self.STATE_TRACKING)
        self.pause_button.setVisible(is_tracking)
        self.resume_button.setVisible(not is_tracking)

    def _get_elided_text(self, label: QLabel, text: str, available_width_offset: int = 12) -> str:
        # Estimate available width for the label.
        # Window width 185. Default QVBoxLayout margins are (6,4,6,4) = 12 horizontal.
        # You might need to adjust available_width_offset based on your specific layout.
        # It's safer to calculate it from self.layout().contentsMargins() if possible,
        # but for a fixed size window, a fixed offset is often okay.
        available_width = self.width() - available_width_offset # Use actual window width
        
        # If the label itself has margins, subtract those too.
        # For simplicity, we'll use the window's content rect width.
        # available_width = 185 - self.layout().contentsMargins().left() - self.layout().contentsMargins().right()

        fm = label.fontMetrics()
        elided_text = fm.elidedText(text, Qt.TextElideMode.ElideRight, available_width)
        return elided_text

    def event(self, event: QEvent) -> bool:
        # Try to get a unique identifier for the window, e.g., activity name from info_label
        activity_name_for_log = "UnknownActivity"
        try:
            # This might be risky if info_label text isn't set yet or in expected format
            activity_name_for_log = self.info_label.text().split('\n')[0] if self.info_label and self.info_label.text() else self._activity_name
        except Exception:
            pass # Keep default if parsing fails

        if event.type() == QEvent.Type.WindowActivate:
            print(f"DEBUG: TimerWindow for '{activity_name_for_log}' Event: WindowActivate")
        elif event.type() == QEvent.Type.WindowDeactivate:
            print(f"DEBUG: TimerWindow for '{activity_name_for_log}' Event: WindowDeactivate")
        elif event.type() == QEvent.Type.FocusIn:
            print(f"DEBUG: TimerWindow for '{activity_name_for_log}' Event: FocusIn")
        elif event.type() == QEvent.Type.FocusOut:
            print(f"DEBUG: TimerWindow for '{activity_name_for_log}' Event: FocusOut")
        elif event.type() == QEvent.Type.Paint:
             # This will be VERY verbose, only enable for deep debugging of repaint issues
             # print(f"DEBUG: TimerWindow for '{activity_name_for_log}' Event: Paint")
             pass
        return super().event(event)

    def showTrackingState(self, current_interval_str, total_work_str, activity_name):
        # print(f"DEBUG: TimerWindow '{activity_name}': showTrackingState called with interval='{current_interval_str}', total='{total_work_str}'") # Verbose
        if self.state != self.STATE_TRACKING:
            self._set_internal_state(self.STATE_TRACKING)
        elided_name = self._get_elided_text(self.info_label, activity_name)
        self.info_label.setText(f"{elided_name}\nTotal Work: {total_work_str}")
        self.time_label.setText(current_interval_str)
        self.setToolTip(f"Tracking: {activity_name}\nTotal Work: {total_work_str}\nCurrent Interval: {current_interval_str}")

    def showPausedState(self, current_break_str, total_break_str, activity_name):
        # print(f"DEBUG: TimerWindow '{activity_name}': showPausedState called with break='{current_break_str}', total='{total_break_str}'") # Verbose
        if self.state != self.STATE_PAUSED:
            self._set_internal_state(self.STATE_PAUSED)
        elided_name = self._get_elided_text(self.info_label, activity_name)
        self.info_label.setText(f"{elided_name}\nTotal Pause: {total_break_str}")
        self.time_label.setText(f"Paused: {current_break_str}")
        self.setToolTip(f"Paused: {activity_name}\nTotal Pause: {total_break_str}\nCurrent Break: {current_break_str}")
    
    def set_overrun(self, overrun, seconds=0): # Для countdown
        needs_update = (self.is_overrun != overrun) or (self.overrun_seconds != seconds)
        self.is_overrun = overrun
        self.overrun_seconds = seconds if overrun else 0
        if needs_update:
            self.update_background_color() # Только обновляем цвет, текст ставит MainWindow

    def update_background_color(self):
        """Обновляет цвет фона."""
        if self.is_overrun: # Приоритет у overrun для countdown
            red_factor = min(1.0, self.overrun_seconds / MAX_OVERRUN_SECONDS_FOR_RED)
            red_component = int(red_factor * 180)
            self._display_color = QColor(red_component, 0, 0, 200)
        elif self.state == self.STATE_PAUSED:
            # Затемняем базовый цвет окна на паузе
            self._display_color = self._background_color.darker(135) # Сделаем чуть темнее
        else: # Стандартное состояние работы
            self._display_color = self._background_color

        self.update() # Запросить перерисовку

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self._display_color))
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        border_radius = 10.0
        rect = QRectF(self.rect())
        rect.adjust(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rect, border_radius, border_radius)

    # mousePressEvent, mouseMoveEvent, mouseReleaseEvent - без изменений
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
        self.entries_table.setColumnCount(4) # CHANGED from 3 to 4
        self.entries_table.setHorizontalHeaderLabels(["ID", "Duration", "Type", "Date & Time"]) # ADDED "Type"
        self.entries_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.entries_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.entries_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.entries_table.verticalHeader().setVisible(False)
        header = self.entries_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # ID
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents) # Duration
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Type (NEW)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)          # Date & Time (was index 2)
        self.entries_table.setSortingEnabled(True)
        self.entries_table.sortByColumn(3, Qt.SortOrder.DescendingOrder) # Sort by new timestamp column index
        self.entries_table.doubleClicked.connect(self.edit_selected_entry)
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
        """Loads entries into the QTableWidget, storing necessary data for editing."""
        self.entries_table.setSortingEnabled(False) 
        self.entries_table.setRowCount(0)

        entries = self.db_manager.get_time_entries_for_activity(self.activity_id) # Uses updated DB method

        buttons_to_disable = ["Edit", "Delete"]

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
        # entries are now (entry_id, duration_seconds, timestamp_str_utc, entry_type)
        for row, entry_tuple in enumerate(entries):
            entry_id, duration_seconds, timestamp_str_utc, entry_type = entry_tuple

            formatted_duration = MainWindow.format_time(None, duration_seconds)
            dt_utc = QDateTime.fromString(timestamp_str_utc, "yyyy-MM-dd HH:mm:ss")
            dt_utc.setTimeSpec(Qt.TimeSpec.UTC)
            dt_local = dt_utc.toLocalTime()
            formatted_timestamp_display = dt_local.toString("yyyy-MM-dd HH:mm:ss")

            id_item = QTableWidgetItem(str(entry_id))
            id_item.setData(Qt.ItemDataRole.UserRole, {
                'entry_id': entry_id,
                'duration_seconds': duration_seconds,
                'timestamp_qdatetime': dt_local, 
                'entry_type': entry_type
            })
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            duration_item = QTableWidgetItem(formatted_duration)
            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            duration_item.setData(Qt.ItemDataRole.UserRole, duration_seconds)

            type_item = QTableWidgetItem(entry_type.capitalize() if entry_type else "N/A") 
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            timestamp_item = QTableWidgetItem(formatted_timestamp_display)
            timestamp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.entries_table.setItem(row, 0, id_item)
            self.entries_table.setItem(row, 1, duration_item)
            self.entries_table.setItem(row, 2, type_item) 
            self.entries_table.setItem(row, 3, timestamp_item)

        self.entries_table.setSortingEnabled(True)
        self.entries_table.sortByColumn(3, Qt.SortOrder.DescendingOrder)

    def get_selected_entry_data(self):
        """Returns the data dictionary of the selected entry."""
        selected_rows = self.entries_table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        selected_row_index = selected_rows[0].row()
        id_item = self.entries_table.item(selected_row_index, 0)
        if not id_item:
            return None
        return id_item.data(Qt.ItemDataRole.UserRole)

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
        dialog = AddEditEntryDialog(self.db_manager, self.activity_id, self.activity_name, entry_data=None, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_entry_data()
            if data:
                if self.db_manager.add_time_entry(
                    self.activity_id,
                    data['duration_seconds'],
                    timestamp=data['timestamp_qdatetime'], 
                    entry_type=data['entry_type'],
                    session_id=None 
                ):
                    self.needs_update = True
                    self.load_entries()
                    if hasattr(self.parent(), 'update_ui_for_selection'):
                         self.parent().update_ui_for_selection()
                    if hasattr(self.parent(), 'habits_updated'): 
                         self.parent().habits_updated.emit()
                else:
                    QMessageBox.warning(self, "Error", "Failed to add entry to the database.")

    def edit_selected_entry(self):
        selected_data = self.get_selected_entry_data() 

        if selected_data is None:
            QMessageBox.information(self, "Information", "Please select an entry in the table first.")
            return

        entry_id_to_edit = selected_data['entry_id']
        dialog = AddEditEntryDialog(self.db_manager, self.activity_id, self.activity_name, entry_data=selected_data, parent=self)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_entry_data()
            if new_data:
                changed = (new_data['duration_seconds'] != selected_data['duration_seconds'] or
                           new_data['timestamp_qdatetime'] != selected_data['timestamp_qdatetime'] or
                           new_data['entry_type'] != selected_data['entry_type'])

                if changed:
                    if self.db_manager.update_time_entry(
                        entry_id_to_edit,
                        new_duration_seconds=new_data['duration_seconds'],
                        new_timestamp_qdatetime=new_data['timestamp_qdatetime'],
                        new_entry_type=new_data['entry_type']
                    ):
                        self.needs_update = True
                        self.load_entries()
                        if hasattr(self.parent(), 'update_ui_for_selection'):
                             self.parent().update_ui_for_selection()
                        if hasattr(self.parent(), 'habits_updated'):
                             self.parent().habits_updated.emit()
                    else:
                        QMessageBox.warning(self, "Error", "Failed to update entry in the database.")
                else:
                    print("No changes detected for the entry.")
            # Removed 'else' for invalid data as AddEditEntryDialog handles it'

    def delete_selected_entry(self):
        selected_data = self.get_selected_entry_data() # This now returns a dictionary or None

        if selected_data is None or 'entry_id' not in selected_data: # Check if data is valid and has entry_id
            QMessageBox.information(self, "Information", "Please select an entry in the table first.")
            return

        entry_id = selected_data['entry_id'] # Get entry_id from the dictionary

        # Find the text of the selected row for the message
        selected_rows = self.entries_table.selectionModel().selectedRows()
        # Ensure a row is actually selected, though get_selected_entry_data should have handled it
        if not selected_rows:
             QMessageBox.information(self, "Information", "No row selected for deletion details.")
             return

        row_index = selected_rows[0].row()
        
        # Column indices for fetching display text:
        # 0: ID
        # 1: Duration
        # 2: Type
        # 3: Date & Time
        duration_text_item = self.entries_table.item(row_index, 1)
        timestamp_text_item = self.entries_table.item(row_index, 3) # CORRECTED: Timestamp is now at column index 3

        duration_text = duration_text_item.text() if duration_text_item else "N/A"
        timestamp_text = timestamp_text_item.text() if timestamp_text_item else "N/A"
        
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
                # Optionally, signal MainWindow to update stats if necessary
                if hasattr(self.parent(), 'update_ui_for_selection'):
                    self.parent().update_ui_for_selection()
                if hasattr(self.parent(), 'habits_updated'): 
                    self.parent().habits_updated.emit()
            else:
                QMessageBox.warning(self, "Error", "Failed to delete entry from the database.")

# --- AddEditEntryDialog Class ---
class AddEditEntryDialog(QDialog):
    def __init__(self, db_manager, activity_id, activity_name, entry_data=None, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.activity_id = activity_id
        self.activity_name = activity_name

        self.is_edit_mode = entry_data is not None
        self.entry_data = entry_data if self.is_edit_mode else {}

        title_prefix = "Edit Entry" if self.is_edit_mode else "Add New Entry"
        self.setWindowTitle(f"{title_prefix} for: {self.activity_name}")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # 1. Activity Name (Display Only)
        self.activity_name_label = QLabel(f"<b>{self.activity_name}</b>")
        layout.addWidget(self.activity_name_label)

        # 2. Timestamp
        self.timestamp_edit = QDateTimeEdit()
        self.timestamp_edit.setCalendarPopup(True)
        self.timestamp_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        form_layout.addRow("Time & Date:", self.timestamp_edit)

        # 3. Duration
        duration_layout = QHBoxLayout()
        self.hours_spin = QSpinBox()
        self.hours_spin.setRange(0, 999)
        self.hours_spin.setSuffix(" h")
        self.mins_spin = QSpinBox()
        self.mins_spin.setRange(0, 59)
        self.mins_spin.setSuffix(" m")
        self.secs_spin = QSpinBox()
        self.secs_spin.setRange(0, 59)
        self.secs_spin.setSuffix(" s")
        duration_layout.addWidget(self.hours_spin)
        duration_layout.addWidget(self.mins_spin)
        duration_layout.addWidget(self.secs_spin)
        form_layout.addRow("Duration:", duration_layout)

        # 4. Entry Type (Work/Break)
        type_layout = QHBoxLayout()
        self.work_radio = QRadioButton("Work")
        self.break_radio = QRadioButton("Break")
        type_layout.addWidget(self.work_radio)
        type_layout.addWidget(self.break_radio)
        type_layout.addStretch()
        form_layout.addRow("Type:", type_layout)

        layout.addLayout(form_layout)

        # 5. Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)
        self._populate_fields()

    def _populate_fields(self):
        """Populates dialog fields based on self.entry_data (for edit mode) or defaults (for add mode)."""
        current_dt = self.entry_data.get('timestamp_qdatetime', QDateTime.currentDateTime())
        duration_seconds = self.entry_data.get('duration_seconds', 600) # Default to 10 mins for add
        entry_type = self.entry_data.get('entry_type', 'work') # Default to 'work'

        self.timestamp_edit.setDateTime(current_dt)

        h, rem = divmod(duration_seconds, 3600)
        m, s = divmod(rem, 60)
        self.hours_spin.setValue(h)
        self.mins_spin.setValue(m)
        self.secs_spin.setValue(s)

        if entry_type == 'work':
            self.work_radio.setChecked(True)
        elif entry_type == 'break':
            self.break_radio.setChecked(True)
        else: # Default fallback
            self.work_radio.setChecked(True)


    def get_entry_data(self):
        """Returns the data entered by the user."""
        duration_seconds = (self.hours_spin.value() * 3600 +
                            self.mins_spin.value() * 60 +
                            self.secs_spin.value())

        selected_timestamp = self.timestamp_edit.dateTime() # This is already a QDateTime object

        entry_type = 'work'
        if self.break_radio.isChecked():
            entry_type = 'break'

        if duration_seconds <= 0:
            QMessageBox.warning(self, "Invalid Duration", "Duration must be greater than zero.")
            return None

        return {
            'duration_seconds': duration_seconds,
            'timestamp_qdatetime': selected_timestamp,
            'entry_type': entry_type
        }

    def accept(self):
        """Overrides QDialog.accept() to validate data before closing."""
        if self.get_entry_data() is not None: 
            super().accept()

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
        self.summary_tree = QTreeWidget()
        # --- ИЗМЕНЕНИЕ: Больше колонок ---
        self.summary_tree.setColumnCount(4)
        self.summary_tree.setHeaderLabels(["Activity", "Work Time", "Break Time", "Total Time"])
        header_summary = self.summary_tree.header()
        header_summary.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch) # Activity
        header_summary.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents) # Work
        header_summary.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Break
        header_summary.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents) # Total
        self.summary_tree.setSortingEnabled(True)
        self.summary_tree.sortByColumn(3, Qt.SortOrder.DescendingOrder) # Сортировка по общему времени
        # --- КОНЕЦ ИЗМЕНЕНИЯ ---
        summary_layout.addWidget(self.summary_tree)
        splitter.addWidget(summary_widget)

        # --- Widget for detailed entries (remains QTableWidget) ---
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0,0,0,0)
        details_layout.addWidget(QLabel("All Entries for the Day:"))
        self.entries_table = QTableWidget()
        # --- ИЗМЕНЕНИЕ: Больше колонок ---
        self.entries_table.setColumnCount(4)
        self.entries_table.setHorizontalHeaderLabels(["Activity", "Duration", "Type", "Entry Time"])
        header_details = self.entries_table.horizontalHeader()
        header_details.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch) # Activity
        header_details.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents) # Duration
        header_details.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Type
        header_details.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents) # Time
    # --- КОНЕЦ ИЗМЕНЕНИЯ ---
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
        """Loads, aggregates, and displays data including work/break times."""
        selected_date = self.date_edit.date().toString("yyyy-MM-dd")
        print(f"Loading snapshot for {selected_date}...")

        # --- ИЗМЕНЕНИЕ: Используем новый метод с типом ---
        entries = self.db_manager.get_entries_for_date_with_type(selected_date)
        # Теперь entries содержит: (activity_id, activity_name, duration, entry_type, timestamp_str)
        # --- КОНЕЦ ИЗМЕНЕНИЯ ---

        # Очистка виджетов
        self.entries_table.setSortingEnabled(False)
        self.entries_table.setRowCount(0)
        self.summary_tree.clear()
        self.summary_tree.setSortingEnabled(False)

        total_duration_day_seconds = 0
        total_work_day_seconds = 0 # Общее РАБОЧЕЕ время за день
        if not entries:
            # ... (код для случая без записей) ...
            return

        # --- ИЗМЕНЕНИЕ: Словари для агрегации по типам ---
        work_time_by_activity_id = defaultdict(int)
        break_time_by_activity_id = defaultdict(int)
        activity_names = {} # Сохраним имена активностей {id: name}
        # --- КОНЕЦ ИЗМЕНЕНИЯ ---

        self.entries_table.setRowCount(len(entries))
        # --- ИЗМЕНЕНИЕ: Обработка entry_type ---
# <<< ИСПРАВЛЕНИЕ: Добавлена переменная _session_id для распаковки 6-го элемента >>>
        for row, (activity_id, activity_name, duration, entry_type, timestamp_str, _session_id) in enumerate(entries):
            total_duration_day_seconds += duration # Общее время (включая перерывы)
            activity_names[activity_id] = activity_name # Сохраняем имя

            # Агрегация по типам
            if entry_type == 'work':
                work_time_by_activity_id[activity_id] += duration
                total_work_day_seconds += duration # Считаем общее рабочее время
            elif entry_type == 'break':
                break_time_by_activity_id[activity_id] += duration

            # --- Заполнение таблицы детальных записей (Добавляем Type) ---
            formatted_duration = MainWindow.format_time(None, duration)
            formatted_timestamp_display = timestamp_str # Default
            try:
                dt_utc = QDateTime.fromString(timestamp_str, "yyyy-MM-dd HH:mm:ss")
                dt_utc.setTimeSpec(Qt.TimeSpec.UTC)
                dt_local = dt_utc.toLocalTime()
                formatted_timestamp_display = dt_local.toString("HH:mm:ss")
            except Exception as e:
                parts = timestamp_str.split(' '); formatted_timestamp_display = parts[1] if len(parts)>1 else timestamp_str

            name_item = QTableWidgetItem(activity_name)
            duration_item = QTableWidgetItem(formatted_duration)
            type_item = QTableWidgetItem(entry_type.capitalize()) # Отображаем тип
            time_item = QTableWidgetItem(formatted_timestamp_display)

            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter) # Выравниваем тип
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            duration_item.setData(Qt.ItemDataRole.UserRole, duration)

            self.entries_table.setItem(row, 0, name_item)
            self.entries_table.setItem(row, 1, duration_item)
            self.entries_table.setItem(row, 2, type_item) # Новая колонка
            self.entries_table.setItem(row, 3, time_item) # Старая колонка времени теперь 3я
        # --- КОНЕЦ ИЗМЕНЕНИЯ в цикле ---

        self.entries_table.setSortingEnabled(True)
        self.entries_table.sortByColumn(3, Qt.SortOrder.AscendingOrder) # Сортируем по времени записи

        # --- ИЗМЕНЕНИЕ: Построение дерева с новыми данными ---
        activity_hierarchy = self.db_manager.get_activity_hierarchy()
        aggregated_work_time = defaultdict(int)
        aggregated_break_time = defaultdict(int)

        # Функция агрегации времени (включая дочерние) - теперь считает оба типа
        def aggregate_time_recursive(node):
            activity_id = node['id']
            node_work_time = work_time_by_activity_id.get(activity_id, 0)
            node_break_time = break_time_by_activity_id.get(activity_id, 0)

            for child_node in node['children']:
                child_work, child_break = aggregate_time_recursive(child_node)
                node_work_time += child_work
                node_break_time += child_break

            aggregated_work_time[activity_id] = node_work_time
            aggregated_break_time[activity_id] = node_break_time
            return node_work_time, node_break_time

        for top_level_node in activity_hierarchy:
            aggregate_time_recursive(top_level_node)

        # Функция построения дерева
        def build_summary_tree(parent_item, nodes):
            for node_data in nodes:
                activity_id = node_data['id']
                activity_name = node_data['name'] # Имя из иерархии
                work_seconds = aggregated_work_time.get(activity_id, 0)
                break_seconds = aggregated_break_time.get(activity_id, 0)
                total_seconds = work_seconds + break_seconds

                # Добавляем только если было какое-то время
                if total_seconds > 0:
                    fmt_work = MainWindow.format_time(None, work_seconds)
                    fmt_break = MainWindow.format_time(None, break_seconds)
                    fmt_total = MainWindow.format_time(None, total_seconds)

                    tree_item = QTreeWidgetItem(parent_item)
                    tree_item.setText(0, activity_name) # Activity
                    tree_item.setText(1, fmt_work)    # Work Time
                    tree_item.setText(2, fmt_break)   # Break Time
                    tree_item.setText(3, fmt_total)   # Total Time

                    # Выравнивание
                    tree_item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
                    tree_item.setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)
                    tree_item.setTextAlignment(3, Qt.AlignmentFlag.AlignCenter)

                    # Данные для сортировки (используем общее время для главной сортировки)
                    tree_item.setData(1, Qt.ItemDataRole.UserRole, work_seconds)
                    tree_item.setData(2, Qt.ItemDataRole.UserRole, break_seconds)
                    tree_item.setData(3, Qt.ItemDataRole.UserRole, total_seconds)
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, activity_id)

                    if node_data['children']:
                        build_summary_tree(tree_item, node_data['children'])

        build_summary_tree(self.summary_tree.invisibleRootItem(), activity_hierarchy)
        self.summary_tree.expandAll()
        self.summary_tree.setSortingEnabled(True)
        self.summary_tree.sortByColumn(3, Qt.SortOrder.DescendingOrder) # Сортируем по Total Time
        # --- КОНЕЦ ИЗМЕНЕНИЯ в построении дерева ---

        # Обновляем итоговую метку (показываем ОБЩЕЕ рабочее время)
        formatted_total_work_day = MainWindow.format_time(None, total_work_day_seconds)
        self.summary_label.setText(f"Total WORK time for the day: {formatted_total_work_day}")
        print(f"Snapshot for {selected_date} loaded. Entries: {len(entries)}. Total work time: {formatted_total_work_day}")# --- NEW: Configure Habit Dialog ---

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

    def on_grid_double_clicked(self, index: QModelIndex):
        """Handles user interaction with a habit cell.
        For numeric/percentage types, prompts to ADD the value for the current instance
        to any existing daily total.
        For binary, it toggles.
        """
        if not index.isValid(): return

        row = index.row()
        column = index.column()

        activity_id = self.habit_model.data(index, HABIT_ACTIVITY_ID_ROLE)
        date_str = self.habit_model.data(index, HABIT_DATE_ROLE)
        habit_type = self.habit_model.data(index, HABIT_TYPE_ROLE)
        habit_unit = self.habit_model.data(index, HABIT_UNIT_ROLE)
        current_value_from_model = self.habit_model.data(index, HABIT_VALUE_ROLE) # Existing cumulative value
        habit_name = self.habit_model.headerData(row, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole)

        if activity_id is None or habit_type is None or date_str is None:
            print(f"Error: Missing model data for index ({row},{column})")
            return

        new_value_to_log = None # This will hold the final CUMULATIVE value
        ok_to_set_data = False

        if habit_type == HABIT_TYPE_BINARY:
            new_value_to_log = None if current_value_from_model == 1.0 else 1.0
            ok_to_set_data = True

        elif habit_type == HABIT_TYPE_PERCENTAGE:
            current_total_percentage = current_value_from_model if current_value_from_model is not None else 0.0
            
            prompt_title = f"Log '{habit_name}' (%)"
            prompt_text = (f"Current daily total: {current_total_percentage:.0f}%. "
                           f"Enter percentage points for THIS INSTANCE to ADD for {date_str}:\n"
                           f"(Max total 100%. Enter 0 or Cancel for no change to total.)")
            
            # User always inputs the amount for the current instance/session
            percentage_this_instance, ok = QInputDialog.getDouble(
                self, prompt_title, prompt_text,
                value=0.0,  # Default to adding 0 for this instance
                min=0,      
                max=100.0,  # Max for a single instance (can be adjusted if needed)
                decimals=0
            )

            if ok:
                if percentage_this_instance > 0: # Only if they log a positive amount for this instance
                    new_cumulative_total = min(100.0, current_total_percentage + percentage_this_instance)
                    # Update if the new cumulative total is different from the old one
                    if new_cumulative_total != current_total_percentage:
                        new_value_to_log = new_cumulative_total
                        ok_to_set_data = True
                # If percentage_this_instance is 0, no change to total, ok_to_set_data remains False.
            # else: User cancelled dialog

        elif habit_type == HABIT_TYPE_NUMERIC:
            current_total_numeric = current_value_from_model if current_value_from_model is not None else 0.0
            unit_str = f" ({habit_unit})" if habit_unit else ""
            prompt_title = f"Log '{habit_name}'"
            prompt_text = (f"Current daily total: {current_total_numeric:g}{unit_str}. "
                           f"Enter value for THIS INSTANCE to ADD for {date_str}:\n"
                           f"(Enter 0 or Cancel for no change to total. Use negative to subtract from total.)")

            # User always inputs the amount for the current instance/session
            value_this_instance, ok = QInputDialog.getDouble(
                self, prompt_title, prompt_text,
                value=0.0, # Default to adding 0 for this instance
                min=-999999.0, max=999999.0, 
                decimals=2 
            )

            if ok:
                # If user explicitly entered 0 for THIS INSTANCE, and there was NO prior data,
                # we might ask if they want to log an explicit zero for the day.
                if current_value_from_model is None and value_this_instance == 0.0:
                    reply = QMessageBox.question(self, "Confirm Zero Log",
                                                 f"Log an explicit total of '0' for '{habit_name}' on {date_str}, or skip logging for this instance?",
                                                 buttons=QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Skip | QMessageBox.StandardButton.Cancel,
                                                 defaultButton=QMessageBox.StandardButton.Skip)
                    if reply == QMessageBox.StandardButton.Save: # Log Zero for the day
                        new_value_to_log = 0.0
                        ok_to_set_data = True
                    # If Skip or Cancel, ok_to_set_data remains False
                elif value_this_instance != 0.0: # If they are adding/subtracting a non-zero amount for this instance
                    new_cumulative_total = current_total_numeric + value_this_instance
                    # Update if the new cumulative total is different from the old one
                    if new_cumulative_total != current_total_numeric:
                        new_value_to_log = new_cumulative_total
                        ok_to_set_data = True
                # If value_this_instance is 0 (and not the special initial case), no change, ok_to_set_data remains False.
            # else: User cancelled dialog
            
        else: # Unknown habit type
            print(f"Warning: Unknown habit type {habit_type} encountered.")
            ok_to_set_data = False

        # --- Update Model if Value Determined ---
        if ok_to_set_data:
            print(f"HabitTrackerDialog: Requesting model setData for index({row},{column}), NewValueToLog={new_value_to_log}")
            success = self.habit_model.setData(index, new_value_to_log, HABIT_VALUE_ROLE)
            if not success:
                QMessageBox.warning(self, "Error", "Failed to save habit log update via model.")
            else:
                parent_window = self.parent() # Assuming HabitTrackerDialog is parented to MainWindow
                if parent_window and hasattr(parent_window, 'habits_updated'):
                    try:
                        parent_window.habits_updated.emit()
                        print("HabitTrackerDialog: Emitted habits_updated signal.")
                    except Exception as e:
                        print(f"HabitTrackerDialog: Error emitting habits_updated: {e}")
                else:
                     print("HabitTrackerDialog: Parent has no habits_updated signal or parent is None.")

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

class MainWindow(QMainWindow):
    habits_updated = pyqtSignal()

    # TimerWindow states (kept for clarity, used within task_data)
    STATE_TRACKING = 0
    STATE_PAUSED = 1

    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager()
        self.qtimer = QTimer(self) # One global QTimer for UI updates
        self.qtimer.timeout.connect(self.update_timer)

        # --- State Variables ---
        self.selected_activity_details = [] # List of selected: [(id, name), ...]
        self.active_timer_windows = {}      # Active tasks: {activity_id: task_data_dict}
        # task_data_dict = {'window': TimerWindow_instance, 'state': int,
        #                   'current_interval_start_time': float,
        #                   'total_session_work_sec': float, 'total_session_break_sec': float,
        #                   'session_id': float, # Unique ID for this task instance (start time)
        #                   'activity_name': str }

          # --- Multi-tasking window colors ---
        self._multitask_color_index = 0
        self.multitask_colors = [
             QColor(0, 0, 0, 180), QColor(90, 0, 0, 190), QColor(90, 45, 0, 190),
             QColor(0, 70, 0, 190), QColor(0, 70, 70, 190), QColor(0, 0, 90, 190),
             QColor(60, 0, 90, 190)
        ]

        # --- UI Elements ---
        self.activity_tree = None
        self.manage_entries_button = None
        self.snapshot_button = None
        self.habit_tracker_button = None
        self.start_tasks_button = None
        self.start_countdowns_button = None # <<< MODIFICATION: Renamed
        self.status_label = None
        self.heatmap_widget = None

        self.init_ui()
        self.apply_dark_theme()
        self.load_activities()

        if self.heatmap_widget:
            self.habits_updated.connect(self.heatmap_widget.refresh_data)
            print("Connected habits_updated signal to heatmap refresh.")

    def init_ui(self):
        self.setWindowTitle("Ritual - Time Tracker")
        self.setGeometry(100, 100, 750, 650)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Activity Tree ---
        main_layout.addWidget(QLabel("Activities (Right-click; Ctrl/Shift to multi-select):"))
        self.activity_tree = QTreeWidget()
        self.activity_tree.setMouseTracking(True) # Важно для itemEntered
        self.activity_tree.itemEntered.connect(self.handle_item_entered)
        # Устанавливаем фильтр событий на область просмотра дерева для отслеживания ухода мыши
        self.activity_tree.viewport().installEventFilter(self)
        self.activity_tree.viewport().setMouseTracking(True) # Также нужно для viewport
        self._hovered_item_id = None # Храним ID элемента под курсором
        self.activity_tree.setColumnCount(1)
        self.activity_tree.setHeaderHidden(True)
        self.activity_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.activity_tree.itemSelectionChanged.connect(self.handle_selection_change)
        self.activity_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.activity_tree.customContextMenuRequested.connect(self.show_activity_context_menu)
        self.activity_tree.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        main_layout.addWidget(self.activity_tree, 1)

        # --- Management Buttons ---
        management_layout = QHBoxLayout()
        self.manage_entries_button = QPushButton("Manage Entries")
        self.manage_entries_button.clicked.connect(self.open_entry_management)
        self.manage_entries_button.setEnabled(False) # Controlled by selection

        self.snapshot_button = QPushButton("Daily Snapshot")
        self.snapshot_button.clicked.connect(self.open_daily_snapshot)

        self.habit_tracker_button = QPushButton("Habit Tracker")
        self.habit_tracker_button.clicked.connect(self.open_habit_tracker)

        management_layout.addWidget(self.manage_entries_button)
        management_layout.addWidget(self.snapshot_button)
        management_layout.addWidget(self.habit_tracker_button)
        main_layout.addLayout(management_layout)

        # --- Timer Buttons ---
        timer_buttons_layout = QHBoxLayout()
        self.start_tasks_button = QPushButton("Start Selected Task(s)")
        self.start_tasks_button.clicked.connect(self.start_selected_tasks)
        self.start_tasks_button.setEnabled(False)

        # Используем новое имя переменной и текст кнопки
        self.start_countdowns_button = QPushButton("Start Selected Countdown(s)")
        # <<< ИСПРАВЛЕНИЕ: Подключаемся к правильному методу >>>
        self.start_countdowns_button.clicked.connect(self.start_selected_countdowns)
        self.start_countdowns_button.setEnabled(False)

        timer_buttons_layout.addWidget(self.start_tasks_button)
        # Используем новое имя переменной при добавлении в layout
        timer_buttons_layout.addWidget(self.start_countdowns_button)
        main_layout.addLayout(timer_buttons_layout)
        
        # --- Status Bar ---
        self.status_label = QLabel("Select activity(-ies)")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.status_label)

        # --- Heatmap Widget ---
        main_layout.addWidget(QLabel("Yearly Habit Heatmap:"))
        self.heatmap_widget = HeatmapWidget(self.db_manager, self)
        main_layout.addWidget(self.heatmap_widget, 0)

    def apply_dark_theme(self):
        # (Your existing dark theme code remains here)
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        # ... (rest of your palette settings) ...
        dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(45, 45, 45))
        app = QApplication.instance()
        if app:
            app.setPalette(dark_palette)
            # app.setStyleSheet(...) # Your stylesheet if any

    def load_activities(self):
        """Loads/reloads the activity hierarchy."""
        self.activity_tree.clear()
        self.activity_tree.setSortingEnabled(False)
        hierarchy = self.db_manager.get_activity_hierarchy()

        def add_items_recursive(parent_widget_item, activity_nodes):
             for node in activity_nodes:
                 item = QTreeWidgetItem(parent_widget_item)
                 prefix = "[H] " if node.get('habit_type') is not None and node.get('habit_type') != HABIT_TYPE_NONE else ""
                 item.setText(0, prefix + node['name'])
                 item.setData(0, Qt.ItemDataRole.UserRole, node['id'])
                 if node.get('children'):
                     add_items_recursive(item, node['children'])

        add_items_recursive(self.activity_tree.invisibleRootItem(), hierarchy)

        self.activity_tree.expandAll()
        self.activity_tree.setSortingEnabled(True)
        self.activity_tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        # Reset selection and update UI
        self.activity_tree.clearSelection()
        self.selected_activity_details = []
        self.update_ui_for_selection() # Update buttons and status bar

    def _find_tree_item_by_id(self, activity_id):
        """Helper to find a tree item by its stored activity ID."""
        if activity_id is None: return None
        iterator = QTreeWidgetItemIterator(self.activity_tree)
        while iterator.value():
            item = iterator.value()
            if item.data(0, Qt.ItemDataRole.UserRole) == activity_id:
                return item
            iterator += 1
        return None

    def _get_next_multitask_color(self):
        """Cycles through the defined colors for new timer windows."""
        color = self.multitask_colors[self._multitask_color_index % len(self.multitask_colors)]
        self._multitask_color_index += 1
        return color

    def handle_item_entered(self, item, column):
        """Вызывается, когда курсор входит в область элемента дерева."""
        # Обновляем статус, только если таймеры не активны
        if not self.active_timer_windows:
            self.update_status_for_hovered_item(item)

    def update_status_for_hovered_item(self, item):
        """Обновляет status_label для элемента под курсором или сбрасывает его."""
        if self.active_timer_windows:
            return

        activity_id = item.data(0, Qt.ItemDataRole.UserRole) if item else None

        if activity_id == self._hovered_item_id:
            return
        self._hovered_item_id = activity_id

        if item and activity_id is not None:
            avg_work, avg_break, avg_total = self.db_manager.calculate_average_session_times(activity_id)

            # CORRECTED CALLS:
            fmt_total = self.format_time(avg_total)
            fmt_work = self.format_time(avg_work)
            fmt_break = self.format_time(avg_break)

            status_string = f"Average session time: {fmt_total} | Work: {fmt_work} | Break: {fmt_break}"
            self.status_label.setText(status_string)
        else:
            self.update_ui_for_selection()
    
    def eventFilter(self, source, event):
        """Фильтр событий для отслеживания ухода мыши из области дерева."""
        # Проверяем, что событие от нужного виджета и тип события - уход мыши
        if source is self.activity_tree.viewport() and event.type() == QEvent.Type.Leave:
            # Мышь покинула область дерева, сбрасываем статус
            # Проверяем, активны ли таймеры перед сбросом
            if not self.active_timer_windows:
                print("DEBUG: Mouse left tree viewport, resetting status.") # Отладка
                self._hovered_item_id = None # Сбрасываем отслеживаемый ID
                self.update_status_for_hovered_item(None) # Вызовет update_ui_for_selection
            return True # Событие обработано

        # Передаем все остальные события дальше
        return super(MainWindow, self).eventFilter(source, event)

    def handle_selection_change(self):
        """Updates the internal list of selected activities and the UI."""
        # <<< MODIFICATION: No longer blocked by active timers >>>
        selected_items = self.activity_tree.selectedItems()
        self.selected_activity_details = []
        for item in selected_items:
            item_id = item.data(0, Qt.ItemDataRole.UserRole)
            if item_id is not None:
                display_name = item.text(0)
                actual_name = display_name.replace("[H] ", "", 1) if display_name.startswith("[H] ") else display_name
                self.selected_activity_details.append((item_id, actual_name))
        self.update_ui_for_selection()

    @staticmethod
    def format_time(total_seconds):  # Only takes total_seconds
        """Formats seconds into HH:MM:SS."""
        total_seconds = abs(int(total_seconds))
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02}:{m:02}:{s:02}"

    def update_ui_for_selection(self):
        """Updates buttons and status bar based on current selection and timer state."""
        # <<< ДОБАВИТЬ ПРОВЕРКУ >>>
        # Если таймеры активны, статус бар обновляется в update_timer, не меняем его здесь
        if self.active_timer_windows:
            # Только обновляем состояние кнопок
            num_selected = len(self.selected_activity_details)
            # ... (только логика enable/disable кнопок, БЕЗ self.status_label.setText) ...
            work_timers_active = any(not task.get('is_countdown', False) for task in self.active_timer_windows.values())
            countdown_timers_active = any(task.get('is_countdown', False) for task in self.active_timer_windows.values())
            self.start_tasks_button.setEnabled(num_selected >= 1 and not countdown_timers_active)
            has_selection_with_avg = any(self.db_manager.calculate_average_duration(aid) > 0 for aid, _ in self.selected_activity_details)
            can_start_countdown = num_selected >= 1 and has_selection_with_avg and not work_timers_active
            self.start_countdowns_button.setEnabled(can_start_countdown)
            if self.manage_entries_button: self.manage_entries_button.setEnabled(num_selected == 1)

            return # Выходим, не меняя status_label

        # --- Если таймеры НЕ активны, обновляем и статус бар ---
        num_selected = len(self.selected_activity_details)
        is_single_selection = num_selected == 1
        is_any_selection = num_selected >= 1

        avg_duration_specific = 0 # Используется для статуса и кнопки countdown
        status_text = "Select activity(-ies)"

        if is_single_selection:
            single_id, single_name = self.selected_activity_details[0]
            try:
                avg_duration_specific = self.db_manager.calculate_average_duration(single_id)
                total_duration_branch = self.db_manager.calculate_total_duration_for_activity_branch(single_id)
                # CORRECTED CALLS (ensure these are like this):
                avg_text = f"Avg Entry: {self.format_time(avg_duration_specific)}" if avg_duration_specific > 0 else "Avg Entry: N/A"
                total_text = f"Branch Total: {self.format_time(total_duration_branch)}"
                status_text = f"Selected: {single_name} ({avg_text} | {total_text})"
            except TypeError as e: # Catching the specific error to provide more context
                print(f"Error calculating stats for {single_name} in update_ui_for_selection: {e}")
                # This print helps confirm if the error originates here due to format_time
                status_text = f"Selected: {single_name} (Error getting stats - TypeError)"
            except Exception as e:
                print(f"Error calculating stats for {single_name}: {e}")
                status_text = f"Selected: {single_name} (Error getting stats)"
        elif is_any_selection:
            status_text = f"Selected: {num_selected} activities"

        # <<< УСТАНОВКА СТАТУСА ПО ВЫБОРУ (когда нет hover и нет таймеров) >>>
        self.status_label.setText(status_text)

        # --- Обновление состояния кнопок (когда нет таймеров) ---
        self.start_tasks_button.setEnabled(is_any_selection)
        # Кнопка Countdown зависит от средней *продолжительности записи*, а не сессии
        can_start_countdown = is_single_selection and avg_duration_specific > 0
        self.start_countdowns_button.setEnabled(can_start_countdown)

        if self.manage_entries_button: self.manage_entries_button.setEnabled(is_single_selection)
        if self.snapshot_button: self.snapshot_button.setEnabled(True)
        if self.habit_tracker_button: self.habit_tracker_button.setEnabled(True)
        self.activity_tree.setEnabled(True)
                
    # <<< MODIFICATION: Renamed from toggle_timer >>>
    def start_selected_tasks(self):
        """Starts work timers for selected activities that are not already running."""
        # <<< MODIFICATION: Added check for active countdowns >>>
        if any(task.get('is_countdown', False) for task in self.active_timer_windows.values()):
            QMessageBox.warning(self, "Timer Busy", "Cannot start work tasks while countdown timers are active.")
            return
        # ... (rest of start_selected_tasks method remains the same as previous step) ...
        if len(self.selected_activity_details) == 0:
            QMessageBox.warning(self, "Error", "Please select at least one activity first.")
            return

        qtimer_was_running = self.qtimer.isActive()
        num_added = 0
        default_font = self.activity_tree.font()
        bold_font = QFont(default_font)
        bold_font.setBold(True)

        for activity_id, activity_name in self.selected_activity_details:
            if activity_id not in self.active_timer_windows:
                print(f"Starting timer for: {activity_name} ({activity_id})")
                task_start_time = time.time() # Use start time as unique session ID for this task
                color = self._get_next_multitask_color()
                new_timer = TimerWindow(initial_color=color, parent=self)

                # Connect signals using lambda to capture the correct activity_id
                new_timer.pause_requested.connect(lambda checked=False, aid=activity_id: self.handle_pause_request(aid))
                new_timer.resume_requested.connect(lambda checked=False, aid=activity_id: self.handle_resume_request(aid))
                new_timer.end_requested.connect(lambda checked=False, aid=activity_id: self.handle_end_request(aid))

                self.active_timer_windows[activity_id] = {
                    'window': new_timer,
                    'state': TimerWindow.STATE_TRACKING,
                    'current_interval_start_time': task_start_time,
                    'total_session_work_sec': 0,
                    'total_session_break_sec': 0,
                    'session_id': task_start_time, # Store unique start time as session ID
                    'activity_name': activity_name,
                    'is_countdown': False # Explicitly mark as not countdown
                }
                new_timer.showTrackingState("00:00:00", "00:00:00", activity_name)

                item_ref = self._find_tree_item_by_id(activity_id)
                if item_ref:
                    item_ref.setFont(0, bold_font)

                window_index = len(self.active_timer_windows) # Index for positioning (0-based)
                self.show_and_position_timer_window(new_timer, window_index)
                num_added += 1
            else:
                 print(f"Task '{activity_name}' ({activity_id}) is already running.")


        if num_added > 0:
             print(f"Started {num_added} new task(s).")
             if not qtimer_was_running:
                 self.qtimer.start(1000)
                 print("Global timer started for UI updates.")
             self.update_ui_for_selection() # Update button states
        else:
             print("No new tasks were started (selected tasks already running or none selected).")

    def start_selected_countdowns(self):
        """Starts countdown timers for selected activities if possible."""
        # Check for conflicts with work timers
        if any(not task.get('is_countdown', False) for task in self.active_timer_windows.values()):
            QMessageBox.warning(self, "Timer Busy", "Cannot start countdowns while work tasks are active.")
            return
        if len(self.selected_activity_details) == 0:
            QMessageBox.warning(self, "Error", "Please select at least one activity for countdown.")
            return

        qtimer_was_running = self.qtimer.isActive()
        num_added = 0
        default_font = self.activity_tree.font()
        bold_font = QFont(default_font)
        bold_font.setBold(True)

        for activity_id, activity_name in self.selected_activity_details:
            if activity_id not in self.active_timer_windows:
                # Check if average duration exists for this activity
                average_duration = self.db_manager.calculate_average_duration(activity_id)
                if average_duration > 0:
                    target_duration = int(average_duration)
                    print(f"Starting countdown for: {activity_name} ({activity_id}), Target: {target_duration}s")

                    task_start_time = time.time()
                    color = self._get_next_multitask_color()
                    new_timer = TimerWindow(initial_color=color, parent=self)

                    # Connect signals
                    new_timer.pause_requested.connect(lambda checked=False, aid=activity_id: self.handle_pause_request(aid))
                    new_timer.resume_requested.connect(lambda checked=False, aid=activity_id: self.handle_resume_request(aid))
                    new_timer.end_requested.connect(lambda checked=False, aid=activity_id: self.handle_end_request(aid))

                    # Add task data, marking as countdown and storing target
                    self.active_timer_windows[activity_id] = {
                        'window': new_timer,
                        'state': TimerWindow.STATE_TRACKING,
                        'current_interval_start_time': task_start_time,
                        'total_session_work_sec': 0,
                        'total_session_break_sec': 0,
                        'session_id': task_start_time,
                        'activity_name': activity_name,
                        'is_countdown': True, # Mark as countdown
                        'target_duration': target_duration, # Store target duration
                    }
                    # Initial display shows target time
                    new_timer.showTrackingState(self.format_time(target_duration), "00:00:00", activity_name)
                    new_timer.set_overrun(False)
                    item_ref = self._find_tree_item_by_id(activity_id)
                    if item_ref:
                        item_ref.setFont(0, bold_font)

                    window_index = len(self.active_timer_windows) # Index for positioning
                    self.show_and_position_timer_window(new_timer, window_index)
                    num_added += 1
                else:
                    print(f"Skipping countdown for '{activity_name}' ({activity_id}): No average time data.")
            else:
                print(f"Countdown or task for '{activity_name}' ({activity_id}) is already running.")

        if num_added > 0:
            print(f"Started {num_added} new countdown timer(s).")
            if not qtimer_was_running:
                self.qtimer.start(1000)
                print("Global timer started for UI updates.")
            self.update_ui_for_selection() # Update button states
        else:
            print("No new countdowns were started.")

    def start_countdown_timer(self, activity_id, activity_name, average_duration):
        """Internal logic to start the countdown state and timer window."""
        # <<< MODIFICATION: Extracted from old toggle_countdown/start_countdown_timer >>>
        print(f"Starting 'Countdown' session for: {activity_name} ({activity_id}) from {average_duration:.0f} sec.")
        session_start_time = time.time()
        # No global session ID needed, but we store countdown specific state
        self.countdown_activity_id = activity_id
        self.countdown_target_duration = int(average_duration)
        # Reset multi-task color index if needed, or let it continue
        # self._multitask_color_index = 0

        # Ensure global timer is running
        if not self.qtimer.isActive():
             self.qtimer.start(1000)
             print("Global timer started for countdown.")

        color = self._get_next_multitask_color()
        countdown_window = TimerWindow(initial_color=color, parent=self)

        # Add to active_timer_windows so updates happen, but use countdown state
        self.active_timer_windows[activity_id] = {
            'window': countdown_window,
            'state': TimerWindow.STATE_TRACKING, # Countdown runs in tracking state
            'current_interval_start_time': session_start_time,
            'total_session_work_sec': 0, 'total_session_break_sec': 0,
             # Use start time as session ID for DB logging
            'session_id': session_start_time,
            'activity_name': activity_name
            # Add a flag? 'is_countdown': True (optional, could check self.countdown_activity_id)
        }

        countdown_window.pause_requested.connect(lambda checked=False, aid=activity_id: self.handle_pause_request(aid))
        countdown_window.resume_requested.connect(lambda checked=False, aid=activity_id: self.handle_resume_request(aid))
        countdown_window.end_requested.connect(lambda checked=False, aid=activity_id: self.handle_end_request(aid))

        # Initial display shows target time
        countdown_window.showTrackingState(self.format_time(None, self.countdown_target_duration), "00:00:00", activity_name)
        countdown_window.set_overrun(False)

        item_ref = self._find_tree_item_by_id(activity_id)
        if item_ref:
            bold_font = QFont(self.activity_tree.font())
            bold_font.setBold(True)
            item_ref.setFont(0, bold_font)

        self.show_and_position_timer_window(countdown_window, 0) # Show countdown window first
        self.update_ui_for_selection() # Update buttons (disables start tasks, changes countdown button)


    # --- Pause/Resume/End Handlers ---

# In class MainWindow:

    def handle_pause_request(self, activity_id):
        """Handles the 'Pause' button click from a TimerWindow."""
        print(f"DEBUG: Pause requested for {activity_id}")
        if activity_id in self.active_timer_windows:
            task_data = self.active_timer_windows[activity_id]
            if task_data['state'] == TimerWindow.STATE_TRACKING:
                now = time.time()
                work_duration = now - task_data['current_interval_start_time']
                print(f"DEBUG: Calculated work_duration before save: {work_duration:.4f}s for {activity_id}")
                task_data['total_session_work_sec'] += work_duration

                if work_duration >= 1: # Only save if duration is 1s or more
                    print(f"DEBUG: work_duration >= 1, attempting to call add_time_entry...")
                    success = self.db_manager.add_time_entry(
                        activity_id,
                        int(work_duration),
                        entry_type='work',
                        session_id=task_data['session_id']
                    )
                    print(f"DEBUG: add_time_entry for 'work' returned: {success}")
                else:
                    print(f"DEBUG: work_duration < 1 ({work_duration:.4f}s), skipped add_time_entry for 'work'.")

                task_data['state'] = TimerWindow.STATE_PAUSED
                task_data['current_interval_start_time'] = now # Start of break interval
                
                # CORRECTED CALLS to self.format_time:
                task_data['window'].showPausedState(
                    self.format_time(0), # Current break interval starts at 0
                    self.format_time(task_data['total_session_break_sec']),
                    task_data['activity_name']
                )
                self.update_ui_for_selection() # Update button states etc.
            else:
                print(f"-- Task {activity_id} ('{task_data.get('activity_name', 'N/A')}') already paused or in unexpected state.")
        else:
            print(f"-- Task {activity_id} not found for pause request.")
            
    def handle_resume_request(self, activity_id):
        """Handles the 'Resume' button click from a TimerWindow."""
        print(f"DEBUG: Resume requested for {activity_id}")
        if activity_id in self.active_timer_windows:
            task_data = self.active_timer_windows[activity_id]
            if task_data['state'] == TimerWindow.STATE_PAUSED:
                now = time.time()
                break_duration = now - task_data['current_interval_start_time']
                print(f"DEBUG: Calculated break_duration before save: {break_duration:.4f}s for {activity_id}")
                task_data['total_session_break_sec'] += break_duration

                if break_duration >= 1:
                    print(f"DEBUG: break_duration >= 1, attempting to call add_time_entry...")
                    success = self.db_manager.add_time_entry(activity_id, int(break_duration),
                                                             entry_type='break', session_id=task_data['session_id'])
                    print(f"DEBUG: add_time_entry for 'break' returned: {success}")
                else:
                    print(f"DEBUG: break_duration < 1, skipped add_time_entry.")

                task_data['state'] = TimerWindow.STATE_TRACKING
                task_data['current_interval_start_time'] = now 

                if task_data.get('is_countdown', False):
                    target_duration = task_data.get('target_duration', 0)
                    total_elapsed_session = task_data['total_session_work_sec']
                    remaining = target_duration - total_elapsed_session
                    # CORRECTED CALL:
                    display_text_main = self.format_time(max(0, remaining))
                    is_over = remaining < 0
                    overrun_secs = abs(remaining) if is_over else 0
                    task_data['window'].set_overrun(is_over, overrun_secs)
                    # CORRECTED CALL:
                    task_data['window'].showTrackingState(display_text_main, self.format_time(total_elapsed_session), task_data['activity_name'])
                else: 
                    task_data['window'].set_overrun(False)
                    # CORRECTED CALLS:
                    task_data['window'].showTrackingState(
                        self.format_time(0), 
                        self.format_time(task_data['total_session_work_sec']),
                        task_data['activity_name']
                    )
                self.update_ui_for_selection()
            else:
                print(f"-- Task {activity_id} ('{task_data.get('activity_name', 'N/A')}') not paused.")
        else:
            print(f"-- Task {activity_id} not found for resume request.")
    
    def handle_end_request(self, activity_id):
        """Handles the 'End' button click from a TimerWindow."""
        print(f"End requested for {activity_id} via window button.")
        # Usually, we want to save the last interval when ending via the window button
        self.stop_single_task(activity_id, save_entry=True)

    def update_timer(self):
        if not self.qtimer.isActive():
            print("DEBUG: update_timer called but qtimer is NOT active. This is unexpected.")
            return

        if not self.active_timer_windows:
            print("DEBUG: MainWindow.update_timer: No active windows. Stopping qtimer.")
            if self.qtimer.isActive(): 
                self.qtimer.stop()
                print("DEBUG: Global timer stopped by update_timer due to no active windows.")
            self.update_ui_for_selection()
            return

        current_time = time.time()
        active_ids_in_tick = list(self.active_timer_windows.keys())

        for activity_id in active_ids_in_tick: 
            if activity_id not in self.active_timer_windows:
                print(f"DEBUG: MainWindow.update_timer: activity_id {activity_id} disappeared during iteration. Skipping.")
                continue

            task_data = self.active_timer_windows[activity_id]
            window = task_data['window']

            if task_data['state'] == TimerWindow.STATE_TRACKING:
                current_interval_sec = current_time - task_data['current_interval_start_time']
                total_session_sec = task_data['total_session_work_sec'] + current_interval_sec

                if task_data.get('is_countdown', False):
                    target_duration = task_data.get('target_duration', 0)
                    remaining = target_duration - total_session_sec
                    if remaining < 0:
                        overrun_seconds = abs(remaining)
                        window.set_overrun(True, overrun_seconds)
                        # CORRECTED CALL:
                        display_text_main = f"-{self.format_time(overrun_seconds)}"
                    else:
                        window.set_overrun(False)
                        # CORRECTED CALL:
                        display_text_main = self.format_time(remaining)
                    # CORRECTED CALL:
                    window.showTrackingState(display_text_main, self.format_time(total_session_sec), task_data['activity_name'])
                else: # Normal work timer
                    window.set_overrun(False)
                    # CORRECTED CALLS:
                    display_text_main = self.format_time(current_interval_sec)
                    total_session_str = self.format_time(total_session_sec)
                    window.showTrackingState(display_text_main, total_session_str, task_data['activity_name'])

            elif task_data['state'] == TimerWindow.STATE_PAUSED:
                current_break_interval_sec = current_time - task_data['current_interval_start_time']
                total_break_sec = task_data['total_session_break_sec'] + current_break_interval_sec
                # CORRECTED CALLS:
                current_break_str = self.format_time(current_break_interval_sec)
                total_break_str = self.format_time(total_break_sec)
                window.showPausedState(current_break_str, total_break_str, task_data['activity_name'])

# In class MainWindow:

    def stop_single_task(self, activity_id, save_entry=True):
        """Stops one task, saves last interval if requested, updates global state if last task,
           and prompts for habit logging if applicable based on total session work."""
        print(f"DEBUG: Attempting to stop/end task ID: {activity_id}. Save last entry: {save_entry}")

        if activity_id not in self.active_timer_windows:
            print(f"-- Task {activity_id} not found in active_timer_windows (already stopped or never started).")
            if not self.active_timer_windows and self.qtimer.isActive():
                print(f"DEBUG: stop_single_task: qtimer is active but no active_timer_windows. Stopping qtimer. Task was {activity_id}.")
                self.qtimer.stop()
                print("DEBUG: Global timer stopped by stop_single_task (no active windows).")
                self.update_ui_for_selection()
            return

        task_data = self.active_timer_windows.pop(activity_id)
        window = task_data['window']
        activity_name = task_data['activity_name']
        session_id = task_data['session_id']
        
        # This will be the duration of the very last segment (work or break)
        duration_of_final_segment_for_db = 0
        
        # This will be updated to the session's true total work, including the final work segment if applicable
        final_total_session_work_sec = task_data['total_session_work_sec']

        if save_entry:
            now = time.time()
            last_interval_duration = now - task_data['current_interval_start_time']
            duration_of_final_segment_for_db = int(last_interval_duration)

            entry_type_to_save = 'unknown'
            if task_data['state'] == TimerWindow.STATE_TRACKING:
                entry_type_to_save = 'work'
                # Add this final work interval's duration to the session's recorded total work
                final_total_session_work_sec += last_interval_duration 
                
                if duration_of_final_segment_for_db >= 1:
                    print(f"DEBUG: duration_to_save_for_db ('{entry_type_to_save}') >= 1 ({duration_of_final_segment_for_db}s), attempting to call add_time_entry...")
                    success = self.db_manager.add_time_entry(activity_id, duration_of_final_segment_for_db, entry_type=entry_type_to_save, session_id=session_id)
                    print(f"DEBUG: add_time_entry for final '{entry_type_to_save}' returned: {success}")
                else:
                    print(f"DEBUG: duration_to_save_for_db ('{entry_type_to_save}') < 1 ({duration_of_final_segment_for_db:.4f}s), skipped add_time_entry.")

            elif task_data['state'] == TimerWindow.STATE_PAUSED:
                entry_type_to_save = 'break'
                # final_total_session_work_sec already correctly reflects work done up to the pause.
                if duration_of_final_segment_for_db >= 1:
                    print(f"DEBUG: last_duration ('{entry_type_to_save}') >= 1 ({duration_of_final_segment_for_db}s), attempting to call add_time_entry...")
                    success = self.db_manager.add_time_entry(activity_id, duration_of_final_segment_for_db, entry_type=entry_type_to_save, session_id=session_id)
                    print(f"DEBUG: add_time_entry for final '{entry_type_to_save}' returned: {success}")
                else:
                    print(f"DEBUG: last_duration ('{entry_type_to_save}') < 1 ({duration_of_final_segment_for_db:.4f}s), skipped add_time_entry.")
        else:
            print(f"-- Ending task '{activity_name}' (ID: {activity_id}) without saving last interval because save_entry=False.")

        # --- Habit Prompt Logic ---
        habit_config_tuple = self.db_manager.get_activity_habit_config(activity_id)
        is_configured_as_habit = habit_config_tuple[0] is not None and habit_config_tuple[0] != HABIT_TYPE_NONE
        
        # Use the session's final total work duration for the prompt's context.
        # This value (final_total_session_work_sec) now correctly includes the last work segment if the timer was running.
        relevant_work_duration_for_habit_prompt = int(final_total_session_work_sec)

        if save_entry and is_configured_as_habit and relevant_work_duration_for_habit_prompt >= 1:
            print(f"-- Checking habit prompt for task {activity_id} ('{activity_name}') with total session work {relevant_work_duration_for_habit_prompt}s (Ended in state: {task_data['state']}).")
            self.prompt_and_log_habit_after_timer(activity_id, activity_name, habit_config_tuple, relevant_work_duration_for_habit_prompt)
        else:
            if not is_configured_as_habit:
                print(f"-- No habit configured for task {activity_id} for post-timer prompt.")
            elif not (relevant_work_duration_for_habit_prompt >= 1):
                 print(f"-- No significant work done in session for habit prompt for task {activity_id} (Total work: {relevant_work_duration_for_habit_prompt:.2f}s).")
            elif not save_entry:
                print(f"-- Not prompting habit for task {activity_id} because save_entry is False.")

        if window:
            window.close()
        item_ref = self._find_tree_item_by_id(activity_id)
        if item_ref:
            item_ref.setFont(0, self.activity_tree.font())

        if not self.active_timer_windows:
            print("-- All active timers stopped/managed by stop_single_task.")
            if self.qtimer.isActive():
                print(f"DEBUG: stop_single_task: Stopping qtimer. No more active_timer_windows. Last task was {activity_id}.")
                self.qtimer.stop()
                print("DEBUG: Global timer stopped by stop_single_task.")
            self._multitask_color_index = 0
        else:
            print(f"DEBUG: stop_single_task: {len(self.active_timer_windows)} timers still active.")
        self.update_ui_for_selection()
    
    def stop_all_tasks(self):
        """Stops all active timers (work and countdown), saving last intervals by default."""
        if not self.active_timer_windows:
            print("stop_all_tasks called but no active tasks to stop.")
            if self.qtimer.isActive():
                 print("DEBUG: stop_all_tasks: qtimer was active with no active_timer_windows. Stopping qtimer.")
                 self.qtimer.stop()
                 print("DEBUG: Global timer stopped by stop_all_tasks (no active windows).")
            self.update_ui_for_selection() # Ensure UI is in a consistent state
            return

        num_active = len(self.active_timer_windows)
        print(f"Stopping {num_active} active task(s) via stop_all_tasks.")
        
        ids_to_stop = list(self.active_timer_windows.keys()) # Iterate over a copy
        for activity_id in ids_to_stop:
            # Ensure task still exists in case of rapid/overlapping calls, though pop in stop_single_task should handle it.
            if activity_id in self.active_timer_windows:
                 self.stop_single_task(activity_id, save_entry=True)
            else:
                 print(f"DEBUG: stop_all_tasks: Task {activity_id} was already removed before its turn.")


        # After loop, active_timer_windows should be empty.
        if self.active_timer_windows:
             print(f"WARNING: stop_all_tasks: active_timer_windows not empty after stopping all. Remaining: {list(self.active_timer_windows.keys())}")
             # Force clear and close any remaining windows as a fallback
             for aid_rem in list(self.active_timer_windows.keys()):
                  task_data_rem = self.active_timer_windows.pop(aid_rem, None)
                  if task_data_rem and task_data_rem.get('window'):
                      try:
                          task_data_rem['window'].close()
                      except Exception as e:
                          print(f"Error closing leftover window for {aid_rem} in stop_all_tasks: {e}")
        
        self._multitask_color_index = 0

        # qtimer should have been stopped by the last call to stop_single_task
        # if active_timer_windows became empty. Double check.
        if not self.active_timer_windows and self.qtimer.isActive():
            print("DEBUG: stop_all_tasks: Forcing qtimer stop as a final check as active_timer_windows is empty.")
            self.qtimer.stop()
            print("DEBUG: Global timer stopped by stop_all_tasks (final check).")
        
        self.update_ui_for_selection()

    def format_time(instance_or_none, total_seconds):
        """Formats seconds into HH:MM:SS."""
        total_seconds = abs(int(total_seconds))
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02}:{m:02}:{s:02}"

    def show_and_position_timer_window(self, timer_window: TimerWindow, window_index: int):
        """Shows and positions a new timer window."""
        # (This method remains the same)
        timer_window.show()
        try:
            screen = QApplication.primaryScreen(); sg = screen.availableGeometry()
            tw = timer_window.width(); th = timer_window.height()
            margin = 15; spacing = 5; offset_x = margin
            # Position based on index (simple tiling)
            offset_y = margin + window_index * (th + spacing)
            x = sg.right() - tw - offset_x; y = sg.top() + offset_y
            # Prevent going off-screen vertically
            max_y = sg.bottom() - th - margin
            if y > max_y : y = max_y # Adjust last window if needed
            timer_window.move(QPoint(x, y))
        except Exception as e: print(f"Error positioning timer window: {e}")

    def closeEvent(self, event):
        """Handles the main window close event."""
        # <<< MODIFICATION: Check active_timer_windows OR countdown state >>>
        if self.active_timer_windows: # Just check if the dictionary is non-empty
            num_active = len(self.active_timer_windows)
            # Determine description based on content
            has_work = any(not task.get('is_countdown', False) for task in self.active_timer_windows.values())
            has_countdown = any(task.get('is_countdown', False) for task in self.active_timer_windows.values())
            if has_work and has_countdown: active_desc = f"{num_active} work/countdown timer(s)"
            elif has_work: active_desc = f"{num_active} work timer(s)"
            elif has_countdown: active_desc = f"{num_active} countdown timer(s)"
            else: active_desc = f"{num_active} timer(s)" # Fallback

            reply = QMessageBox.question(self, "Timers Active",
                                         f"{active_desc} are still running. Stop all and exit?\n(Last intervals will be saved)",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_all_tasks()
            else:
                event.ignore()
                return

        print("Closing application resources...")
        self.db_manager.close()
        # Ensure all timer windows are closed explicitly (stop_all_tasks should handle this, but belt-and-suspenders)
        for task_data in list(self.active_timer_windows.values()):
             try: task_data['window'].close()
             except Exception as e: print(f"Error closing timer window during shutdown: {e}")
        self.active_timer_windows = {}
        print("Application closing.")
        event.accept()

    # --- Context Menu Methods (add_activity_action, rename_activity_action, configure_habit_action, delete_activity_action) ---
    # (These remain the same as in the previous version, ensure delete_activity_action calls stop_single_task if deleting a timed activity)
    
    def show_activity_context_menu(self, position):
        clicked_item = self.activity_tree.itemAt(position)
        menu = QMenu(self)

        selected_id = None
        item_text_for_menu = "selection"

        if clicked_item:
            item_text_for_menu = clicked_item.text(0)
            retrieved_data = clicked_item.data(0, Qt.ItemDataRole.UserRole)
            # This first print is what we saw: UI_DEBUG_CONTEXT_MENU: Clicked Item='[H] 14 hwf + кс', Retrieved UserRole Data='6' (type: <class 'int'>)
            print(f"UI_DEBUG_CONTEXT_MENU: Clicked Item='{item_text_for_menu}', Retrieved UserRole Data='{retrieved_data}' (type: {type(retrieved_data)})")

            if isinstance(retrieved_data, int):
                selected_id = retrieved_data # selected_id is now an integer, e.g., 6
            else:
                print(f"UI_ERROR_CONTEXT_MENU: UserRole data for item '{item_text_for_menu}' is NOT an integer (it's '{retrieved_data}'). Will not use for operations requiring an ID.")
        else:
            print(f"UI_DEBUG_CONTEXT_MENU: No item at click position {position}. Context menu might be limited.")

        add_top_level_action = QAction(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder), "Add Top-Level Activity", self)
        add_top_level_action.setObjectName("addTopLevelAction") # For debugging sender
        add_top_level_action.triggered.connect(lambda: self.add_activity_action(parent_id=None))
        menu.addAction(add_top_level_action)

        if clicked_item and selected_id is not None: # This condition should be true if selected_id is 6
            menu.addSeparator()

            add_sub_action = QAction(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder), f"Add Sub-Activity to '{item_text_for_menu}'", self)
            add_sub_action.setObjectName(f"addSubActionFor_{selected_id}") # For debugging sender

            # --- CRITICAL DEBUG PRINT ---
            print(f"UI_DEBUG_CONTEXT_MENU_CONNECT: About to connect 'add_sub_action' for selected_id: {selected_id} (type: {type(selected_id)})")
            # --- END CRITICAL DEBUG PRINT ---

            # Using functools.partial for robust argument binding
            action_callable = partial(self.add_activity_action, parent_id=selected_id)
            add_sub_action.triggered.connect(action_callable)
            menu.addAction(add_sub_action)

            menu.addSeparator()
            rename_action = QAction(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), f"Rename '{item_text_for_menu}'", self)
            rename_action.setObjectName(f"renameActionFor_{selected_id}")
            rename_action.triggered.connect(lambda item_to_rename=clicked_item: self.rename_activity_action(item_to_rename_override=item_to_rename))
            menu.addAction(rename_action)

            config_habit_action = QAction(QIcon.fromTheme("preferences-system", QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)), f"Configure '{item_text_for_menu}' as Habit...", self)
            config_habit_action.setObjectName(f"configHabitActionFor_{selected_id}")
            config_habit_action.triggered.connect(lambda item_to_config=clicked_item: self.configure_habit_action(item_to_config_override=item_to_config))
            menu.addAction(config_habit_action)

            menu.addSeparator()
            delete_action = QAction(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon), f"Delete '{item_text_for_menu}'", self)
            delete_action.setObjectName(f"deleteActionFor_{selected_id}")
            delete_action.triggered.connect(lambda item_to_delete=clicked_item: self.delete_activity_action(item_to_delete_override=item_to_delete))
            menu.addAction(delete_action)

        menu.exec(self.activity_tree.viewport().mapToGlobal(position))    
    
    def add_activity_action(self, parent_id=None):
        sender_action = self.sender()
        if sender_action:
            print(f"UI_DEBUG_ADD_ACTIVITY_ACTION_ENTRY: Called by action: '{sender_action.objectName() if sender_action.objectName() else 'Unnamed Action'}' with parent_id: {parent_id} (type: {type(parent_id)})")
        else:
            print(f"UI_DEBUG_ADD_ACTIVITY_ACTION_ENTRY: Called directly (no sender QAction) with parent_id: {parent_id} (type: {type(parent_id)})")

        # ... rest of your existing add_activity_action method from the previous good version ...
        # (The one that started with parent_name_suffix = "" and had the UI_WARNING print)
        parent_name_suffix = ""
        parent_item_found_in_tree = False # Flag to check if parent_id corresponds to a visible tree item

        if parent_id is not None: # This means we are trying to add a sub-activity
            item = self._find_tree_item_by_id(parent_id)
            if item:
                parent_name_suffix = f" under '{item.text(0)}'"
                parent_item_found_in_tree = True
                print(f"UI_DEBUG_ADD_ACTIVITY_ACTION: For sub-activity, found parent item '{item.text(0)}' in tree with ID: {parent_id}")
            else:
                parent_name_suffix = f" under a potential parent (ID: {parent_id})"
                # This is the UI_WARNING you were seeing. It will now be preceded by the SENDER log.
                print(f"UI_WARNING_ADD_ACTIVITY_ACTION: For sub-activity, parent_id {parent_id} (type: {type(parent_id)}) was provided, but no corresponding item found in the tree. This ID will still be passed to the DB.")
        else:
            print(f"UI_DEBUG_ADD_ACTIVITY_ACTION: Adding a top-level activity (parent_id is None).")

        text, ok = QInputDialog.getText(self, "Add Activity", f"Enter name for the new activity{parent_name_suffix}:")
        # ... (continue with the rest of the method from the previous step where it was working,
        # make sure to use the one that has the `print(f"UI_DEBUG: Calling db_manager.add_activity with name='{activity_name_to_add}', parent_id={parent_id} ...")` )
        if ok and text.strip():
            activity_name_to_add = text.strip()
            print(f"UI_DEBUG_ADD_ACTIVITY_ACTION: Calling db_manager.add_activity with name='{activity_name_to_add}', parent_id={parent_id} (type: {type(parent_id)}), parent_item_found_in_tree={parent_item_found_in_tree}")
            new_activity_id = self.db_manager.add_activity(activity_name_to_add, parent_id)

            if new_activity_id is not None:
                print(f"UI_INFO_ADD_ACTIVITY_ACTION: Successfully added activity, new ID: {new_activity_id}. Reloading activities.")
                self.load_activities()
                new_item = self._find_tree_item_by_id(new_activity_id)
                if new_item:
                    self.activity_tree.setCurrentItem(new_item)
                self.update_ui_for_selection() 
                self.habits_updated.emit()
            else:
                print(f"UI_ERROR_ADD_ACTIVITY_ACTION: db_manager.add_activity returned None for name='{activity_name_to_add}', parent_id={parent_id}.")
        elif ok: 
            QMessageBox.warning(self, "Error", "Activity name cannot be empty.")
        else: 
            print(f"UI_INFO_ADD_ACTIVITY_ACTION: Add activity cancelled by user.")

    def rename_activity_action(self, item_to_rename_override=None):
        selected_item = item_to_rename_override if item_to_rename_override else self.activity_tree.currentItem()
        if not selected_item:
            print("UI_ERROR_RENAME: No item selected or provided for renaming.")
            return

        activity_id = selected_item.data(0, Qt.ItemDataRole.UserRole)
        current_display_name = selected_item.text(0)
        current_name = current_display_name.replace("[H] ", "", 1) if current_display_name.startswith("[H] ") else current_display_name
        db_parent_id = self.db_manager.get_activity_parent_id(activity_id)

        new_name, ok = QInputDialog.getText(self, "Rename Activity", "Enter new name:", QLineEdit.EchoMode.Normal, current_name)
        new_name_stripped = new_name.strip() if ok else ""

        if ok and new_name_stripped and new_name_stripped != current_name:
             if self.db_manager.update_activity_name(activity_id, new_name_stripped, db_parent_id):
                 prefix = "[H] " if current_display_name.startswith("[H] ") else ""
                 selected_item.setText(0, prefix + new_name_stripped)
                 # Update name in active timer window if it's running
                 if activity_id in self.active_timer_windows:
                     self.active_timer_windows[activity_id]['activity_name'] = new_name_stripped
                     # Force an update of the timer window display text
                     # (Need to call showTrackingState/showPausedState - update_timer might not catch the name change immediately)
                     task_data = self.active_timer_windows[activity_id]
                     # Simplified update - just call update_timer() which will redraw with new name
                     # Or force redraw:
                     # if task_data['state'] == TimerWindow.STATE_TRACKING: ... call showTrackingState ...
                     # else: ... call showPausedState ...


                 # Update selection details and UI
                 updated_selection_details = []
                 was_selected = False
                 for sel_id, sel_name in self.selected_activity_details:
                     if sel_id == activity_id:
                         updated_selection_details.append((sel_id, new_name_stripped))
                         was_selected = True
                     else:
                         updated_selection_details.append((sel_id, sel_name))
                 self.selected_activity_details = updated_selection_details
                 if was_selected: self.update_ui_for_selection()

                 self.habits_updated.emit() # Notify habit views

        elif ok and not new_name_stripped:
             QMessageBox.warning(self, "Error", "Activity name cannot be empty.")

    def configure_habit_action(self, item_to_config_override=None):
        selected_item = item_to_config_override if item_to_config_override else self.activity_tree.currentItem()
        if not selected_item:
            print("UI_ERROR_CONFIG_HABIT: No item selected or provided for habit configuration.")
            return
        activity_id = selected_item.data(0, Qt.ItemDataRole.UserRole)
        display_name = selected_item.text(0)
        activity_name = display_name.replace("[H] ", "", 1) if display_name.startswith("[H] ") else display_name
        current_config = self.db_manager.get_activity_habit_config(activity_id)
        dialog = ConfigureHabitDialog(activity_id, activity_name, current_config, self.db_manager, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            print(f"Habit config updated for {activity_name}. Reloading activities.")
            selected_ids_before_reload = {details[0] for details in self.selected_activity_details}
            self.load_activities() # Reloads tree
            # Restore selection
            items_to_select = []
            iterator = QTreeWidgetItemIterator(self.activity_tree)
            while iterator.value():
                item = iterator.value()
                item_id = item.data(0, Qt.ItemDataRole.UserRole)
                if item_id in selected_ids_before_reload: items_to_select.append(item)
                iterator += 1
            self.activity_tree.blockSignals(True)
            self.activity_tree.clearSelection()
            for item in items_to_select: item.setSelected(True)
            self.activity_tree.blockSignals(False)
            self.handle_selection_change() # Update UI for restored selection

            self.habits_updated.emit() # Notify habit views


    def delete_activity_action(self, item_to_delete_override=None): # Keep the fix from previous step here too
        selected_item = item_to_delete_override if item_to_delete_override else self.activity_tree.currentItem()
        if not selected_item:
            print("UI_ERROR_DELETE: No item selected or provided for deletion.")
            return
        
        activity_id = selected_item.data(0, Qt.ItemDataRole.UserRole)
        # Ensure activity_id is an integer, especially if coming from item_to_delete_override
        if not isinstance(activity_id, int):
            print(f"UI_ERROR_DELETE: Invalid activity ID ({activity_id}) for item '{selected_item.text(0)}'. Cannot delete.")
            QMessageBox.warning(self, "Error", "Could not delete item: invalid activity ID.")
            return

        activity_name = selected_item.text(0)
        base_activity_name = activity_name.replace("[H] ", "", 1) if activity_name.startswith("[H] ") else activity_name

        # Warning message logic
        warning_message = ""
        all_descendants = self.db_manager.get_descendant_activity_ids(activity_id)
        descendant_count = len(all_descendants) - 1 if activity_id in all_descendants else len(all_descendants)
        if descendant_count > 0:
            warning_message += f"\n\nWARNING: Also deletes {descendant_count} child activities!"
        warning_message += "\nAll associated time/habit entries will also be deleted!"

        reply = QMessageBox.question(self, "Confirm Deletion",
                                     f"Delete '{base_activity_name}'?{warning_message}",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            was_habit, _, _ = self.db_manager.get_activity_habit_config(activity_id)
            is_habit = was_habit is not None and was_habit != HABIT_TYPE_NONE

            if activity_id in self.active_timer_windows:
                print(f"Stopping timer for activity being deleted: {activity_id}")
                self.stop_single_task(activity_id, save_entry=False)

            if self.db_manager.delete_activity(activity_id):
                self.load_activities()
                if is_habit:
                    self.habits_updated.emit()
            else:
                QMessageBox.critical(self, "Deletion Error",
                                     f"Failed to delete activity '{base_activity_name}'.")
    
    def open_entry_management(self):
        if len(self.selected_activity_details) != 1:
            QMessageBox.warning(self, "Selection Error", "Please select exactly one activity to manage entries.")
            return
        activity_id, activity_name = self.selected_activity_details[0]
        dialog = EntryManagementDialog(activity_id, activity_name, self.db_manager, self)
        dialog.exec()
        if dialog.needs_update:
            print("Updating activity info after managing entries...")
            self.update_ui_for_selection() # Update status bar stats

    def open_daily_snapshot(self):
        dialog = DailySnapshotDialog(self.db_manager, self)
        dialog.exec()

    def open_habit_tracker(self):
        # Pass self so dialog can connect to habits_updated signal
        dialog = HabitTrackerDialog(self.db_manager, self)
        dialog.exec()

# In class MainWindow:
# In class MainWindow:

    def prompt_and_log_habit_after_timer(self, activity_id, activity_name, habit_config, work_duration_seconds):
        # activity_name IS DEFINED HERE as a parameter
        habit_type, habit_unit, habit_goal = habit_config 
        today_str = QDate.currentDate().toString("yyyy-MM-dd")

        confirm_instance_log_reply = QMessageBox.question(self, 
            f"Log Habit Instance: {activity_name}", # Use activity_name
            f"The timed activity '{activity_name}' is also a habit.\n" # Use activity_name
            f"Do you want to log the instance you just completed for {today_str}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if confirm_instance_log_reply != QMessageBox.StandardButton.Yes:
            print(f"-- User skipped logging habit instance for '{activity_name}' on {today_str}.")
            return

        value_this_instance = None
        proceed_with_instance_value = False

        if habit_type == HABIT_TYPE_BINARY:
            value_this_instance = 1.0 
            proceed_with_instance_value = True

        elif habit_type == HABIT_TYPE_PERCENTAGE:
            logs_for_day_temp = self.db_manager.get_habit_logs_for_date_range(today_str, today_str)
            current_cumulative_value_for_prompt = None
            for (log_aid, log_date), log_val in logs_for_day_temp.items():
                if log_aid == activity_id and log_date == today_str:
                    current_cumulative_value_for_prompt = log_val
                    break
            current_total_percentage_for_display = current_cumulative_value_for_prompt if current_cumulative_value_for_prompt is not None else 0.0
            
            prompt_title = f"Log Percentage for '{activity_name}' Instance" # Use activity_name
            prompt_text = (f"Daily total for '{activity_name}' is {current_total_percentage_for_display:.0f}%. " # Use activity_name
                           f"Enter percentage for THIS INSTANCE just completed on {today_str}:\n"
                           f"(0-100%. This will be added to daily total.)")
            default_instance_percent = 25.0 
            
            percent_val, ok = QInputDialog.getDouble(self, prompt_title, prompt_text,
                                                     value=default_instance_percent, min=0, max=100, decimals=0)
            if ok:
                value_this_instance = percent_val
                proceed_with_instance_value = True

        elif habit_type == HABIT_TYPE_NUMERIC:
            logs_for_day_temp = self.db_manager.get_habit_logs_for_date_range(today_str, today_str)
            current_cumulative_value_for_prompt = None
            for (log_aid, log_date), log_val in logs_for_day_temp.items():
                if log_aid == activity_id and log_date == today_str:
                    current_cumulative_value_for_prompt = log_val
                    break
            current_total_numeric_for_display = current_cumulative_value_for_prompt if current_cumulative_value_for_prompt is not None else 0.0
            
            unit_display = f" ({habit_unit})" if habit_unit else ""
            prompt_title = f"Log Numeric for '{activity_name}' Instance" # Use activity_name
            prompt_text = (f"Daily total for '{activity_name}' is {current_total_numeric_for_display:g}{unit_display}. " # Use activity_name
                           f"Enter value for THIS INSTANCE just completed on {today_str}:\n"
                           f"(This will be added to daily total. Use negative to subtract.)")

            default_instance_value = 0.0
            if habit_unit and habit_unit.lower() in ['minutes', 'min', 'm']: default_instance_value = round(work_duration_seconds / 60.0, 2)
            elif habit_unit and habit_unit.lower() in ['hours', 'hrs', 'h']: default_instance_value = round(work_duration_seconds / 3600.0, 2)
            elif habit_unit and habit_unit.lower() in ['seconds', 'sec', 's']: default_instance_value = float(work_duration_seconds)
            
            num_val, ok = QInputDialog.getDouble(self, prompt_title, prompt_text,
                                                 value=default_instance_value, 
                                                 min=-999999.0, max=999999.0, decimals=2)
            if ok:
                value_this_instance = num_val
                proceed_with_instance_value = True
        
        if proceed_with_instance_value and value_this_instance is not None:
            logs_for_day = self.db_manager.get_habit_logs_for_date_range(today_str, today_str)
            current_cumulative_value_db = None
            for (log_aid, log_date), log_val in logs_for_day.items():
                if log_aid == activity_id and log_date == today_str:
                    current_cumulative_value_db = log_val
                    break
            
            new_daily_total = None

            if habit_type == HABIT_TYPE_BINARY:
                new_daily_total = 1.0 
            elif habit_type == HABIT_TYPE_PERCENTAGE:
                base_total = current_cumulative_value_db if current_cumulative_value_db is not None else 0.0
                new_daily_total = min(100.0, base_total + value_this_instance)
            elif habit_type == HABIT_TYPE_NUMERIC:
                base_total = current_cumulative_value_db if current_cumulative_value_db is not None else 0.0
                new_daily_total = base_total + value_this_instance
            
            should_log_to_db = False
            if habit_type == HABIT_TYPE_BINARY:
                if new_daily_total == 1.0 and (current_cumulative_value_db is None or current_cumulative_value_db != 1.0):
                    should_log_to_db = True 
            elif new_daily_total is not None:
                 if new_daily_total != current_cumulative_value_db or \
                   (current_cumulative_value_db is None): 
                    if habit_type == HABIT_TYPE_NUMERIC and current_cumulative_value_db is None and new_daily_total == 0.0 and value_this_instance == 0.0:
                        reply_zero = QMessageBox.question(self, "Confirm Zero Log",
                                                     f"Log an explicit total of '0' for '{activity_name}' on {today_str}, or skip logging for this instance?", # Use activity_name
                                                     buttons=QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Skip | QMessageBox.StandardButton.Cancel,
                                                     defaultButton=QMessageBox.StandardButton.Skip)
                        if reply_zero == QMessageBox.StandardButton.Save:
                            should_log_to_db = True
                        else: 
                            should_log_to_db = False
                    else:
                        should_log_to_db = True
            
            if should_log_to_db:
                print(f"MainWindow.prompt_and_log_habit: Logging to DB: ActID={activity_id}, Date={today_str}, NewDailyTotal={new_daily_total} (InstanceValue={value_this_instance}, PrevDBTotal={current_cumulative_value_db})")
                if self.db_manager.log_habit(activity_id, today_str, new_daily_total):
                    unit_suffix = ""
                    if habit_type == HABIT_TYPE_PERCENTAGE: unit_suffix = "%"
                    elif habit_type == HABIT_TYPE_NUMERIC and habit_unit: unit_suffix = f" {habit_unit}"
                    
                    QMessageBox.information(self, "Habit Logged", 
                                            f"Habit instance for '{activity_name}' logged.\n" # Use activity_name
                                            f"Daily total for {today_str} is now: {new_daily_total:g}{unit_suffix}.")
                    self.habits_updated.emit()
                else:
                    QMessageBox.warning(self, "Error", f"Failed to log habit for '{activity_name}'.") # Use activity_name
            else:
                print(f"MainWindow.prompt_and_log_habit: No change to log for habit '{activity_name}' on {today_str} or instance value was such that no update was needed.")
        else:
            print(f"-- User cancelled providing instance value, or not applicable (e.g. binary not confirmed as done), for habit '{activity_name}'.")
   
    def check_and_prompt_save_countdown(self, actual_duration, activity_id, activity_name, average_duration_at_start):
        # (This method is likely not needed with the current save logic but kept for reference)
        # ...
        return True # Assume save is always desired for now


# --- End of Modified MainWindow Class ---

# Make sure the rest of the classes (DatabaseManager, HeatmapWidget, TimerWindow, Dialogs, Delegate, Model)
# and the __main__ block remain as they were in the original code provided.
# Only the MainWindow class needs to be replaced with the version above.

# =============================================================
# (Keep all other classes like DatabaseManager, HeatmapWidget, TimerWindow,
#  EntryManagementDialog, DailySnapshotDialog, ConfigureHabitDialog,
#  HabitCellDelegate, HabitTableModel, HabitTrackerDialog exactly as they were)
# =============================================================

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

# --- End of Modified MainWindow Class ---

# (Rest of the code: DatabaseManager, other Widgets, Dialogs, Model, Delegate, __main__ remains the same)

# ... (Keep all other classes as they were) ...

# --- Application Launch ---
if __name__ == '__main__':
    # ... (High DPI settings) ...
    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())
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