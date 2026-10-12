#!/usr/bin/env python3
"""Run the BKK Active booking automation."""
import subprocess
import sys
import xml.etree.ElementTree as ET

from bkk_active.cli import main
from bkk_active.logging_setup import LOGGER, configure_logging


if __name__ == "__main__":
    configure_logging()
    try:
        main()
    except (RuntimeError, subprocess.TimeoutExpired, ET.ParseError) as error:
        LOGGER.error("ผิดพลาด: %s", error)
        sys.exit(1)
