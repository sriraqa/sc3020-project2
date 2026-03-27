# interface.py
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QSplitter, QFrame, QMessageBox,
    QDialog, QLineEdit, QFormLayout, QDialogButtonBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor, QTextCharFormat, QSyntaxHighlighter, QTextCursor

from preprocessing import connect_db, get_qep, get_aqps
from annotation import generate_annotations
import json


# ─────────────────────────────────────────────
# SQL Syntax Highlighter
# ─────────────────────────────────────────────
class SQLHighlighter(QSyntaxHighlighter):
    """Basic SQL syntax highlighting for the query input panel."""
    def __init__(self, document):
        super().__init__(document)
        self.rules = []

        # Keywords
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#569cd6"))
        keyword_format.setFontWeight(QFont.Bold)
        keywords = ["SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER",
                    "OUTER", "ON", "GROUP", "BY", "ORDER", "HAVING", "LIMIT",
                    "AND", "OR", "NOT", "IN", "AS", "DISTINCT", "COUNT", "SUM",
                    "AVG", "MIN", "MAX", "UNION", "ALL", "INSERT", "UPDATE",
                    "DELETE", "CREATE", "DROP", "INDEX"]
        for kw in keywords:
            self.rules.append((f"\\b{kw}\\b", keyword_format))

        # Strings
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#ce9178"))
        self.rules.append(("'[^']*'", string_format))

        # Numbers
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#b5cea8"))
        self.rules.append(("\\b[0-9]+\\.?[0-9]*\\b", number_format))

    def highlightBlock(self, text):
        import re
        for pattern, fmt in self.rules:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


# ─────────────────────────────────────────────
# DB Connection Dialog
# ─────────────────────────────────────────────
class ConnectionDialog(QDialog):
    """Dialog to input PostgreSQL connection details."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect to PostgreSQL")
        self.setMinimumWidth(350)

        layout = QFormLayout()

        self.host_input     = QLineEdit("127.0.0.1")
        self.port_input     = QLineEdit("5432")
        self.dbname_input   = QLineEdit("tpch")
        self.user_input     = QLineEdit("postgres")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)

        layout.addRow("Host:",     self.host_input)
        layout.addRow("Port:",     self.port_input)
        layout.addRow("Database:", self.dbname_input)
        layout.addRow("Username:", self.user_input)
        layout.addRow("Password:", self.password_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.setLayout(layout)

    def get_credentials(self):
        return {
            "host":     self.host_input.text(),
            "port":     self.port_input.text(),
            "dbname":   self.dbname_input.text(),
            "user":     self.user_input.text(),
            "password": self.password_input.text()
        }


# ─────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.conn = None
        self.setWindowTitle("SC3020 — Query Plan Annotator")
        self.setMinimumSize(1200, 800)
        self._build_ui()

    def _build_ui(self):
        # ── Central widget ──
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # ── Top bar: connection status + button ──
        top_bar = QHBoxLayout()
        self.conn_status = QLabel("⚫  Not connected")
        self.conn_status.setStyleSheet("color: grey; font-weight: bold;")
        connect_btn = QPushButton("Connect to DB")
        connect_btn.setFixedWidth(140)
        connect_btn.clicked.connect(self.open_connection_dialog)
        top_bar.addWidget(self.conn_status)
        top_bar.addStretch()
        top_bar.addWidget(connect_btn)
        main_layout.addLayout(top_bar)

        # ── Main splitter (left | right) ──
        splitter = QSplitter(Qt.Horizontal)

        # ── LEFT PANEL: SQL input + annotated output ──
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # SQL input
        left_layout.addWidget(self._section_label("SQL Query"))
        self.sql_input = QTextEdit()
        self.sql_input.setPlaceholderText(
            "Paste your SQL query here...\n\nExample:\n"
            "SELECT * FROM customer C, orders O\n"
            "WHERE C.c_custkey = O.o_custkey"
        )
        self.sql_input.setFont(QFont("Courier New", 11))
        self.sql_input.setMinimumHeight(180)
        SQLHighlighter(self.sql_input.document())
        left_layout.addWidget(self.sql_input)

        # Execute button
        self.run_btn = QPushButton("▶  Annotate Query")
        self.run_btn.setFixedHeight(38)
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #0e639c;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #1177bb; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        self.run_btn.clicked.connect(self.run_annotation)
        left_layout.addWidget(self.run_btn)

        # Annotated output
        left_layout.addWidget(self._section_label("Annotated Query"))
        self.annotated_output = QTextEdit()
        self.annotated_output.setReadOnly(True)
        self.annotated_output.setFont(QFont("Courier New", 11))
        self.annotated_output.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        left_layout.addWidget(self.annotated_output)

        splitter.addWidget(left_panel)

        # ── RIGHT PANEL: QEP tree + raw JSON ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addWidget(self._section_label("Query Execution Plan (Tree View)"))
        self.qep_tree_view = QTextEdit()
        self.qep_tree_view.setReadOnly(True)
        self.qep_tree_view.setFont(QFont("Courier New", 10))
        self.qep_tree_view.setStyleSheet("background-color: #1e1e1e; color: #9cdcfe;")
        right_layout.addWidget(self.qep_tree_view)

        right_layout.addWidget(self._section_label("Raw QEP (JSON)"))
        self.qep_json_view = QTextEdit()
        self.qep_json_view.setReadOnly(True)
        self.qep_json_view.setFont(QFont("Courier New", 9))
        self.qep_json_view.setStyleSheet("background-color: #1e1e1e; color: #808080;")
        self.qep_json_view.setMaximumHeight(200)
        right_layout.addWidget(self.qep_json_view)

        splitter.addWidget(right_panel)
        splitter.setSizes([600, 500])
        main_layout.addWidget(splitter)

        # ── Status bar ──
        self.statusBar().showMessage("Ready — connect to a database to begin.")

    def _section_label(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; font-size: 12px; margin-top: 4px;")
        return label

    # ─────────────────────────────────────────────
    # DB Connection
    # ─────────────────────────────────────────────
    def open_connection_dialog(self):
        dialog = ConnectionDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            creds = dialog.get_credentials()
            try:
                self.conn = connect_db(
                    dbname=creds["dbname"],
                    user=creds["user"],
                    password=creds["password"],
                    host=creds["host"],
                    port=creds["port"]
                )
                self.conn_status.setText(
                    f"🟢  Connected to '{creds['dbname']}' as {creds['user']}"
                )
                self.conn_status.setStyleSheet("color: #4ec94e; font-weight: bold;")
                self.statusBar().showMessage("Connected successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Connection Failed", str(e))

    # ─────────────────────────────────────────────
    # Run Annotation
    # ─────────────────────────────────────────────
    def run_annotation(self):
        if not self.conn:
            QMessageBox.warning(self, "Not Connected",
                                "Please connect to a database first.")
            return

        sql = self.sql_input.toPlainText().strip()
        if not sql:
            QMessageBox.warning(self, "Empty Query", "Please enter an SQL query.")
            return

        try:
            self.statusBar().showMessage("Fetching query plans...")
            QApplication.processEvents()

            # Fetch plans
            qep  = get_qep(self.conn, sql)
            aqps = get_aqps(self.conn, sql)

            # Generate annotations
            result = generate_annotations(sql, qep, aqps)

            # Display annotated query
            self._display_annotated_query(sql, result)

            # Display QEP tree
            tree_text = self._build_tree_text(qep["Plan"], prefix="")
            self.qep_tree_view.setPlainText(tree_text)

            # Display raw JSON
            self.qep_json_view.setPlainText(json.dumps(qep, indent=2))

            self.statusBar().showMessage("Annotation complete.")

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self.statusBar().showMessage("Error occurred.")

    # ─────────────────────────────────────────────
    # Display Helpers
    # ─────────────────────────────────────────────
    def _display_annotated_query(self, sql, result):
        """Display the SQL query with annotations appended."""
        self.annotated_output.clear()
        cursor = self.annotated_output.textCursor()

        # SQL in white
        sql_fmt = QTextCharFormat()
        sql_fmt.setForeground(QColor("#d4d4d4"))
        sql_fmt.setFont(QFont("Courier New", 11))
        cursor.insertText(sql + "\n\n", sql_fmt)

        # Scan annotations in green
        if result["scans"]:
            header_fmt = QTextCharFormat()
            header_fmt.setForeground(QColor("#4ec9b0"))
            header_fmt.setFontWeight(QFont.Bold)
            cursor.insertText("── Table Access ──\n", header_fmt)

            note_fmt = QTextCharFormat()
            note_fmt.setForeground(QColor("#9cdcfe"))
            for table, note in result["scans"].items():
                cursor.insertText(f"• {note}\n", note_fmt)
            cursor.insertText("\n")

        # Join annotations in yellow
        if result["joins"]:
            header_fmt = QTextCharFormat()
            header_fmt.setForeground(QColor("#dcdcaa"))
            header_fmt.setFontWeight(QFont.Bold)
            cursor.insertText("── Join Operations ──\n", header_fmt)

            note_fmt = QTextCharFormat()
            note_fmt.setForeground(QColor("#ce9178"))
            for note in result["joins"]:
                cursor.insertText(f"• {note}\n", note_fmt)
            cursor.insertText("\n")

        # Other annotations in purple
        if result["others"]:
            header_fmt = QTextCharFormat()
            header_fmt.setForeground(QColor("#c586c0"))
            header_fmt.setFontWeight(QFont.Bold)
            cursor.insertText("── Other Operations ──\n", header_fmt)

            note_fmt = QTextCharFormat()
            note_fmt.setForeground(QColor("#d7ba7d"))
            for note in result["others"]:
                cursor.insertText(f"• {note}\n", note_fmt)

        self.annotated_output.setTextCursor(cursor)

    def _build_tree_text(self, node, prefix="", is_last=True):
        """Recursively build a text tree of the query plan."""
        connector = "└── " if is_last else "├── "
        node_type = node.get("Node Type", "Unknown")
        relation  = node.get("Relation Name", "")
        cost      = node.get("Total Cost", "?")
        condition = (node.get("Hash Cond") or node.get("Merge Cond") or
                     node.get("Index Cond") or node.get("Filter") or "")

        line = f"{prefix}{connector}{node_type}"
        if relation:
            line += f" on {relation}"
        line += f"  [cost: {cost}]"
        if condition:
            line += f"\n{prefix}{'    ' if is_last else '│   '}   cond: {condition}"

        result = line + "\n"

        children = node.get("Plans", [])
        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(children):
            result += self._build_tree_text(
                child, child_prefix, is_last=(i == len(children) - 1)
            )
        return result


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────
def launch_gui():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette
    from PyQt5.QtGui import QPalette
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor("#1e1e1e"))
    palette.setColor(QPalette.WindowText,      QColor("#d4d4d4"))
    palette.setColor(QPalette.Base,            QColor("#252526"))
    palette.setColor(QPalette.AlternateBase,   QColor("#1e1e1e"))
    palette.setColor(QPalette.Text,            QColor("#d4d4d4"))
    palette.setColor(QPalette.Button,          QColor("#3c3c3c"))
    palette.setColor(QPalette.ButtonText,      QColor("#d4d4d4"))
    palette.setColor(QPalette.Highlight,       QColor("#0e639c"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())