"""Generated-value correction checks; no paths are opened or inspected."""
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from videomate.errors import VideoMateError
from videomate.gui_validation import correction
from videomate.preferences import INTEGER_BOUNDS, Preferences


def values():
    result = asdict(Preferences())
    for name in INTEGER_BOUNDS:
        result[name] = str(result[name])
    result["config_file"] = ""
    return result


class CorrectionTests(unittest.TestCase):
    def test_defaults_and_every_numeric_boundary_remain_usable(self):
        self.assertIsNone(correction(values()))
        for name, (low, high) in INTEGER_BOUNDS.items():
            for value in (low, high):
                with self.subTest(field=name, boundary=value):
                    candidate = values()
                    candidate[name] = str(value)
                    self.assertIsNone(correction(candidate))
                    replace(Preferences(), **{name: value}).validate()
            for value in (low - 1, high + 1):
                with self.subTest(field=name, outside=value):
                    candidate = values()
                    candidate[name] = str(value)
                    self.assertEqual(correction(candidate)[0], name)
                    with self.assertRaises(VideoMateError):
                        replace(Preferences(), **{name: value}).validate()

    def test_invalid_numeric_text_produces_fixed_correction_without_echo(self):
        for raw in ("", "1.5", "NaN", "Infinity", True, "generated-secret-do-not-echo", "9" * 5000):
            with self.subTest(kind=type(raw).__name__, length=len(str(raw))):
                candidate = values()
                candidate["target_size_mib"] = raw
                field, message = correction(candidate)
                self.assertEqual(field, "target_size_mib")
                self.assertEqual(message, "Target output size: enter a whole number from 1 to 1,048,576.")

    def test_path_guidance_does_not_reveal_values_or_access_storage(self):
        # Host-native absolute syntax only; constructing Path never opens it.
        absolute = str(Path("generated-safe-location").absolute())
        names = ("workspace", "recovered_dir", "diagnostics_dir", "logs_dir", "dependencies", "config_file")
        for name in names:
            for raw in ("generated-private-relative", absolute + "\0generated-private",
                        absolute + "/" + "generated-private" * 300):
                with self.subTest(field=name, length=len(raw)):
                    candidate = values()
                    candidate[name] = raw
                    field, message = correction(candidate)
                    self.assertEqual(field, name)
                    self.assertNotIn("generated-private", message)
                    self.assertNotIn(raw, message)
                    self.assertLess(len(message), 160)
            for raw in ("", absolute):
                candidate = values()
                candidate[name] = raw
                self.assertIsNone(correction(candidate))

    def test_incompatible_hevc_choice_routes_to_the_codec_control(self):
        candidate = values()
        candidate["video_codec"] = "hevc"
        field, message = correction(candidate)
        self.assertEqual(field, "video_codec")
        self.assertIn("Choose MP4", message)
        candidate["profile"] = "compatible_sdr"
        self.assertIsNone(correction(candidate))

    def test_multiple_errors_select_a_correction_without_dumping_the_form(self):
        candidate = values()
        candidate.update(timeout="generated-secret-timeout", target_size_mib="generated-secret-size",
                         workspace="generated-secret-path")
        field, message = correction(candidate)
        self.assertEqual(field, "timeout")
        self.assertNotIn("generated-secret", message)
        self.assertIn("Worker timeout", message)
