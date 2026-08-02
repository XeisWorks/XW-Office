"""XeisWorks Office application entry point."""
import sys


def main() -> None:
    from xw_office.app import create_application
    app = create_application()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
