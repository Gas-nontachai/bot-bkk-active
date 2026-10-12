"""Choose pay-later on the payment page, then wait for Booking Review."""
from ..logging_setup import LOGGER
from ..middleware import flow_step
from ..ui import booking_details_match, is_payment_page, is_review_page, payment_later_button


@flow_step("pay-later")
def defer_payment(device, config, root, number, interval):
    root = device.wait_for(lambda ui: is_payment_page(ui) and payment_later_button(ui) is not None,
                           "ไม่พบปุ่มชำระภายหลังที่พร้อมกด", initial=root)
    if not booking_details_match(root, config.date, number, interval):
        raise RuntimeError("วัน สนาม หรือเวลาในหน้าชำระเงินไม่ตรงกับการจอง จึงไม่ได้กดชำระภายหลัง")
    button = payment_later_button(root)
    LOGGER.info("พบหน้าชำระเงิน: กด ชำระภายหลัง")
    device.tap(button)
    return device.wait_for(is_review_page,
                           "กดชำระภายหลังแล้ว แต่ยังไม่พบหน้า Booking Review จึงไม่กดซ้ำ")
