"""Entry point for the trading system.

Usage:
    python -m trading
"""

import asyncio

from trading.app import main

if __name__ == "__main__":
    asyncio.run(main())
