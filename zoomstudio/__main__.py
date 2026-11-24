"""Entry point: `uv run python -m zoomstudio`."""
import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication(sys.argv)
    app.setApplicationName("Zoom Studio")
    label = QLabel("Zoom Studio — work in progress")
    label.resize(480, 120)
    label.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
