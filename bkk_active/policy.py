"""App-defined available slots and court ranking near 18:00."""
import re
from .config import PACKAGE, TIME_RANGE
from .ui import bounds, ui_labels


def available_slot(root, start_minute=18 * 60, end_minute=21 * 60, exact_interval=None):
    """อ่านสถานะในแถวเดียวกับเวลา ไม่ตีความ 'ไม่ว่าง' ว่าเป็น 'ว่าง'."""
    choices = []
    for node in root.iter("node"):
        rect = bounds(node)
        if node.get("package") != PACKAGE or not rect:
            continue
        labels = ui_labels(node)
        tokens = [part.strip() for label in labels for part in re.split(r"[,\n]", label)]
        free = any(re.search(r"(?:^|[\s,])ว่าง(?:$|[\s,])", token) for token in tokens)
        if not free or any("ไม่ว่าง" in token for token in tokens):
            continue
        ranges = {tuple(map(int, match.groups())) for label in labels
                  for match in TIME_RANGE.finditer(label)}
        if len(ranges) != 1:
            continue
        h1, m1, h2, m2 = next(iter(ranges))
        begin, end = h1 * 60 + m1, h2 * 60 + m2
        if not (0 <= h1 < 24 and 0 <= h2 <= 24 and m1 < 60 and m2 < 60
                and start_minute <= begin < end <= end_minute):
            continue
        area = (rect[2] - rect[0]) * (rect[3] - rect[1])
        choices.append((begin, area, node, f"{h1:02d}:{m1:02d}–{h2:02d}:{m2:02d}"))
    # ใช้แถวที่เล็กที่สุด ไม่ใช้ container ครอบหน้ามากดแทนแถวที่ disabled
    choices = [choice for choice in choices
               if not any(other[2] is not choice[2] and other[2] in tuple(choice[2].iter())
                          for other in choices)
               and choice[2].get("enabled") != "false"]
    if exact_interval is not None:
        choices = [choice for choice in choices if choice[3] == exact_interval]
    if not choices:
        return None
    _, _, node, label = min(choices, key=lambda choice: (choice[0], choice[1]))
    return node, label


def ranked_courts(choices):
    """เรียงเวลาเริ่มใกล้ 18:00 ที่สุดก่อน แล้วใช้หมายเลขสนามตัดสินเมื่อเวลาเท่ากัน."""
    return sorted(choices, key=lambda choice: (int(choice[1][:2]) * 60 + int(choice[1][3:5]), choice[0]))
