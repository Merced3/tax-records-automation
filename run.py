"""Stable project entry point: python run.py <command>."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from financial_automation.cli import main

if __name__ == "__main__":
    main(repo_root=ROOT)
