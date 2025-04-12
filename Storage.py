import os
import time
import csv
from collections import defaultdict
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QFileDialog, QProgressBar, QTreeWidget, QTreeWidgetItem,
    QHBoxLayout, QLineEdit, QHeaderView, QMessageBox,
    QStackedWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal,QTimer
from PyQt6.QtGui import QPalette, QColor, QDesktopServices
from PyQt6.QtCore import QUrl
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import mplcursors

class FileProcessorThread(QThread):
    progress_update = pyqtSignal(int, str)
    result_ready = pyqtSignal(list)
    cancelled = pyqtSignal()
    live_file_signal = pyqtSignal(tuple)
    eta_signal = pyqtSignal(str)

    def __init__(self, root_directory, threshold_gb, extensions):
        super().__init__()
        self.root_directory = root_directory
        self.threshold_gb = threshold_gb or 1.0
        self.extensions = [ext.strip().lower() for ext in extensions if ext.strip()]
        self.cancel_requested = False
        self.paused = False

    def get_file_size(self, file_path):
        try:
            size = os.path.getsize(file_path)
            return size / (1024 ** 2), size / (1024 ** 3)
        except:
            return None, None

    def run(self):
        results = []
        files_to_process = []

        for dirpath, _, filenames in os.walk(self.root_directory):
            for filename in filenames:
                if self.cancel_requested:
                    self.cancelled.emit()
                    return

                file_path = os.path.abspath(os.path.join(dirpath, filename))

                if self.extensions:
                    if not any(filename.lower().endswith(ext) for ext in self.extensions):
                        continue

                if not os.path.exists(file_path):
                    continue

                size_mb, size_gb = self.get_file_size(file_path)
                if size_gb is None:
                    continue

                if size_gb > self.threshold_gb:
                    files_to_process.append((filename, file_path, size_mb, size_gb))

        total_files = len(files_to_process)
        if total_files == 0:
            self.progress_update.emit(100, "No files found above threshold.")
            self.result_ready.emit([])
            return

        start_time = time.time()

        for i, (filename, file_path, size_mb, size_gb) in enumerate(files_to_process):
            while self.paused:
                time.sleep(0.1)
            if self.cancel_requested:
                self.cancelled.emit()
                return

            results.append((filename, file_path, f"{size_mb:.2f}", f"{size_gb:.2f}"))
            self.live_file_signal.emit((filename, file_path, f"{size_mb:.2f}", f"{size_gb:.2f}"))

            elapsed = time.time() - start_time
            remaining = int((elapsed / (i + 1)) * (total_files - i - 1))
            progress_percent = int((i + 1) / total_files * 100)
            self.progress_update.emit(progress_percent, f"{filename} | {i+1} of {total_files} | ~{remaining}s left")
            self.eta_signal.emit(f"ETA: ~{remaining}s")
            QApplication.processEvents()
            self.msleep(50)

        self.result_ready.emit(results)

    def cancel(self):
        self.cancel_requested = True

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

class FileAnalyzerUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("📁 File Analyzer - Dark Mode")
        self.resize(1200, 700)
        self.init_dark_theme()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        controls_layout = QHBoxLayout()
        self.folder_button = QPushButton("📁 Select Folder")
        self.folder_button.setStyleSheet("font-weight: bold; background-color: #2e8b57; color: white")
        self.folder_button.clicked.connect(self.select_folder)

        self.size_input = QLineEdit()
        self.size_input.setPlaceholderText("(default:0.1GB)")
        self.size_input.setMaximumWidth(120)
        self.size_input.setStyleSheet("color: white;")

        self.ext_input = QLineEdit()
        self.ext_input.setPlaceholderText("Extensions (e.g., .mp4,.zip)")
        self.ext_input.setMaximumWidth(180)
        self.ext_input.setStyleSheet("color: white;")

        self.start_button = QPushButton("▶ Start Scan")
        self.start_button.setStyleSheet("font-weight: bold; background-color: #4169e1; color: white")
        self.start_button.clicked.connect(self.start_scan)

        self.cancel_button = QPushButton("⛔ Cancel")
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.cancel_button.setEnabled(False)

        self.pause_button = QPushButton("⏸ Pause")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.toggle_pause_resume)

        self.export_button = QPushButton("💾 Export CSV")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_csv)

        self.toggle_button = QPushButton("📊 Toggle View")
        self.toggle_button.clicked.connect(self.toggle_view)

        controls_layout.addWidget(self.folder_button)
        controls_layout.addWidget(self.size_input)
        controls_layout.addWidget(self.ext_input)
        controls_layout.addWidget(self.start_button)
        controls_layout.addWidget(self.pause_button)
        controls_layout.addWidget(self.cancel_button)
        controls_layout.addWidget(self.export_button)
        controls_layout.addWidget(self.toggle_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(18)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label = QLabel("Status: Waiting")

        self.table = QTreeWidget()
        self.table.setHeaderLabels(["File Name", "File Path", "Size (MB)", "Size (GB)"])
        self.table.setColumnCount(4)
        self.table.setSortingEnabled(True)
        self.table.setAnimated(True)
        self.table.itemClicked.connect(self.open_file_from_table)
        self.folder_items = {}

        self.chart_canvas = FigureCanvas(Figure())

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.table)
        self.stacked_widget.addWidget(self.chart_canvas)

        layout.addLayout(controls_layout)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addWidget(self.stacked_widget)
        
        footer = QLabel("Developed by Chandan S")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet("color: white; font-size: 12pt; margin-top: 10px;")
        layout.addWidget(footer)
        
        self.setLayout(layout)

    def init_dark_theme(self):
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
        dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        QApplication.instance().setPalette(dark_palette)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.folder_path = folder
            self.status_label.setText(f"Selected folder: {folder}")

    def start_scan(self):
        if not hasattr(self, "folder_path") or not self.folder_path:
            self.status_label.setText("Please select a folder.")
            return

        try:
            threshold = float(self.size_input.text()) if self.size_input.text() else 0.1
        except ValueError:
            self.status_label.setText("Invalid size value.")
            return

        extensions = self.ext_input.text().split(",")
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Scanning...")
        self.table.clear()
        self.folder_items.clear()

        self.thread = FileProcessorThread(self.folder_path, threshold, extensions)
        self.thread.progress_update.connect(self.update_progress)
        self.thread.result_ready.connect(self.show_results)
        self.thread.cancelled.connect(self.thread_cancelled)
        self.thread.live_file_signal.connect(self.add_row)
        self.thread.eta_signal.connect(self.update_eta_title)
        self.thread.start()

        self.cancel_button.setEnabled(True)
        self.pause_button.setEnabled(True)
        self.export_button.setEnabled(False)

    def update_progress(self, value, status_text):
        self.progress_bar.setValue(value)
        self.status_label.setText(f"Processing: {status_text}")
        QApplication.processEvents()

    def update_eta_title(self, eta):
        self.setWindowTitle(f"File Analyzer - {eta}")

    def add_row(self, row_data):
        filename, filepath, size_mb, size_gb = row_data
        folder = os.path.dirname(filepath)

        if folder not in self.folder_items:
            folder_item = QTreeWidgetItem([os.path.basename(folder), folder, "", ""])
            self.folder_items[folder] = folder_item
            self.table.addTopLevelItem(folder_item)
        else:
            folder_item = self.folder_items[folder]

        child_item = QTreeWidgetItem([filename, filepath, size_mb, size_gb])
        if float(size_gb) > 5.0:
            child_item.setBackground(3, QColor("red"))
        folder_item.addChild(child_item)

    def show_results(self, results):
        self.status_label.setText(f"Completed. {len(results)} large files found.")
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.export_button.setEnabled(True)
        self.setWindowTitle("File Analyzer - Done")
        self.table.expandAll()

        QTimer.singleShot(10,self.adjust_columns_to_fit)
        
        self.render_funnel_chart()

    def adjust_columns_to_fit(self):
        total_width = self.table.viewport().width()
        column_count = self.table.columnCount()
        
        # Determine max needed width for each column
        self.table.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        widths = [self.table.columnWidth(i) for i in range(column_count)]
        total_content_width = sum(widths)

        if total_content_width < total_width:
            # Scale widths proportionally to fill the space
            extra_space = total_width - total_content_width
            per_column_extra = extra_space // column_count
            for i in range(column_count):
                self.table.setColumnWidth(i, widths[i] + per_column_extra)

            self.table.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)


    def render_funnel_chart(self):
        self.chart_canvas.figure.clf()
        ax = self.chart_canvas.figure.add_subplot(111)
        ax.set_title("File Size Funnel Chart", fontsize=14)

        sizes = []
        labels = []

        for folder, item in self.folder_items.items():
            for i in range(item.childCount()):
                child = item.child(i)
                size_gb = float(child.text(3))
                label = child.text(0)
                sizes.append(size_gb)
                labels.append(label)

        if not sizes:
            ax.text(0.5, 0.5, "No data to display", ha='center', va='center', color='white')
        else:
            sorted_data = sorted(zip(sizes, labels), reverse=True)
            sizes, labels = zip(*sorted_data)
            y = range(len(sizes))
            width = [s / max(sizes) for s in sizes]
            bars = ax.barh(y, width, height=0.6, left=[(1 - w) / 2 for w in width], color=[plt.cm.viridis(i / len(sizes)) for i in range(len(sizes))])

            ax.invert_yaxis()
            ax.axis('off')

            cursor = mplcursors.cursor(bars, hover=True)
            cursor.connect("add", lambda sel: sel.annotation.set_text(f"{labels[sel.index]}\n{sizes[sel.index]:.2f} GB"))

        self.chart_canvas.draw()


    def toggle_view(self):
        index = self.stacked_widget.currentIndex()
        new_index = 1 if index == 0 else 0
        self.stacked_widget.setCurrentIndex(new_index)
        self.toggle_button.setText("📁 Tree View" if new_index == 1 else "📊 Chart View")

    def open_file_from_table(self, item, column):
        if column == 0 or column == 1:
            path = item.text(1)
            if os.path.exists(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def cancel_scan(self):
        if hasattr(self, "thread"):
            self.thread.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling...")

    def toggle_pause_resume(self):
        if self.thread.paused:
            self.thread.resume()
            self.pause_button.setText("Pause")
        else:
            self.thread.pause()
            self.pause_button.setText("Resume")

    def thread_cancelled(self):
        self.status_label.setText("Scan cancelled.")
        self.progress_bar.setValue(0)
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.setWindowTitle("File Analyzer - Cancelled")

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "results.csv", "CSV Files (*.csv)")
        if not path:
            return

        with open(path, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["File Name", "File Path", "Size (MB)", "Size (GB)"])

            def write_items(item):
                for i in range(item.childCount()):
                    child = item.child(i)
                    writer.writerow([child.text(0), child.text(1), child.text(2), child.text(3)])

            for i in range(self.table.topLevelItemCount()):
                folder_item = self.table.topLevelItem(i)
                write_items(folder_item)

        QMessageBox.information(self, "Export Successful", f"Results exported to {path}")

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = FileAnalyzerUI()
    window.show()
    sys.exit(app.exec())
