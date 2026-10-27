from PySide6.QtWidgets import QInputDialog, QMessageBox, QLineEdit

def prompt_phone(parent):
    phone, ok = QInputDialog.getText(
        parent,
        "Telegram Login",
        "Enter your phone number (with country code, e.g. +1234567890):",
        QLineEdit.Normal
    )
    if ok and phone:
        return phone.strip()
    return None

def prompt_code(parent, phone):
    code, ok = QInputDialog.getText(
        parent,
        "Verification Code",
        f"Enter the code sent to {phone}:",
        QLineEdit.Normal
    )
    if ok and code:
        return code.strip()
    return None

def prompt_password(parent):
    password, ok = QInputDialog.getText(
        parent,
        "Two-Step Verification",
        "Enter your 2FA password:",
        QLineEdit.Password
    )
    if ok and password:
        return password
    return None

def show_auth_error(parent, error_msg):
    QMessageBox.critical(parent, "로그인 오류", f"로그인하지 못했습니다:\n{error_msg}")

def show_auth_success(parent):
    QMessageBox.information(parent, "연결 완료", "텔레그램에 로그인했습니다.")
