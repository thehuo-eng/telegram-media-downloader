def stylesheet(dark):
    bg, panel, text, border, hover = ("#0b1220", "#172235", "#e9f0f9", "#33465f", "#21334d") if dark else (
        "#f4f7fb", "#ffffff", "#1c2d43", "#cbd5e1", "#e7f0fb")
    return f"""
    QWidget#SmartView, QWidget#SmartView QWidget {{ background-color: {bg}; color: {text}; }}
    QWidget#SmartView QLabel {{ background: transparent; font-family: 'Malgun Gothic', 'Segoe UI'; }}
    QWidget#SmartView QPushButton {{ background: {panel}; border: 1px solid {border}; border-radius: 5px; padding: 6px 9px; min-height: 20px; }}
    QWidget#SmartView QPushButton:hover {{ background: {hover}; border-color: #229ed9; }}
    QWidget#SmartView QPushButton:disabled {{ color: #8290a5; }}
    QWidget#SmartView QPushButton#PrimaryButton {{ background: #1689c4; color: white; border-color: #1689c4; font-weight: 600; }}
    QWidget#SmartView QLineEdit, QWidget#SmartView QPlainTextEdit, QWidget#SmartView QSpinBox,
    QWidget#SmartView QComboBox, QWidget#SmartView QDateEdit {{ background: {panel}; border: 1px solid {border}; border-radius: 4px; padding: 5px 7px; min-height: 22px; }}
    QWidget#SmartView QTableView, QWidget#SmartView QListWidget {{ background: {panel}; alternate-background-color: {hover};
        border: 1px solid {border}; gridline-color: {border}; selection-background-color: #247aac; selection-color: white; }}
    QWidget#SmartView QTableView QWidget, QWidget#SmartView QListWidget QWidget {{ background: {panel}; }}
    QWidget#SmartView QHeaderView::section {{ background: {hover}; color: {text}; padding: 7px; border: 0px; border-right: 1px solid {border}; font-weight: 600; }}
    QWidget#SmartView QTabWidget::pane {{ border: 1px solid {border}; background: {bg}; }}
    QWidget#SmartView QTabBar::tab {{ background: {panel}; color: {text}; padding: 10px 12px; margin-right: 2px; border: 1px solid {border}; }}
    QWidget#SmartView QTabBar::tab:selected {{ background: #1689c4; color: white; }}
    QWidget#SmartView QProgressBar {{ background: {panel}; border: 1px solid {border}; border-radius: 4px; text-align: center; min-height: 18px; }}
    QWidget#SmartView QProgressBar::chunk {{ background: #1689c4; }}
    QWidget#SmartView QScrollArea {{ border: none; }}
    """
