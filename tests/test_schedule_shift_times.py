import unittest

from modules.schedule.config import SHIFT_TIMES
from modules.schedule.handlers import shift_time_keyboard


class ScheduleShiftTimesTests(unittest.TestCase):
    def test_schedule_offers_only_full_and_half_shift_start_times(self):
        self.assertEqual(SHIFT_TIMES, ["10:00", "15:00"])

        callbacks = [
            button.callback_data
            for row in shift_time_keyboard("01.08.2026").inline_keyboard
            for button in row
            if button.callback_data.startswith("schtime:")
        ]

        self.assertEqual(
            callbacks,
            [
                "schtime:01.08.2026:1000",
                "schtime:01.08.2026:1500",
            ],
        )


if __name__ == "__main__":
    unittest.main()
