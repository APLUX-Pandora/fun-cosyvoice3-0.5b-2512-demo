#!/usr/bin/env python3
"""Create a reusable prepared voice; no synthesis model is loaded."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1]/"demo/clone.py"),run_name="__main__")
