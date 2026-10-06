"""Native journey checks using only generated selections and stub services.

The selected .mp4 is a labelled text placeholder, never decoded or probed.
Pickers, tool checks, preparation and processing are patched; no operator state
or dialog is opened. These checks do not establish screen-reader usability.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Native GUI testing not enabled")
class GuiJourneyTests(unittest.TestCase):
    def setUp(self):
        from videomate.gui import Application
        from videomate.gui_layout import create_root
        self.temporary = tempfile.TemporaryDirectory(prefix="videomate-journey-generated-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = create_root()
        self.addCleanup(self.close_generated_window)
        with patch.object(Application, "check_tools"):
            self.app = Application(self.root, config_path=self.base / "settings.json", prepare_on_start=False)
        self.app.workspace.set(str(self.base / "workspace"))
        self.app.backend_ready = True
        self.app.workflow_changed()
        self.root.geometry("800x600")
        self.root.update()

    def close_generated_window(self):
        self.app.cancel.set()
        if self.app.worker:
            self.app.worker.join(timeout=5)
        for timer in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()

    def finish_worker(self):
        self.app.worker.join(timeout=5)
        self.assertFalse(self.app.worker.is_alive())
        self.app.poll()
        self.root.update()
        self.assertFalse(self.app.busy)

    def test_native_keyboard_traversal_reaches_active_settings_and_skips_hidden_fields(self):
        app = self.app
        app.show("setup")
        app.show_settings_section("performance")
        self.root.update()
        anchor = app.navigation["setup"]
        current, chain = anchor, []
        for _ in range(200):
            current = current.tk_focusNext()
            if str(current) in chain:
                break
            chain.append(str(current))
        else:
            self.fail("Native keyboard traversal did not return to a known control")
        cpu = app.field_widgets[str(app.cpu_threads)]
        timeout = app.field_widgets[str(app.timeout)]
        hidden_workspace = app.field_widgets[str(app.workspace)]
        for control in (cpu, timeout, app.optimize_button, app.run_workflow_button,
                        *app.settings_navigation.values(), *app.navigation.values()):
            self.assertIn(str(control), chain)
        self.assertNotIn(str(hidden_workspace), chain)
        self.assertNotIn(str(app.cancel_button), chain)  # Stop is disabled while idle.
        self.root.focus_force()
        cpu.focus_set()
        self.root.update()
        self.assertEqual(self.root.focus_get(), cpu)
        expected_next = cpu.tk_focusNext()
        cpu.event_generate("<Tab>")
        self.root.update()
        self.assertEqual(self.root.focus_get(), expected_next)
        expected_next.event_generate("<Shift-Tab>")
        self.root.update()
        self.assertEqual(self.root.focus_get(), cpu)
        canvas = app.surfaces["setup"].canvas
        self.assertGreaterEqual(cpu.winfo_rooty(), canvas.winfo_rooty() - 1)
        self.assertLessEqual(cpu.winfo_rooty() + cpu.winfo_height(), canvas.winfo_rooty() + canvas.winfo_height() + 1)

    def test_first_inspection_then_repair_routes_the_same_generated_selection(self):
        app = self.app
        self.assertEqual(app.workflow.get(), "inspect")
        self.assertTrue(app.sensitive.get())
        self.assertEqual(app.inputs, [])
        self.assertFalse(app.destination_panel.winfo_ismapped())
        self.assertTrue(app.preview_workflow_button.instate(["disabled"]))
        self.assertIn("Add videos", app.empty.cget("text"))
        placeholder = self.base / "generated-placeholder.mp4"
        original = b"Generated selection placeholder, not media; processing must be stubbed."
        placeholder.write_bytes(original)
        app.add_input(str(placeholder))
        self.assertEqual(app.files.item("0", "values")[0], "Item 1")
        with patch("videomate.gui.prepare_application", return_value=self.base / "workspace"), \
                patch("videomate.gui.scan_local", return_value=0) as scan:
            app.run_workflow_button.invoke()
            self.finish_worker()
        self.assertEqual(scan.call_args.args[0], [str(placeholder)])
        self.assertIsNone(scan.call_args.kwargs["recovery"])
        self.assertTrue(scan.call_args.kwargs["sensitive"])
        app.workflow.set("repair")
        app.workflow_changed()
        app.show("queue")
        self.root.update()
        self.assertTrue(app.destination_panel.winfo_ismapped())
        self.assertFalse(app.preview_workflow_button.instate(["disabled"]))
        self.assertIn("MKV", app.workflow_intro.get())
        output = self.base / "generated-output"
        app.recovered_dir.set(str(output))
        self.assertTrue(app.custom_output.get())
        self.assertEqual(app.preferences().recovered_dir, str(output))
        with patch("videomate.gui.prepare_application", return_value=self.base / "workspace"), \
                patch("videomate.gui.scan_local", return_value=0) as repair:
            app.run_workflow_button.invoke()
            self.finish_worker()
        self.assertEqual(repair.call_args.args[0], [str(placeholder)])
        self.assertEqual(repair.call_args.kwargs["recovery"].profile, "preserve_decoded_samples")
        self.assertEqual(repair.call_args.kwargs["recovered_dir"], str(output))
        self.assertTrue(repair.call_args.kwargs["sensitive"])
        self.assertEqual(placeholder.read_bytes(), original)
        self.assertFalse(output.exists())  # Stub workers cannot publish output.

    def test_migration_source_replaces_queue_and_preview_keeps_output_uncreated(self):
        app = self.app
        app.add_input(str(self.base / "generated-prior-selection.mp4"))
        app.workflow.set("migrate")
        app.workflow_changed()
        self.assertTrue(app.add_files_button.instate(["disabled"]))
        self.assertTrue(app.recursive.get())
        source = self.base / "generated-source"
        source.mkdir()
        output = self.base / "generated-migration-output"
        with patch("tkinter.filedialog.askdirectory", return_value=str(source)) as picker:
            app.add_folder_button.invoke()
        picker.assert_called_once()
        self.assertEqual(app.inputs, [str(source)])
        self.assertEqual(app.input_kinds, ["Folder"])
        self.assertEqual(len(app.files.get_children()), 1)
        self.assertEqual(app.files.item("0", "values")[0], "Item 1")
        app.recovered_dir.set(str(output))
        self.root.update()
        self.assertTrue(app.destination_controls.winfo_ismapped())
        self.assertFalse(app.output_toggle.winfo_ismapped())
        with patch("videomate.gui.prepare_application", return_value=self.base / "workspace"), \
                patch("videomate.migration.migrate_local", return_value=0) as migrate, \
                patch("tkinter.messagebox.askyesno") as confirmation:
            app.preview_workflow_button.invoke()
            self.finish_worker()
        confirmation.assert_not_called()
        self.assertEqual(migrate.call_args.args[0], [str(source)])
        self.assertFalse(migrate.call_args.kwargs["execute"])
        self.assertTrue(migrate.call_args.kwargs["sensitive"])
        self.assertFalse(migrate.call_args.kwargs["local_names"])
        self.assertEqual(migrate.call_args.kwargs["recovered_dir"], str(output))
        self.assertIn("no package created", app.status.get().lower())
        self.assertFalse(output.exists())
        self.assertFalse(app.busy)
