"""Viewport tests use empty, isolated GUI instances; no operator settings/media."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class GeometryTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
    def test_changed_tools_path_waits_for_its_own_check(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        with tempfile.TemporaryDirectory(prefix="videomate-tools-ui-generated-") as temporary:
            root = create_root()
            first_started, release_first = threading.Event(), threading.Event()
            old = Path(temporary).resolve() / "generated-old-tools"
            new = Path(temporary).resolve() / "generated-new-tools"
            checks = []
            def check(path):
                checks.append(path)
                if path == old:
                    first_started.set()
                    release_first.wait(timeout=5)
                return {"version": "generated"}
            try:
                with patch.object(Application, "check_tools"):
                    app = Application(root, config_path=Path(temporary).resolve() / "settings.json", prepare_on_start=False)
                with patch("videomate.gui.check_backend", side_effect=check):
                    app.dependency_path.set(str(old))
                    app.check_tools()
                    self.assertTrue(first_started.wait(timeout=3))
                    app.dependency_path.set(str(new))
                    app.check_tools()
                    self.assertFalse(app.backend_ready)
                    release_first.set()
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline and (checks != [old, new] or not app.backend_ready):
                        root.update()
                        time.sleep(0.01)
                    self.assertEqual(checks, [old, new])
                    self.assertTrue(app.backend_ready)
                    self.assertEqual(app.dependencies, new)
            finally:
                release_first.set()
                for after in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", after)
                root.destroy()

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
    def test_stopped_migration_offers_direct_continue_and_private_resume(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        from videomate.migration_resume import SESSION_RETRIES
        with tempfile.TemporaryDirectory(prefix="videomate-continue-ui-generated-") as temporary:
            root = create_root()
            identifier = "a" * 32
            try:
                with patch.object(Application, "check_tools"):
                    app = Application(root, config_path=Path(temporary) / "settings.json", prepare_on_start=False)
                app.backend_ready = True
                app.workflow.set("migrate")
                SESSION_RETRIES[identifier] = {"mode": "continue"}
                app.job.set(identifier)
                app.workflow_changed()
                root.update()
                self.assertTrue(app.new_migration_button.winfo_ismapped())
                self.assertEqual(app.retry_button.cget("text"), "Continue stopped migration")
                self.assertEqual(app.run_workflow_button.cget("text"), "Continue stopped migration")
                self.assertIn("No passphrase is needed", app.resume_guidance.get())
                self.assertEqual(str(app.retry_preview_button.cget("state")), "disabled")
                self.assertEqual(str(app.resume_migration_button.cget("state")), "disabled")
                with patch.object(app, "start") as start:
                    app.run_workflow_button.invoke()
                start.assert_called_once_with("continue_migration")
                with patch.object(app, 'start') as start_different:
                    app.new_migration_button.invoke()
                start_different.assert_called_once_with('run_workflow')
                SESSION_RETRIES[identifier] = {"mode": "retry"}
                app.workflow_changed()
                root.update()
                self.assertFalse(app.new_migration_button.winfo_ismapped())
                self.assertEqual(str(app.retry_preview_button.cget("state")), "normal")
                self.assertEqual(app.run_workflow_button.cget("text"), "Start new migration")
                self.assertIn("Preview unresolved retry", app.resume_guidance.get())
                SESSION_RETRIES.pop(identifier)
                app.workflow_changed()
                self.assertIn("private checkpoint was enabled before this job", app.resume_guidance.get())
                self.assertEqual(str(app.retry_preview_button.cget("state")), "disabled")
                self.assertEqual(str(app.resume_migration_button.cget("state")), "normal")
            finally:
                SESSION_RETRIES.pop(identifier, None)
                for after in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", after)
                root.destroy()

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
    def test_selective_hevc_profile_is_visible_and_keeps_privacy_setting(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        with tempfile.TemporaryDirectory(prefix="videomate-hevc-ui-generated-") as temporary:
            root = create_root()
            try:
                with patch.object(Application, "check_tools"):
                    app = Application(root, config_path=Path(temporary).resolve() / "settings.json", prepare_on_start=False)
                app.workflow.set("migrate")
                app.workflow_changed()
                self.assertIn("Migrate · selective HEVC MP4", app.preset_choice.cget("values"))
                app.preset.set("Migrate · selective HEVC MP4")
                app.apply_profile()
                p = app.preferences()
                self.assertTrue(p.sensitive)
                self.assertTrue(p.convert_noncompliant_hevc)
                self.assertTrue(p.partial_salvage)
                self.assertEqual((p.profile, p.video_codec, p.audio_normalization, p.rate_control),
                                 ("compatible_sdr", "hevc", "playback", "auto"))
                self.assertIn("copy healthy", app.policy_text.get().lower())
            finally:
                for after in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", after)
                root.destroy()

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
    def test_prepare_defaults_early_overlap_and_migration_progress(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        from videomate.preferences import load_preferences
        from videomate.progress import Progress
        import time
        with tempfile.TemporaryDirectory(prefix="videomate-progress-ui-generated-") as temporary:
            base = Path(temporary).resolve()
            root = create_root()
            try:
                with patch.object(Application, "check_tools"):
                    app = Application(root, config_path=base / "settings.json", prepare_on_start=False)
                app.workspace.set(str(base / "workspace"))
                app.config_file.set("")
                with patch("videomate.gui.default_config_path", return_value=base / "config" / "settings.json"):
                    self.assertTrue(app.initialize())
                config = base / "config" / "settings.json"
                self.assertEqual(app.config_file.get(), str(config))
                config.unlink()
                app.logs_dir.set(str(base / "chosen-logs"))
                self.assertTrue(app.initialize())
                self.assertEqual(load_preferences(config).logs_dir, str(base / "chosen-logs"))
                self.assertIn("verified", app.storage_health.get())
                source = base / "invented-source"
                source.mkdir()
                app.workflow.set("migrate")
                app.add_input(str(source), "Folder")
                app.recovered_dir.set(str(source / "nested-output"))
                app.backend_ready = True
                with patch("videomate.gui.prepare_application") as prepare, patch("tkinter.messagebox.askyesno") as consent:
                    app.start("run_workflow")
                    prepare.assert_not_called()
                    consent.assert_not_called()
                    self.assertIn("MIG-OUTPUT", app.status.get())
                    self.assertFalse(app.initialize())
                    prepare.assert_not_called()
                self.assertFalse((source / "nested-output").exists())
                self.assertIsNone(app.worker)
                app.recovered_dir.set("")
                app.custom_output.set(False)
                app.workflow_changed()
                app.output_override_changed()
                root.update()
                self.assertTrue(app.destination_controls.winfo_ismapped())
                app.sensitive.set(False)
                app.privacy_changed()
                self.assertIn("automatically", app.migration_name_hint.get())
                self.assertEqual(str(app.migration_names_option.cget("state")), "disabled")
                self.assertEqual(str(app.layout_option.cget("state")), "disabled")
                app.use_size_defaults()
                self.assertEqual(app.preferences().rate_control, "source_size")
                self.assertEqual(app.preferences().max_output_mib, 0)
                self.assertEqual(app.preferences().max_source_percent, 0)
                app.audio_normalization.set("Playback — target -16 LUFS")
                app.audio_bitrate_kbps.set("96")
                app.software_preset.set("fast")
                app.mp4_faststart.set(False)
                self.assertEqual(app.preferences().audio_normalization, "playback")
                self.assertEqual(app.preferences().audio_bitrate_kbps, 96)
                self.assertFalse(app.preferences().mp4_faststart)
                app.migration_gpu_jobs.set("3")
                self.assertTrue(app.preferences().migration_cpu_auto)
                app.migration_cpu_auto.set(False)
                self.assertFalse(app.preferences().migration_cpu_auto)
                app.migration_cpu_auto.set(True)
                app.migration_cpu_encoding.set(True)
                app.use_all_cpu_threads()
                self.assertEqual(app.preferences().cpu_threads,
                    max(1, min(1024, (getattr(os, "process_cpu_count", os.cpu_count)() or 1))))
                app.max_source_percent.set("200")
                self.assertEqual(app.preferences().migration_gpu_jobs, 3)
                self.assertTrue(app.preferences().migration_cpu_encoding)
                self.assertEqual(app.preferences().max_source_percent, 200)
                app.migration_local_names.set(True)
                def migrate(*args, **kwargs):
                    kwargs["progress"](Progress("copying", 25, 1005, 1005, 10, 392, time.monotonic()))
                    return 2  # Finishes early; progress must not pretend 100%.
                with patch("videomate.migration.migrate_local", side_effect=migrate), \
                        patch("tkinter.messagebox.askyesno", return_value=True):
                    app.start("run_workflow")
                    app.worker.join(timeout=5)
                    self.assertFalse(app.worker.is_alive())
                    app.poll()
                self.assertEqual(str(app.progress.cget("mode")), "determinate")
                self.assertEqual(float(app.progress.cget("value")), 25)
                self.assertEqual(float(app.progress.cget("maximum")), 1005)
                self.assertIn("25 / 1,005", app.progress_text.get())
                self.assertNotIn("remaining", app.progress_text.get())
                app.begin_progress()
                self.assertEqual(str(app.progress.cget("mode")), "indeterminate")
                self.assertIsNone(app.progress_state)
                app.update_progress(Progress("copying", 1, 10, 10, 20, 180, time.monotonic()))
                self.assertIn("remaining", app.progress_text.get())
                root.geometry("800x600")
                root.update()
                self.assertTrue(app.progress_label.winfo_ismapped())
                self.assertLessEqual(app.progress_label.winfo_rooty() + app.progress_label.winfo_height(), root.winfo_rooty() + root.winfo_height())
            finally:
                for after in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", after)
                root.destroy()

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
    def test_workflow_profiles_and_sensitive_migration_consent(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        from videomate.preferences import load_preferences
        with tempfile.TemporaryDirectory(prefix="videomate-workflow-ui-generated-") as temporary:
            base = Path(temporary).resolve()
            root = create_root()
            try:
                root.tk.call("tk", "scaling", 1.5 * 96 / 72)
                with patch.object(Application, "check_tools"):
                    app = Application(root, config_path=base / "settings.json", prepare_on_start=False)
                app.workspace.set(str(base / "workspace"))
                app.video_bitrate_kbps.set("invalid edit")
                app.preset.set("Migrate — keep healthy formats")
                app.preset_choice.event_generate("<<ComboboxSelected>>")
                self.assertEqual(app.workflow.get(), "migrate")
                self.assertNotEqual(str(app.resume_option.cget('state')), 'disabled')
                self.assertTrue(app.interruption_recovery.get())
                reconnect_controls = [widget for widget, _ in app.controls
                                      if widget.winfo_class() == 'Checkbutton' and 'Migration interruption recovery' in str(widget.cget('text'))]
                self.assertEqual(len(reconnect_controls), 1)
                self.assertEqual(reconnect_controls[0].winfo_manager(), 'pack')
                self.assertEqual(app.video_bitrate_kbps.get(), "8000")
                self.assertTrue(app.sensitive.get())
                self.assertFalse(app.migration_local_names.get())
                self.assertEqual(app.migration_unresolved.get(), "Exclude from output; keep sources")
                root.geometry("800x600")
                app.show("queue")
                # WSLg can start a later test window iconified after several
                # rapid root create/destroy cycles. Show this isolated root
                # and wait for native mapping before asserting visibility.
                root.update()
                root.withdraw()
                root.deiconify()
                import time
                deadline = time.monotonic() + 2
                while not app.migration_panel.winfo_ismapped() and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                self.assertTrue(app.migration_panel.winfo_ismapped())
                self.assertTrue(app.migration_resume_card.winfo_ismapped())
                self.assertIn('Session only', app.resume_mode_hint.get())
                card_top = app.migration_resume_card.winfo_rooty() - app.surfaces['queue'].canvas.winfo_rooty()
                self.assertGreaterEqual(card_top, -8)
                self.assertLess(card_top, app.surfaces['queue'].canvas.winfo_height())
                self.assertFalse(app.advanced_frame.winfo_ismapped())
                self.assertEqual(app.run_workflow_button.cget("text"), "Start new migration")
                self.assertTrue(all(button.winfo_class() == "TButton" for button in app.navigation.values()))
                with patch("tkinter.simpledialog.askstring", return_value="Generated profile"):
                    app.save_profile()
                saved = load_preferences(base / "settings.json")
                self.assertEqual(saved.profiles["Generated profile"]["workflow"], "migrate")
                self.assertNotIn("migration_local_names", saved.profiles["Generated profile"])
                source = base / "selection"
                source.mkdir()
                app.add_input(str(source), "Folder")
                app.backend_ready = True
                with patch("videomate.migration.migrate_local", return_value=0) as migrate:
                    with patch("tkinter.messagebox.askyesno", return_value=False) as consent:
                        app.start("run_workflow")
                    consent.assert_called_once()
                    self.assertIsNone(app.worker)
                    self.assertIn("declined", app.status.get())
                    app.migration_unresolved.set("Copy unchanged into output")
                    with patch("tkinter.messagebox.askyesno", return_value=True):
                        app.start("run_workflow")
                    app.worker.join(timeout=5)
                    self.assertFalse(app.worker.is_alive())
                    self.assertTrue(migrate.call_args.kwargs["local_names"])
                    self.assertTrue(migrate.call_args.kwargs["sensitive"])
                    self.assertEqual(migrate.call_args.kwargs["unresolved"], "copy")
                    self.assertEqual(migrate.call_args.kwargs["package_layout"], "direct")
                    self.assertTrue(migrate.call_args.kwargs["recovery"].partial_salvage)
                    self.assertTrue((base / "workspace" / "logs").is_dir())
                app.remove_profile()
                self.assertEqual(load_preferences(base / "settings.json").profiles, {})
            finally:
                for after in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", after)
                root.destroy()

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
    def test_migration_preflight_confirms_restart_choice_and_keeps_failed_resume_id(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        from videomate.errors import VideoMateError
        from videomate.migration_resume import SESSION_RETRIES
        with tempfile.TemporaryDirectory(prefix='videomate-resume-preflight-generated-') as temporary:
            base = Path(temporary).resolve()
            source = base / 'synthetic-source'
            source.mkdir()
            (source / 'generated.txt').write_text('Generated fixture')
            root = create_root()
            try:
                with patch.object(Application, 'check_tools'):
                    app = Application(root, config_path=base / 'settings.json', prepare_on_start=False)
                app.workspace.set(str(base / 'workspace'))
                app.recovered_dir.set(str(base / 'output'))
                app.sensitive.set(False)
                app.workflow.set('migrate')
                app.workflow_changed()
                app.add_input(str(source), 'Folder')
                app.backend_ready = True
                with patch('tkinter.messagebox.askyesno', return_value=False) as confirm:
                    app.start('run_workflow')
                confirm.assert_called_once()
                self.assertIsNone(app.worker)
                self.assertIn('not started', app.status.get())
                app.private_resume.set(True)
                self.assertIn('Restart checkpoint selected', app.resume_mode_hint.get())
                root.geometry('800x600')
                app.show('queue')
                root.update()
                app.open_resume_activity()
                root.update()
                entry_top = app.job_entry.winfo_rooty() - app.surfaces['jobs'].canvas.winfo_rooty()
                self.assertGreaterEqual(entry_top, -8)
                self.assertLess(entry_top, app.surfaces['jobs'].canvas.winfo_height())
                with patch('tkinter.simpledialog.askstring', side_effect=['generated passphrase', 'different passphrase']) as prompt:
                    app.start('run_workflow')
                self.assertEqual(prompt.call_count, 2)
                self.assertIsNone(app.worker)
                self.assertIn('did not match', app.status.get())
                identifier = 'a' * 32
                app.job.set(identifier)
                with patch('tkinter.simpledialog.askstring', return_value='generated passphrase'), \
                        patch('videomate.migration.migrate_local', side_effect=VideoMateError('checkpoint_invalid')):
                    app.start('resume_migration')
                    app.worker.join(timeout=5)
                    self.assertFalse(app.worker.is_alive())
                    app.poll()
                self.assertEqual(app.job.get(), identifier)
                self.assertIn('checkpoint', app.status.get().lower())
                SESSION_RETRIES[identifier] = {'mode': 'continue'}
                with patch('tkinter.messagebox.askyesno', return_value=False) as close_warning:
                    app.close()
                close_warning.assert_called_once()
                self.assertFalse(app.closing)
            finally:
                SESSION_RETRIES.clear()
                for after in root.tk.call('after', 'info'):
                    root.tk.call('after', 'cancel', after)
                root.destroy()

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
    def test_optimizer_is_not_mistaken_for_a_running_migration(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        from videomate.setup_local import ensure_workspace
        with tempfile.TemporaryDirectory(prefix='videomate-optimize-ui-generated-') as temporary:
            base = Path(temporary).resolve()
            ensure_workspace(base / 'workspace')
            root = create_root()
            try:
                with patch.object(Application, 'check_tools'):
                    app = Application(root, config_path=base / 'settings.json', prepare_on_start=False)
                app.workspace.set(str(base / 'workspace'))
                app.workflow.set('migrate')
                app.workflow_changed()
                app.backend_ready = True
                with patch('videomate.calibration.optimize_generated', return_value={}), \
                        patch('videomate.dependencies.load_bundle', return_value=object()):
                    app.optimize_hardware()
                    app.worker.join(timeout=5)
                self.assertFalse(app.worker.is_alive())
                self.assertTrue(any(kind == 'calibration_ready' for kind, _ in list(app.events.queue)))
                self.assertIsNone(app.active_operation)
                with patch('tkinter.messagebox.askyesno') as warning:
                    app.close()
                warning.assert_not_called()
            finally:
                for after in root.tk.call('after', 'info'):
                    root.tk.call('after', 'cancel', after)
                root.destroy()

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
    def test_startup_prepares_missing_settings_and_folders_without_inputs(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        from videomate.preferences import load_preferences
        with tempfile.TemporaryDirectory(prefix="videomate-startup-generated-") as temporary:
            base = Path(temporary).resolve()
            root = create_root()
            try:
                with patch.object(Application, "check_tools"), \
                        patch("videomate.preferences.default_workspace", return_value=base / "workspace"), \
                        patch("videomate.gui.default_workspace", return_value=base / "workspace"):
                    app = Application(root, config_path=base / "settings.json")
                self.assertEqual(app.inputs, [])
                self.assertEqual(load_preferences(base / "settings.json").workspace, str(base / "workspace"))
                for name in ("state", "jobs", "recovered", "export-review", "logs"):
                    self.assertTrue((base / "workspace" / name).is_dir())
                app.workflow.set("migrate")
                app.backend_ready = True
                app.workflow_changed()
                chosen = base / "generated-selection"
                chosen.mkdir()
                with patch("tkinter.filedialog.askdirectory", return_value=str(chosen)):
                    app.run_workflow_button.invoke()
                self.assertEqual(app.inputs, [str(chosen)])
                self.assertIsNone(app.worker)
                self.assertIn("Start migration", app.status.get())
                app.workspace.set(str(base / "another-workspace"))
                app.recovered_dir.set(str(base / "chosen-output"))
                self.assertTrue(app.initialize())
                self.assertTrue((base / "another-workspace" / "jobs").is_dir())
                self.assertTrue((base / "chosen-output").is_dir())
            finally:
                for after in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", after)
                root.destroy()

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
    def test_private_resume_and_recovery_controls_fit_compact_viewport(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        from videomate.preferences import load_preferences
        with tempfile.TemporaryDirectory(prefix="videomate-private-controls-generated-") as temporary:
            root = create_root()
            config = Path(temporary).resolve() / "new-settings.json"
            try:
                root.tk.call("tk", "scaling", 1.5 * 96 / 72)
                with patch.object(Application, "check_tools"):
                    app = Application(root, config_path=config, prepare_on_start=False)
                root.geometry("800x600")
                root.update()
                self.assertTrue(app.layout_option.instate(["disabled"]))
                self.assertEqual(str(app.mapping_option.cget("state")), "disabled")
                app.private_resume.set(True)
                app.convert_all_mp4.set(True)
                app.rate_control.set("Target file size")
                app.target_size_mib.set("250")
                app.max_shorter_percent.set("5")
                app.workflow.set("repair")
                app.advanced.set(True)
                app.workflow_changed()
                app.save_settings()
                saved = load_preferences(config)
                self.assertTrue(saved.private_resume)
                self.assertTrue(saved.convert_all_mp4)
                self.assertFalse(saved.retain_history)
                self.assertEqual((saved.rate_control, saved.target_size_mib, saved.max_shorter_percent), ("target_size", 250, 5))
                for key, surface in app.surfaces.items():
                    app.show(key)
                    root.update()
                    for control, _ in app.controls:
                        if not surface.contains(control) or not control.winfo_ismapped():
                            continue
                        surface.reveal(SimpleNamespace(widget=control))
                        root.update()
                        self.assertLessEqual(control.winfo_rootx() + control.winfo_width(),
                                             surface.canvas.winfo_rootx() + surface.canvas.winfo_width(), (key, control.winfo_class()))
                        self.assertLessEqual(control.winfo_rooty() + control.winfo_height(),
                                             surface.canvas.winfo_rooty() + surface.canvas.winfo_height() + 1, (key, control.winfo_class()))
            finally:
                for after in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", after)
                root.destroy()

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
    def test_additional_diagnostics_checkbox_is_visible_independent_and_persisted(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        from videomate.preferences import load_preferences
        with tempfile.TemporaryDirectory(prefix="videomate-diagnostic-ui-generated-") as temporary:
            root = create_root()
            config = Path(temporary).resolve() / "new-settings.json"
            try:
                root.tk.call("tk", "scaling", 1.5 * 96 / 72)
                with patch.object(Application, "check_tools"):
                    app = Application(root, config_path=config, prepare_on_start=False)
                root.geometry("800x600")
                root.update()
                checkbox = app.diagnostic_checkbox
                self.assertTrue(checkbox.winfo_ismapped())
                self.assertLessEqual(checkbox.winfo_rootx() + checkbox.winfo_width(), root.winfo_rootx() + root.winfo_width())
                self.assertFalse(app.diagnostic_logs.get())
                self.assertTrue(app.sensitive.get())
                checkbox.invoke()
                self.assertTrue(app.diagnostic_logs.get())
                self.assertTrue(app.sensitive.get())
                self.assertIn("diagnostics on", app.privacy_hint.get())
                app.workspace.set(str(Path(temporary).resolve() / "workspace"))
                app.save_settings()
                self.assertTrue(load_preferences(config).diagnostic_logs)
                app.reset_settings()
                self.assertFalse(app.diagnostic_logs.get())
            finally:
                for after in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", after)
                root.destroy()

    def test_small_screens_never_receive_an_oversized_minimum(self):
        from videomate.gui_layout import initial_geometry
        for scale in (1, 1.5, 2, 3):
            for width, height in ((800, 600), (1024, 768), (1920, 1080)):
                w, h, mw, mh = initial_geometry(width, height, scale)
                self.assertLess(w, width)
                self.assertLess(h, height)
                self.assertLessEqual(mw, w)
                self.assertLessEqual(mh, h)

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
    def test_all_controls_remain_reachable_across_sizes_and_text_scales(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        with tempfile.TemporaryDirectory(prefix="videomate-layout-") as temporary:
            for scale in (1, 1.5, 2):
                root = create_root()
                root.tk.call("tk", "scaling", scale * 96 / 72)
                errors = []
                try:
                    with patch.object(Application, "check_tools"):
                        app = Application(root, config_path=Path(temporary).resolve() / "new-settings.json", prepare_on_start=False)
                    app.workflow.set("migrate")
                    app.advanced.set(True)
                    app.workflow_changed()
                    app.progress_text.set("25 / 1,005 files · Elapsed 10m 12s · About 1h 20m remaining")
                    root.report_callback_exception = lambda *error: errors.append(error)
                    for width, height in ((800, 600), (1024, 768), (1440, 900)):
                        with self.subTest(scale=scale, width=width, height=height):
                            root.geometry(f"{width}x{height}")
                            root.update()
                            self.assertLessEqual(root.winfo_width(), width)
                            for control in (*app.navigation.values(), app.cancel_button, app.run_workflow_button, app.progress_label):
                                self.assertTrue(control.winfo_ismapped())
                                self.assertLessEqual(control.winfo_rootx() + control.winfo_width(), root.winfo_rootx() + root.winfo_width())
                                self.assertLessEqual(control.winfo_rooty() + control.winfo_height(), root.winfo_rooty() + root.winfo_height())
                            for key, surface in app.surfaces.items():
                                app.show(key)
                                root.update()
                                self.assertGreater(surface.canvas.winfo_height(), 80)
                                for control, _ in app.controls:
                                    if not surface.contains(control) or not control.winfo_ismapped():
                                        continue
                                    surface.reveal(SimpleNamespace(widget=control))
                                    root.update()
                                    x = control.winfo_rootx() - surface.canvas.winfo_rootx()
                                    y = control.winfo_rooty() - surface.canvas.winfo_rooty()
                                    self.assertGreaterEqual(x, 0)
                                    self.assertLessEqual(x + control.winfo_width(), surface.canvas.winfo_width(), (key, control.winfo_class()))
                                    self.assertGreaterEqual(y, -1)
                                    self.assertLessEqual(y + control.winfo_height(), surface.canvas.winfo_height() + 1, (key, control.winfo_class()))
                            self.assertFalse(errors)
                finally:
                    for after in root.tk.call("after", "info"):
                        root.tk.call("after", "cancel", after)
                    root.destroy()
