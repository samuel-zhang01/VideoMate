"""Focused GUI audit checks with isolated generated settings and stub workers.

No operator state, media, dialogs, or installed backend are accessed. The
optimizer stub exercises UI cancellation, not codec performance/qualification.
"""
import os
import tempfile
import threading
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
class GuiAuditTests(unittest.TestCase):
    def setUp(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        self.temporary = tempfile.TemporaryDirectory(prefix="videomate-audit-ui-generated-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = create_root()
        self.addCleanup(self.close_generated_window)
        if self._testMethodName == "test_each_settings_section_is_reachable_at_large_text_scale":
            self.root.tk.call("tk", "scaling", 2 * 96 / 72)
        with patch.object(Application, "check_tools"):
            self.app = Application(self.root, config_path=self.base / "settings.json", prepare_on_start=False)
        self.app.workspace.set(str(self.base / "workspace"))
        self.app.backend_ready = True

    def close_generated_window(self):
        if hasattr(self, "app"):
            self.app.cancel.set()
            if self.app.worker:
                self.app.worker.join(timeout=5)
        for timer in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()

    def selectors(self):
        variables = {str(self.app.video_codec), str(self.app.rate_control), str(self.app.audio_normalization)}
        return [widget for widget, _ in self.app.controls
                if isinstance(widget, self.app.ttk.Combobox) and str(widget.cget("textvariable")) in variables]

    def select_hevc_profile(self):
        self.app.workflow.set("migrate")
        self.app.workflow_changed()
        self.app.preset.set("Migrate · selective HEVC MP4")
        self.app.apply_profile()

    def test_optimizer_stop_reaches_worker_and_restores_idle_ui(self):
        app = self.app
        started = threading.Event()

        def optimize(_bundle, _codec, *, cancel_event):
            started.set()
            if not cancel_event.wait(timeout=5):
                raise AssertionError("Generated worker did not receive Stop")
            raise KeyboardInterrupt()

        with patch("videomate.calibration.optimize_generated", side_effect=optimize), \
                patch("videomate.dependencies.load_bundle", return_value=object()), \
                patch("videomate.execution.processing_session", return_value=nullcontext()), \
                patch("videomate.gui.save_preferences") as save:
            app.optimize_hardware()
            self.assertTrue(started.wait(timeout=3))
            self.assertTrue(app.busy)
            self.assertTrue(app.progress_running)
            self.assertFalse(app.cancel_button.instate(["disabled"]))
            self.assertIn("Stop job is available", app.progress_text.get())
            app.cancel_button.invoke()
            app.worker.join(timeout=5)
            self.assertFalse(app.worker.is_alive())
            app.poll()
            save.assert_not_called()
        self.assertFalse(app.busy)
        self.assertFalse(app.progress_running)
        self.assertTrue(app.cancel_button.instate(["disabled"]))
        self.assertEqual(app.progress_text.get(), "Optimization stopped.")
        self.assertIn("Previous settings were kept", app.status.get())
        self.assertFalse(app.optimize_button.instate(["disabled"]))

    def test_optimizer_terminal_states_and_presets_survive_control_restoration(self):
        from videomate.errors import VideoMateError
        app = self.app
        self.select_hevc_profile()
        record = {"signature": "a" * 64, "expires_at": int(time.time()) + 3600,
                  "routes": [{"id": "hevc_videotoolbox", "fps": 60, "jobs": 1}]}
        for outcome in ("saved", "save_failed", "worker_failed", "cancelled_ready"):
            with self.subTest(outcome=outcome):
                app.hardware_calibration = {}
                worker_failure = VideoMateError("backend_unavailable") if outcome == "worker_failed" else None
                save_failure = VideoMateError("settings_invalid") if outcome == "save_failed" else None
                with patch("videomate.calibration.optimize_generated", return_value=record, side_effect=worker_failure), \
                        patch("videomate.dependencies.load_bundle", return_value=object()), \
                        patch("videomate.execution.processing_session", return_value=nullcontext()), \
                        patch("videomate.gui.save_preferences", side_effect=save_failure) as save:
                    app.optimize_hardware()
                    app.worker.join(timeout=5)
                    self.assertFalse(app.worker.is_alive())
                    if outcome == "cancelled_ready":
                        app.stop_job()
                    app.poll()
                self.assertFalse(app.busy)
                self.assertFalse(app.progress_running)
                self.assertTrue(app.cancel_button.instate(["disabled"]))
                self.assertTrue(all(widget.instate(["disabled"]) for widget in self.selectors()))
                self.assertEqual(app.hardware_calibration, {"hevc": record} if outcome == "saved" else {})
                if outcome == "saved":
                    save.assert_called_once()
                    self.assertEqual(app.progress_text.get(), "Optimization complete.")
                    self.assertEqual(float(app.progress["value"]), 100)
                elif outcome == "save_failed":
                    self.assertIn("Optimization not saved", app.progress_text.get())
                elif outcome == "cancelled_ready":
                    save.assert_not_called()
                    self.assertEqual(app.progress_text.get(), "Optimization stopped.")
                    self.assertIsInstance(app.status.get(), str)
                else:
                    save.assert_not_called()
                    self.assertEqual(app.progress_text.get(), "Optimization failed.")

    def test_selective_preset_locks_then_releases_readonly_selectors(self):
        app = self.app
        self.select_hevc_profile()
        selectors = self.selectors()
        self.assertEqual(len(selectors), 3)
        self.assertTrue(all(widget.instate(["disabled"]) for widget in selectors))
        self.assertEqual(app.video_codec.get(), "hevc")
        app.convert_noncompliant_hevc.set(False)
        self.assertTrue(all(widget.instate(["readonly", "!disabled"]) for widget in selectors))
        app.video_codec.set("h264")
        app.rate_control.set("Target file size")
        self.assertEqual(app.preferences().video_codec, "h264")
        self.assertEqual(app.preferences().rate_control, "target_size")

    def test_job_and_preview_completion_keep_selective_preset_locked(self):
        app = self.app
        self.select_hevc_profile()
        for preview in (False, True):
            with self.subTest(preview=preview):
                app.action_only = preview
                app.operation_pending = True
                for widget, _ in app.controls:
                    widget.configure(state="disabled")
                app.events.put(("done", "Generated job completed."))
                app.poll()
                self.assertFalse(app.busy)
                self.assertTrue(all(widget.instate(["disabled"]) for widget in self.selectors()))
                self.assertFalse(app.optimize_button.instate(["disabled"]))

    def test_invalid_options_reveal_the_actual_field_without_private_text(self):
        app = self.app
        app.workflow.set("inspect")
        app.workflow_changed()
        app.target_size_mib.set("generated-private-marker")
        app.show("setup")
        app.optimize_hardware()
        self.assertIsNone(app.worker)
        self.assertIn("Target output size", app.field_error.get())
        with patch("videomate.gui.save_preferences") as save:
            app.save_settings()
        self.root.update()
        save.assert_not_called()
        self.assertTrue(app.surfaces["recovery"].outer.winfo_ismapped())
        self.assertTrue(app.advanced_frame.winfo_ismapped())
        field = app.field_widgets[str(app.target_size_mib)]
        self.assertTrue(field.winfo_ismapped())
        self.assertIn("Target output size", app.field_error.get())
        self.assertNotIn("generated-private-marker", app.field_error.get())
        app.target_size_mib.set("500")
        app.timeout.set("0")
        app.save_settings()
        self.root.update()
        self.assertTrue(app.surfaces["setup"].outer.winfo_ismapped())
        self.assertTrue(app.settings_forms["performance"].winfo_ismapped())
        self.assertIn("Worker timeout", app.field_error.get())

    def test_settings_save_reset_undo_and_motion(self):
        app = self.app
        app.show("setup")
        app.show_settings_section("display")
        self.root.update()
        self.assertTrue(app.settings_forms["display"].winfo_ismapped())
        self.assertFalse(app.settings_forms["storage"].winfo_ismapped())
        app.reduce_motion.set(True)
        self.assertIn("Unsaved changes", app.settings_state.get())
        app.save_settings()
        from videomate.preferences import load_preferences
        self.assertTrue(load_preferences(self.base / "settings.json").reduce_motion)
        app.begin_progress()
        self.assertTrue(app.progress_running)
        self.assertFalse(any("ttk::progressbar::Autoincrement" in str(self.root.tk.call("after", "info", timer))
                             for timer in self.root.tk.call("after", "info")))
        app.progress_running = False
        app.reset_settings()
        self.assertFalse(app.reduce_motion.get())
        self.assertIn("Unsaved changes", app.settings_state.get())
        app.revert_settings()
        self.assertTrue(app.reduce_motion.get())
        self.assertNotIn("Unsaved changes", app.settings_state.get())
        self.assertTrue(load_preferences(self.base / "settings.json").reduce_motion)

    def test_compact_privacy_and_footer_stay_visible(self):
        app = self.app
        self.assertEqual(str(app.progress.cget("mode")), "determinate")
        self.assertEqual(float(app.progress.cget("value")), 0)
        for size in ("800x600", "640x600"):
            with self.subTest(size=size):
                self.root.geometry(size)
                app.show("queue")
                self.root.update()
                self.assertTrue(app.privacy_hint_label.winfo_ismapped())
                self.assertIn("Automatic exports off", app.privacy_hint.get())
                self.assertTrue(app.cancel_button.winfo_ismapped())
                self.assertLessEqual(app.cancel_button.winfo_rooty() + app.cancel_button.winfo_height(),
                                     self.root.winfo_rooty() + self.root.winfo_height())
                self.assertLessEqual(app.run_workflow_button.winfo_rootx() + app.run_workflow_button.winfo_width(),
                                     self.root.winfo_rootx() + self.root.winfo_width())

    def test_each_settings_section_is_reachable_at_large_text_scale(self):
        from types import SimpleNamespace
        app = self.app
        self.root.geometry("800x600")
        app.show("setup")
        for section in app.settings_forms:
            with self.subTest(section=section):
                app.show_settings_section(section)
                self.root.update()
                surface = app.surfaces["setup"]
                for control, _ in app.controls:
                    if not surface.contains(control) or not control.winfo_ismapped():
                        continue
                    surface.reveal(SimpleNamespace(widget=control))
                    self.root.update()
                    x = control.winfo_rootx() - surface.canvas.winfo_rootx()
                    y = control.winfo_rooty() - surface.canvas.winfo_rooty()
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, -1)
                    self.assertLessEqual(x + control.winfo_width(), surface.canvas.winfo_width())
                    self.assertLessEqual(y + control.winfo_height(), surface.canvas.winfo_height() + 1)
