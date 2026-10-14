"""Select the first app-defined available slot in UI order."""
import re
from .config import PACKAGE, TIME_RANGE
from .ui import bounds, ui_labels


def time_window(config):
    return getattr(config, "start_minute", 0), getattr(config, "end_minute", 24 * 60)


def time_window_label(config):
    begin, end = time_window(config)
    if (begin, end) == (0, 24 * 60):
        return "ทุกช่วงเวลา"
    return f"{begin // 60:02d}:{begin % 60:02d}–{end // 60:02d}:{end % 60:02d}"


def available_slot(root, start_minute=0, end_minute=24 * 60, exact_interval=None):
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
    _, _, node, label = choices[0]
    return node, label
