# Ritual - Time & Activity Tracker (v0.09362)⏱️

Ritual is a desktop application designed to help you meticulously track your time across various activities, manage your tasks efficiently, and build positive daily habits. Gain insights into your productivity and cultivate consistency with an intuitive interface and powerful tracking tools.

---

## ✨ Key Features

* **Hierarchical Activity Management**: Organize your tasks and projects in a nested tree structure. Add, rename, delete, and rearrange activities with ease.
* **Versatile Time Tracking**:
    * **Standard Timers**: Start timers for one or multiple selected tasks.
    * **Countdown Timers**: Work in focused bursts using countdowns based on your average time for an activity.
    * **Multi-Tasking**: Run multiple timers (standard or countdown, but not mixed types simultaneously) each in its own floating window.
* **Post-Session Review**: After stopping a timer, review all recorded work/break intervals. Edit durations or discard intervals before saving them permanently, ensuring data accuracy.
    * **Smart Highlighting**: Intervals and session totals that deviate significantly (>10%) from historical averages are visually highlighted.
* **Comprehensive Habit Tracking**:
    * Configure any activity as a daily habit (Binary, Percentage, or Numeric with custom units & goals).
    * Log habit completion in an intuitive monthly grid.
    * Visualize yearly progress with an animated **Habit Heatmap**.
    * Track **Global Daily Streaks** based on overall habit completion.
* **In-Depth Statistics & Reports**:
    * **Status Bar**: Quick stats for hovered or selected activities (average entry/session times, branch totals).
    * **Daily Snapshot**: Detailed breakdown of time spent per activity (including sub-activities) for any selected day, plus a list of all entries.
    * **Manual Entry Management**: Add, edit, or delete historical time entries.
* **Customizable Interface**: Includes a dark theme for comfortable viewing.

---

## 🚀 Getting Started

### Prerequisites

* Python 3.x
* PyQt6 library (`pip install PyQt6`)

### Running the Application

1.  Save the application code as a Python file (e.g., `ritual_tracker.py`).
2.  Open a terminal or command prompt.
3.  Navigate to the directory where you saved the file.
4.  Run the script using:
    ```bash
    python ritual_tracker.py
    ```
    The application window will appear, and a `time_tracker.db` SQLite database file will be created in the same directory to store your data.

---

## 📖 Core Usage Overview

### 1. Managing Activities 📂

* **Add**: Right-click in the activity tree area to add a top-level activity, or right-click an existing activity to add a sub-activity.
* **Rename/Delete/Configure Habit**: Right-click an activity to access these options.
* **Select**: Click to select. Use `Ctrl+Click` or `Shift+Click` to select multiple activities for starting timers.

### 2. Tracking Time ⏳

* **Start Timers**: Select one or more activities, then click "**Start Selected Task(s)**" or "**Start Selected Countdown(s)**".
    * Each active timer appears in a small, movable window.
    * Use the "**Pause**", "**Resume**", or "**End**" buttons in the timer window.
* **Post-Session Review**: When you click "**End**":
    * A dialog appears listing all work/break intervals from that session.
    * **Checkbox**: Uncheck any interval you don't want to save.
    * **Edit Duration**: Double-click an interval's "Final Duration" or select it and use the "Edit" button to adjust the time.
    * **Remove**: Remove an interval entirely from the review.
    * Click "**Save Marked & Close**" to log the selected intervals.

### 3. Tracking Habits ✅

* **Configure**: Right-click an activity -> "**Configure '[Activity Name]' as Habit...**". Choose type (Binary, Percentage, Numeric) and set goal/unit if applicable.
* **Log**: Click "**Habit Tracker**". Double-click a cell for a habit/day to log its status or value.
    * Binary: Toggles done/not done.
    * Percentage: Enter % (0-100).
    * Numeric: Enter a value to add to the daily total.
* **View**: The **Habit Heatmap** on the main window visualizes yearly progress.

### 4. Viewing Stats & Progress 📊

* **Status Bar**: Automatically updates with info on hovered or selected activities.
* **Daily Snapshot**: Click "**Daily Snapshot**", pick a date, and see a detailed time breakdown.
* **Manage Entries**: Select an activity and click "**Manage Entries**" to view/edit its entire time log history.
* **Global Streaks**: Check your current and maximum daily habit streaks on the main window.

---

Enjoy using Ritual to master your time and build lasting habits!