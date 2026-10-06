"""Portable controller regressions using generated state and no Tk/runtime I/O.

These exercise real Application methods through a small widget port. Native
geometry, painting, accessibility and toolkit behavior require separate checks.
"""
import queue
import threading
import unittest
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from videomate.errors import VideoMateError
from videomate.gui import Application
from videomate.preferences import Preferences


class GeneratedTclError(Exception):
    pass


class Variable:
    def __init__(self, name, value):
        self.name, self.value = name, value

    def __str__(self):
        return self.name

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self, **options):
        self.options = {"state": "normal", **options}
        self.animated = False

    def cget(self, name):
        if name not in self.options:
            raise GeneratedTclError()
        return self.options[name]

    def configure(self, **options):
        self.options.update(options)

    def start(self, _interval):
        self.animated = True

    def stop(self):
        self.animated = False
        # Tk may reset a progressbar value when stopping animation.
        self.options["value"] = 0

    def pack(self, **_options):
        self.options["packed"] = True

    def focus_set(self):
        self.options["focused"] = True


def controller():
    """Build only generated UI state; never call Application.__init__."""
    app = Application.__new__(Application)
    app.tk = SimpleNamespace(TclError=GeneratedTclError)
    app.root = SimpleNamespace(after=lambda *_: "generated-timer")
    app.events, app.cancel = queue.Queue(), threading.Event()
    app.worker = app.setup_worker = None
    app.operation_pending = app.closing = app._tools_recheck_pending = False
    app.progress_state = None
    app.progress_running = app.action_only = False
    app.active_operation = None
    app.hardware_calibration = {}
    app.applied_profile = app.profile_baseline = None
    values = {"convert_noncompliant_hevc": False, "convert_all_mp4": False,
              "strategy": "auto", "profile": "compatible_sdr", "video_codec": "h264",
              "audio_normalization": "Off — leave audio level unchanged",
              "rate_control": "Auto — estimate from source", "policy_text": "",
              "profile_status": "", "progress_text": "", "status": "",
              "conversion_hint": "", "settings_state": "",
              "reduce_motion": False, "sensitive": True, "workflow": "migrate"}
    for name, value in values.items():
        setattr(app, name, Variable("generated-" + name, value))
    app.progress = Widget(mode="indeterminate", value=0, maximum=100)
    app.cancel_button = Widget(state="disabled")
    app.log_option, app.layout_option, app.mapping_option = Widget(), Widget(), Widget()
    app.controls = []
    for name in ("strategy", "profile", "video_codec", "audio_normalization", "rate_control"):
        # This reflects the actual toolkit API distinction, not app internals.
        binding = "variable" if name in {"strategy", "profile"} else "textvariable"
        normal = "normal" if binding == "variable" else "readonly"
        app.controls.append((Widget(**{binding: str(getattr(app, name)), "state": normal}), normal))
    app.optimize_button = Widget()
    app.controls.append((app.optimize_button, "normal"))
    app.privacy_changed = app.workflow_changed = app.refresh_calibration_status = lambda: None
    app.settings_snapshot = lambda: ("generated-settings-snapshot",)
    app.append = lambda _: None
    app.preferences = lambda: Preferences(
        workflow=app.workflow.get(), profile=app.profile.get(), strategy=app.strategy.get(),
        video_codec=app.video_codec.get(), convert_all_mp4=app.convert_all_mp4.get(),
        convert_noncompliant_hevc=app.convert_noncompliant_hevc.get(),
        audio_normalization=app.LOUDNESS_LABELS[app.audio_normalization.get()],
        rate_control=app.RATE_LABELS[app.rate_control.get()],
        hardware_calibration=app.hardware_calibration).validate()
    return app


def ranking(codec="h264", speed=60):
    return {"signature": "a" * 64, "expires_at": 4102444800,
            "routes": [{"id": codec + "_videotoolbox", "fps": speed, "jobs": 1}]}


def settings_controller():
    app = controller()
    del app.settings_snapshot  # Use the real snapshot and undo implementation.
    defaults = Preferences()
    aliases = {"allow_shorter": "shorter", "allow_track_loss": "drop_tracks", "dependencies": "dependency_path"}
    for field in fields(defaults):
        name = aliases.get(field.name, field.name)
        if field.type is dict or hasattr(app, name):
            continue
        value = getattr(defaults, field.name)
        setattr(app, name, Variable("generated-" + name, str(value) if field.type is int else value))
    app.config_file = Variable("generated-config", "/generated/settings.json")
    app.custom_output = Variable("generated-output-override", False)
    app.preset = Variable("generated-preset", "Choose a profile (optional)")
    app.field_error = Variable("generated-field-error", "")
    return app


class ControllerTests(unittest.TestCase):
    def test_queued_worker_status_cannot_erase_pending_stop_acknowledgement(self):
        app = controller()
        app.operation_pending = True
        app.cancel_button.configure(state="normal")
        app.events.put(("message", "Inspecting input 3"))
        app.stop_job()
        stopping = app.status.get()
        app.poll()
        self.assertTrue(app.busy)
        self.assertTrue(app.cancel.is_set())
        self.assertEqual(app.cancel_button.cget("state"), "disabled")
        self.assertEqual(app.status.get(), stopping)

    def test_stop_wins_over_already_queued_calibration_success(self):
        app = controller()
        original = {"h264": ranking(speed=30)}
        app.hardware_calibration = original
        app.operation_pending = app.progress_running = True
        app.progress.start(30)
        app.cancel_button.configure(state="normal")
        app.events.put(("calibration_ready", ("h264", ranking(), Path("/generated/settings.json"))))
        # The worker finished, but Stop happened before Tk consumed its result.
        app.stop_job()
        with patch("videomate.gui.save_preferences") as save:
            app.poll()
        save.assert_not_called()
        self.assertEqual(app.hardware_calibration, original)
        self.assertFalse(app.busy)
        self.assertFalse(app.progress_running)
        self.assertFalse(app.progress.animated)
        self.assertEqual(app.cancel_button.cget("state"), "disabled")
        self.assertEqual(app.progress_text.get(), "Optimization stopped.")
        self.assertIsInstance(app.status.get(), str)
        self.assertNotIn("generated/settings", app.status.get())
        self.assertNotIn("saved locally", app.status.get())

    def test_reduced_motion_has_static_progress_but_keeps_processing_state(self):
        app = controller()
        app.reduce_motion.set(True)
        app.begin_progress()
        self.assertTrue(app.progress_running)
        self.assertFalse(app.progress.animated)
        self.assertTrue(app.progress_text.get())
        app.reduce_motion.set(False)
        app.apply_motion_preference()
        self.assertTrue(app.progress.animated)
        app.reduce_motion.set(True)
        app.apply_motion_preference()
        self.assertFalse(app.progress.animated)
        self.assertTrue(app.progress_running)

    def test_selective_preset_locks_selectors_then_restores_editability(self):
        app = controller()
        app.convert_noncompliant_hevc.set(True)
        app.refresh_policy()
        self.assertEqual(app.video_codec.get(), "hevc")
        self.assertEqual(app.audio_normalization.get(), "Playback — target -16 LUFS")
        self.assertTrue(all(widget.cget("state") == "disabled" for widget, _ in app.controls[:5]))
        app.convert_noncompliant_hevc.set(False)
        app.refresh_policy()
        self.assertEqual([widget.cget("state") for widget, _ in app.controls[:5]],
                         ["normal", "normal", "readonly", "readonly", "readonly"])
        app.video_codec.set("h264")
        app.refresh_policy()
        self.assertEqual(app.preferences().video_codec, "h264")

    def test_every_completion_restores_idle_controls_without_unlocking_preset(self):
        for completion in ("job", "preview", "optimizer", "optimizer_error", "save_failure"):
            with self.subTest(completion=completion):
                app = controller()
                app.convert_noncompliant_hevc.set(True)
                app.refresh_policy()
                app.operation_pending = True
                app.action_only = completion == "preview"
                for widget, _ in app.controls:
                    widget.configure(state="disabled")
                if completion in {"job", "preview"}:
                    event = ("done", "Generated job complete.")
                elif completion == "optimizer_error":
                    event = ("calibration_error", "Generated optimization failed.")
                else:
                    event = ("calibration_ready", ("hevc", ranking("hevc"), Path("/generated/settings.json")))
                app.events.put(event)
                failure = VideoMateError("settings_invalid") if completion == "save_failure" else None
                with patch("videomate.gui.save_preferences", side_effect=failure):
                    app.poll()
                self.assertFalse(app.busy)
                self.assertEqual(app.optimize_button.cget("state"), "normal")
                self.assertTrue(all(widget.cget("state") == "disabled" for widget, _ in app.controls[:5]))
                self.assertEqual(app.cancel_button.cget("state"), "disabled")
                if completion == "job":
                    self.assertEqual(app.progress.cget("mode"), "determinate")
                    self.assertEqual(app.progress.cget("value"), 0)
                if completion == "optimizer":
                    self.assertEqual(app.progress.cget("value"), 100)
                    self.assertEqual(app.progress_text.get(), "Optimization complete.")
                if completion == "save_failure":
                    self.assertEqual(app.hardware_calibration, {})
                    self.assertIn("Previous settings were kept", app.progress_text.get())

    def test_undo_restores_calibration_and_edits_without_touching_selection_or_profiles(self):
        app = settings_controller()
        app.inputs = ["generated-selection"]
        app.custom_profiles = {"Generated profile": {"workflow": "inspect"}}
        app.hardware_calibration = {"h264": ranking()}
        app._saved_settings = app.settings_snapshot()
        app.hardware_calibration.clear()
        app.workspace.set("/generated/unsaved-workspace")
        app.update_settings_state()
        self.assertIn("Unsaved changes", app.settings_state.get())
        app.revert_settings()
        self.assertEqual(app.workspace.get(), "")
        self.assertEqual(app.hardware_calibration, {"h264": ranking()})
        self.assertEqual(app.inputs, ["generated-selection"])
        self.assertEqual(app.custom_profiles, {"Generated profile": {"workflow": "inspect"}})
        self.assertNotIn("Unsaved changes", app.settings_state.get())

    def test_invalid_advanced_value_reveals_options_instead_of_unrelated_settings(self):
        app = settings_controller()
        app.workflow.set("inspect")
        app.target_size_mib.set("generated-secret-value")
        app.advanced = Variable("generated-advanced", False)
        app.advanced_frame = Widget()
        target = Widget()
        shown, revealed = [], []
        app.field_widgets = {str(app.target_size_mib): target}
        app.settings_forms = {}
        app.surfaces = {"recovery": SimpleNamespace(contains=lambda widget: widget is target,
                                                    reveal=lambda event: revealed.append(event.widget))}
        app.show = shown.append
        app.root.after_idle = lambda callback: callback()
        app.report_settings_error(VideoMateError("settings_invalid"))
        self.assertEqual(shown, ["recovery"])
        self.assertEqual(revealed, [target])
        self.assertTrue(app.advanced.get())
        self.assertTrue(app.advanced_frame.cget("packed"))
        self.assertTrue(target.cget("focused"))
        self.assertNotIn("generated-secret", app.field_error.get())
        self.assertIn("Target output size", app.status.get())
