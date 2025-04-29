# Ritual Time Tracker (v0.07)

A simple desktop application for tracking time spent on hierarchical activities, built with Python and PyQt6.

---

## Main Idea

Ritual Time Tracker helps you organize your tasks or activities in a tree-like structure (parent activities with sub-activities) and track the time you spend on them. It provides two main modes for time tracking: a simple stopwatch (**Work**/**Track**) and a **Countdown** timer based on the average time previously spent on an activity.

---

## Key Features

* **Hierarchical Activity Management:**
    * Add top-level activities.
    * Add sub-activities under existing ones to create a tree structure.
    * Rename activities.
    * Delete activities (including all sub-activities and associated time entries).
    * Activities are managed via a right-click context menu on the activity tree.
* **Time Tracking Modes:**
    * **Work Timer:** A simple stopwatch to track elapsed time for the selected activity. Start it and stop it when you're done.
    * **Countdown Timer:** Starts a timer based on the calculated average duration of previously logged entries for the selected activity. Useful for timeboxing or focusing for a specific duration. The timer window turns red if you exceed the average time.
* **Floating Timer Window:**
    * A small, always-on-top window displays the current timer (either counting up or down), which can be moved around the screen.
* **Entry Management:**
    * View all time entries recorded for a specific activity.
    * Manually add new time entries with specific dates, times, and durations.
    * Edit the duration of existing entries.
    * Delete specific time entries.
* **Daily Snapshot:**
    * View a summary of time spent across all activities for a selected date.
    * Shows both a hierarchical summary (total time per activity branch) and a detailed list of individual entries for the day.
* **Data Storage:**
    * Uses a local SQLite database (`time_tracker.db`) to store activities and time entries.
* **Dark Theme:**
    * Features a dark user interface for comfortable viewing.

---

## Usage Guide

1.  **Running the Application:**
    * Ensure you have the necessary dependencies installed (see below).
    * Run the Python script: `python time_tracker_app.py`

2.  **Managing Activities:**
    * **Add:** Right-click in the empty space of the "Activities" tree view to add a top-level activity. Right-click on an existing activity to add a sub-activity under it.
    * **Rename/Delete:** Right-click on the activity you want to modify and select "Rename" or "Delete" from the context menu.

3.  **Tracking Time:**
    * **Select:** Click on an activity in the tree. The status bar will show the selected activity and its average/total time.
    * **Start Work Timer:** Click the `Start Work` button. The floating timer window will appear.
    * **Start Countdown Timer:** If the selected activity has previous time entries, the `Start Countdown` button will be enabled. Click it to start the countdown based on the average time.
    * **Stop Timer:** Click the button again (it will now say `Stop Work` or `Stop Countdown`) to stop the timer. The elapsed time will be recorded automatically for the "Work" timer. For the "Countdown" timer, you might be prompted to save the entry if the duration significantly differed from the average.

4.  **Managing Entries:**
    * Select an activity.
    * Click the `Manage Entries` button.
    * Use the buttons in the dialog to add, edit, or delete time entries for that specific activity.

5.  **Viewing Daily Snapshot:**
    * Click the `Daily Snapshot` button.
    * Select a date using the date picker.
    * Click `Show` to view the aggregated summary and detailed entries for that day.

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
5.  The application window will appear, and the `time_tracker.db` file will be created in the same directory if it doesn't exist.

---