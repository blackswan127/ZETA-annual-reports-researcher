import sys
from pathlib import Path

# Add markets/Philippines/src and repo root to sys.path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parents[3]))
