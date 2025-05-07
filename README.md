<<<<<<< HEAD
# Ritual Time Tracker (v0.091)
=======
# Ritual Time Tracker (v0.09)
>>>>>>> b66be4e9f43ee7872dbfae28dc32de542a98bdac

A desktop application for tracking time spent on hierarchical activities and monitoring daily habit completion, built with Python and PyQt6.

---

## Main Idea

Ritual Time Tracker helps you organize your tasks or activities in a tree-like structure (parent activities with sub-activities) and track the time you spend on them. It provides two main modes for time tracking: a simple stopwatch (**Track**) and a **Countdown** timer based on the average time previously spent on an activity. **It now also includes features for tracking daily habit completion.**

---

## Key Features

* **Hierarchical Activity Management:**
    * Add top-level activities.
    * Add sub-activities under existing ones to create a tree structure.
    * Rename activities.
    * Delete activities (including all sub-activities and associated data).
    * Activities are managed via a right-click context menu on the activity tree.
    * **Configure activities as trackable habits** (see Habit Tracking below).
* **Time Tracking Modes:**
    * **Work/Tracking Timer:** A simple stopwatch to track elapsed time for the selected activity.
    * **Countdown Timer:** Starts a timer based on the calculated average duration of previously logged time entries for the selected activity. Useful for timeboxing. The timer window turns red if you exceed the average time.
    * Optional prompt to log associated habit completion after stopping a timer.
* **Floating Timer Window:**
    * A small, always-on-top window displays the current timer (either counting up or down), which can be moved around the screen.
* **Time Entry Management:**
    * View all time entries recorded for a specific activity.
    * Manually add new time entries with specific dates, times, and durations.
    * Edit the duration of existing entries.
    * Delete specific time entries.
* **Habit Tracking:**
    * **Configuration:** Activities can be marked as habits with types:
        * *Binary:* Done / Not Done.
        * *Percentage:* 0-100% in 25% increments.
        * *Numeric:* Track any number (e.g., pages read, km run) with optional units and a daily goal.
    * **Tracker Dialog:** A dedicated dialog (`Habit Tracker` button) displays a monthly grid.
    * **Logging:** Log daily habit progress via double-click interaction in the grid (toggle binary, cycle percentage, enter numeric value).
    * **Visualization:** Includes an animated yearly heatmap on the main window showing habit completion density. Days where average numeric goal completion exceeds 70% are highlighted in the tracker dialog header.
    * **Reordering:** Habits can be reordered in the tracker view using the row header context menu.
* **Daily Snapshot:**
    * View a summary of **time spent** across all activities for a selected date.
    * Shows both a hierarchical time summary (total time per activity branch) and a detailed list of individual time entries for the day. *(Note: Does not currently show habit data)*.
* **Technical:**
    * Uses a local SQLite database (`time_tracker.db`) to store activities, time entries, and habit logs.
    * **Timezone Handling:** Stores all timestamps in UTC and converts to the user's local time for display, preventing timezone offset errors.
* **Dark Theme:**
    * Features a dark user interface for comfortable viewing.

---

## Usage Guide

1.  **Running the Application:**
    * Ensure you have the necessary dependencies installed (see below).
    * Run the Python script: `python time_tracker_app.py`

2.  **Managing Activities:**
    * **Add:** Right-click in the empty space of the "Activities" tree view to add a top-level activity. Right-click on an existing activity to add a sub-activity under it.
    * **Rename/Delete:** Right-click on the activity you want to modify and select "Rename" or "Delete".
    * **Configure Habit:** Right-click an activity and select "Configure as Habit...". Check the box, choose the type (Binary, Percentage, Numeric), and fill in optional Unit and Goal for Numeric types.

3.  **Tracking Time:**
    * **Select:** Click on an activity in the tree.
    * **Start Work Timer:** Click the `Start Tracking` button.
    * **Start Countdown Timer:** If the activity has previous time entries, click `Start Countdown`.
    * **Stop Timer:** Click the button again (`Stop Tracking` or `Stop Countdown`).
    * **Log Habit (Optional):** If the finished activity is a configured habit, you may be prompted to log its completion for the day.

4.  **Tracking Habits:**
    * **Open Tracker:** Click the `Habit Tracker` button.
    * **Navigate:** Use "< Prev", "Next >", or "Today" to change the displayed month.
    * **Log:** Double-click a cell in the grid corresponding to a habit and date. This will toggle binary habits, cycle through percentage options, or open an input dialog for numeric habits. Entering '0' for a numeric habit prompts confirmation to either log zero or clear the entry (set to None).
    * **View Heatmap:** Observe the yearly heatmap on the main window for a quick overview of daily habit completion intensity.
    * **Reorder Habits:** In the Habit Tracker dialog, right-click on a habit name in the *row header* (left side) and select "Move Up" or "Move Down".

5.  **Managing Time Entries:**
    * Select an activity.
    * Click the `Manage Entries` button.
    * Use the dialog buttons to add, edit, or delete **time entries** (not habit logs) for that specific activity.

6.  **Viewing Daily Time Snapshot:**
    * Click the `Daily Snapshot` button.
    * Select a date.
    * Click `Show` to view the **time** summary and detailed **time entries** for that day.

---

## Dependencies

* Python 3.x
* PyQt6 (`pip install PyQt6`)
* SQLite (usually built into Python)

---

## How to Run

1.  Make sure Python 3 and pip are installed.
2.  Install the required library:
    ```bash
    pip install PyQt6
    ```
3.  Navigate to the directory containing `time_tracker_app.py`.
4.  Run the application from your terminal:
    ```bash
    python time_tracker_app.py
    ```
5.  The application window will appear, and the `time_tracker.db` file will be created or updated in the same directory.

---
