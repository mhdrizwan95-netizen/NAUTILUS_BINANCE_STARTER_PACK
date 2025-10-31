
import argparse
from loguru import logger
from .config import settings
from .engine import run

def main():
    parser = argparse.ArgumentParser(description="Backtest runner (autonomous)")
    parser.add_argument("cmd", choices=["run"], help="run backtest loop")
    args = parser.parse_args()
    logger.remove()
    logger.add(lambda msg: print(msg, end=""))
    if args.cmd == "run":
        run()

if __name__ == "__main__":
    main()
