"""Manual trigger for the daily invoice processing cycle.

Usage:
    python -m scripts.run_daily_sync
"""

from src.main import run_daily_cycle

if __name__ == "__main__":
    run_daily_cycle()
