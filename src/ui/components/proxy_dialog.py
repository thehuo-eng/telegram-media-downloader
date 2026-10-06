from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QCheckBox, QComboBox, 
    QMessageBox
)
from PySide6.QtCore import Qt, Signal
from ui.views.settings_view import load_config, save_config

class ProxySettingsDialog(QDialog):
    proxy_saved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Network & Proxy Settings")
        self.setMinimumWidth(400)
        self.setup_ui()
        self.load_values()

    def setup_ui(self):
        self.setObjectName("ProxySettingsDialog")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header
        title = QLabel("Network & Proxy Settings")
        title.setObjectName("SectionHeader")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        
        subtitle = QLabel("Configure a proxy server if Telegram is restricted or blocked in your network region.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("MutedText")
        
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)

        # Enable checkbox
        self.chk_enable = QCheckBox("Enable Proxy Server Connection")
        self.chk_enable.stateChanged.connect(self._toggle_fields)
        layout.addWidget(self.chk_enable)

        # Proxy Type & Host & Port
        row1 = QHBoxLayout()
        self.combo_type = QComboBox()
        self.combo_type.addItems(["SOCKS5", "SOCKS4", "HTTP"])
        self.combo_type.setFixedWidth(95)
        self.combo_type.setMinimumHeight(36)
        
        self.input_host = QLineEdit()
        self.input_host.setPlaceholderText("Hostname / IP Address")
        self.input_host.setMinimumHeight(36)
        
        self.input_port = QLineEdit()
        self.input_port.setPlaceholderText("Port")
        self.input_port.setFixedWidth(75)
        self.input_port.setMinimumHeight(36)

        row1.addWidget(self.combo_type)
        row1.addWidget(self.input_host, stretch=1)
        row1.addWidget(self.input_port)
        layout.addLayout(row1)

        # Username & Password
        row2 = QHBoxLayout()
        self.input_user = QLineEdit()
        self.input_user.setPlaceholderText("Username (Optional)")
        self.input_user.setMinimumHeight(36)

        self.input_pass = QLineEdit()
        self.input_pass.setPlaceholderText("Password (Optional)")
        self.input_pass.setEchoMode(QLineEdit.Password)
        self.input_pass.setMinimumHeight(36)

        row2.addWidget(self.input_user)
        row2.addWidget(self.input_pass)
        layout.addLayout(row2)

        # Hint
        self.lbl_hint = QLabel("Supports SOCKS5, SOCKS4, and HTTP proxies (e.g. 127.0.0.1:1080).")
        self.lbl_hint.setObjectName("MutedText")
        self.lbl_hint.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.lbl_hint)

        layout.addSpacing(10)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.setMinimumHeight(36)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton("Save Proxy")
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.setMinimumHeight(36)
        self.btn_save.clicked.connect(self.save_values)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def _toggle_fields(self):
        enabled = self.chk_enable.isChecked()
        self.combo_type.setEnabled(enabled)
        self.input_host.setEnabled(enabled)
        self.input_port.setEnabled(enabled)
        self.input_user.setEnabled(enabled)
        self.input_pass.setEnabled(enabled)

    def load_values(self):
        cfg = load_config()
        p = cfg.get("proxy", {})
        self.chk_enable.setChecked(bool(p.get("enabled", False)))
        self.combo_type.setCurrentText(p.get("type", "SOCKS5"))
        self.input_host.setText(str(p.get("host", "")))
        self.input_port.setText(str(p.get("port", "")))
        self.input_user.setText(str(p.get("user", "")))
        self.input_pass.setText(str(p.get("pass", "")))
        self._toggle_fields()

    def save_values(self):
        port_txt = self.input_port.text().strip()
        if self.chk_enable.isChecked():
            if not self.input_host.text().strip():
                QMessageBox.warning(self, "Invalid Host", "Please enter a proxy host address (e.g. 127.0.0.1).")
                return
            if not port_txt.isdigit() or not (1 <= int(port_txt) <= 65535):
                QMessageBox.warning(self, "Invalid Port", "Please enter a valid port number between 1 and 65535.")
                return

        cfg = load_config()
        cfg["proxy"] = {
            "enabled": self.chk_enable.isChecked(),
            "type": self.combo_type.currentText(),
            "host": self.input_host.text().strip(),
            "port": port_txt,
            "user": self.input_user.text().strip(),
            "pass": self.input_pass.text()
        }
        save_config(cfg)
        self.proxy_saved.emit()
        QMessageBox.information(self, "Proxy Saved", "Proxy configuration saved successfully!")
        self.accept()
