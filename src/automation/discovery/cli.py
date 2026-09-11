"""Compatibility entry point; share the maintained discovery CLI."""
import sys
from automation.cli import main as automation_main


def main() -> None:
    sys.argv.insert(1, "discover")
    automation_main()


if __name__ == "__main__":
    main()
