from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from bkk_active.config import PACKAGE
from bkk_active.flows.payment import defer_payment
from bkk_active.flows.submit import select_slot
from bkk_active.ui import confirmation_matches, is_payment_page, payment_later_button


def node(**attributes):
    return ET.Element("node", {"package": PACKAGE, "enabled": "true",
                              "bounds": "[10,10][900,1900]", **attributes})


def payment_page():
    root = node(clickable="true")
    for text in ("ชำระเงิน", "14/10/2569", "18:20 น.", "สนามแบดมินตัน 6", "รอการชำระ"):
        root.append(node(text=text))
    root.append(node(text="ชำระเงิน", clickable="true", bounds="[50,1600][850,1750]"))
    later = node(clickable="true", bounds="[250,1800][650,1880]")
    later.append(node(text="ชำระภายหลัง"))
    root.append(later)
    return root, later


class PaymentTests(unittest.TestCase):
    def test_success_receipt_finishes_once_before_review(self):
        root = node()
        for text in ("ยืนยันการจอง", "ศูนย์กีฬาเบญจกิติ", "สำเร็จ", "21/10/2569",
                     "07:00 น.", "สนามแบดมินตัน แบดมินตัน สนาม 1", "หมายเลขการจอง", "123456"):
            root.append(node(text=text))
        done = node(clickable="true", bounds="[53,2131][1028,2275]")
        done.append(node(text="เสร็จสิ้น"))
        root.append(done)
        review = node(text="Booking Review")
        for target in (date(2026, 10, 21), date(2026, 10, 20)):
            with self.subTest(target=target), \
                    patch("bkk_active.flows.submit.orange_submit_center", return_value=(400, 1700)), \
                    patch("bkk_active.flows.submit.submit_review") as submit_review:
                device = Mock()
                device.read_ui.return_value = root
                device.wait_for.side_effect = [node(), review]
                slot = node()
                config = SimpleNamespace(date=target)
                if target.day == 21:
                    select_slot(device, config, 1, (slot, "07:00–08:00"))
                    self.assertEqual([c.args[0] for c in device.tap.call_args_list], [slot, done])
                    submit_review.assert_called_once_with(device, config, review)
                else:
                    with self.assertRaisesRegex(RuntimeError, "ไม่ตรง"):
                        select_slot(device, config, 1, (slot, "07:00–08:00"))
                    device.tap.assert_called_once_with(slot)
                    submit_review.assert_not_called()
                device.run.assert_called_once_with("shell", "input", "tap", "400", "1700")

    def test_selects_pay_later_not_pay_now_or_full_page_container(self):
        root, later = payment_page()
        self.assertTrue(is_payment_page(root))
        self.assertIs(payment_later_button(root), later)
        self.assertFalse(confirmation_matches(root, date(2026, 10, 14), 6, "18:20–19:30"))

    def test_disabled_pay_later_is_not_selected(self):
        root, later = payment_page()
        later.set("enabled", "false")
        self.assertIsNone(payment_later_button(root))

    def test_payment_is_deferred_once_and_review_page_returned(self):
        root, later = payment_page()
        review = node(text="Booking Review")
        device = Mock()
        device.wait_for.side_effect = [root, review]
        config = SimpleNamespace(date=date(2026, 10, 14))
        self.assertIs(defer_payment(device, config, root, 6, "18:20–19:30"), review)
        device.tap.assert_called_once_with(later)

    def test_mismatched_booking_details_stop_before_payment_button(self):
        root, _ = payment_page()
        for day, court, interval in ((date(2026, 10, 13), 6, "18:20–19:30"),
                                      (date(2026, 10, 14), 1, "18:20–19:30"),
                                      (date(2026, 10, 14), 6, "19:00–20:00")):
            device = Mock()
            device.wait_for.return_value = root
            with self.assertRaises(RuntimeError):
                defer_payment(device, SimpleNamespace(date=day), root, court, interval)
            device.tap.assert_not_called()

    def test_submit_routes_payment_before_review_and_never_resubmits(self):
        root, _ = payment_page()
        review = node(text="Booking Review")
        device = Mock()
        device.read_ui.return_value = root
        config = SimpleNamespace(date=date(2026, 10, 14))
        order = []
        with patch("bkk_active.flows.submit.orange_submit_center", return_value=(400, 1700)), \
                patch("bkk_active.flows.submit.defer_payment") as payment, \
                patch("bkk_active.flows.submit.submit_review") as submit_review:
            payment.side_effect = lambda *args: order.append("pay-later") or review
            submit_review.side_effect = lambda *args: order.append("review")
            select_slot(device, config, 6, (node(), "18:20–19:30"))
        self.assertEqual(order, ["pay-later", "review"])
        device.run.assert_called_once_with("shell", "input", "tap", "400", "1700")
        submit_review.assert_called_once_with(device, config, review)


if __name__ == "__main__":
    unittest.main()
