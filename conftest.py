import pathlib
import sys

# Make `hallucheck` and `adapters` importable as top-level packages without an
# editable install (so the suite runs from a fresh checkout).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
