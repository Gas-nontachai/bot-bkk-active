"""App constants, project paths, and command-line configuration."""
import re
from pathlib import Path

PACKAGE = 'go.th.bangkok.cstd'
ACTIVITY = f'{PACKAGE}/com.mfessplayground.cstd.MainActivity'
THAI_MONTHS = ('มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน', 'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม')
TIME_RANGE = re.compile('(?<!\\d)(\\d{1,2}):(\\d{2})\\s*[-–—]\\s*(\\d{1,2}):(\\d{2})(?!\\d)')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
