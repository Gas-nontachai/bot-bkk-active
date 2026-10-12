"""Find the orange submit button from RGBA screenshots."""
import struct


def orange_submit_center(raw):
    """หาปุ่มส้มกว้างด้านล่างจาก Android screencap RGBA โดยไม่ใช้ชื่อปุ่ม."""
    if len(raw) < 16:
        raise RuntimeError("ภาพหน้าจอไม่สมบูรณ์")
    width, height, pixel_format = struct.unpack_from("<3I", raw)
    offset = len(raw) - width * height * 4
    if pixel_format != 1 or offset not in (12, 16) or width == 0 or height == 0:
        raise RuntimeError("รูปแบบภาพหน้าจอไม่รองรับ ต้องเป็น Android RGBA_8888")
    step = max(1, width // 180)
    columns, rows = (width + step - 1) // step, (height + step - 1) // step
    orange = set()
    for gy in range(rows * 55 // 100, rows):
        for gx in range(columns):
            pos = offset + ((gy * step) * width + gx * step) * 4
            red, green, blue = raw[pos:pos + 3]
            if red >= 185 and 40 <= green <= 190 and blue < 100 and red > green * 1.35:
                orange.add((gx, gy))
    candidates = []
    while orange:
        seed = orange.pop()
        stack, component = [seed], [seed]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in orange:
                    orange.remove(neighbor)
                    component.append(neighbor)
                    stack.append(neighbor)
        x1 = min(point[0] for point in component) * step
        x2 = min(width, (max(point[0] for point in component) + 1) * step)
        y1 = min(point[1] for point in component) * step
        y2 = min(height, (max(point[1] for point in component) + 1) * step)
        fill = len(component) * step * step / ((x2 - x1) * (y2 - y1))
        if (x2 - x1 >= width * 0.5 and height * 0.02 <= y2 - y1 <= height * 0.13
                and fill >= 0.55 and y2 <= height * 0.98):
            candidates.append(((x1 + x2) // 2, (y1 + y2) // 2))
    if len(candidates) != 1:
        raise RuntimeError(f"หาปุ่ม Submit สีส้มที่ชัดเจนไม่ได้: พบ {len(candidates)} ปุ่ม")
    return candidates[0]
