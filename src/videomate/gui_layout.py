"""Responsive Tk layout helpers. No media, network or user settings access."""
import sys


def create_root():
    import tkinter as tk
    # Process-local only, before creating a window. Tk 8.6 is system-DPI aware;
    # don't claim per-monitor font scaling or change desktop display settings.
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2))
        except (AttributeError, OSError):
            pass  # Older systems retain their existing process DPI policy.
    return tk.Tk()


def initial_geometry(screen_width, screen_height, scale):
    """Leave room for desktop chrome; never impose a larger minimum than the screen."""
    width, height = max(240, screen_width - 80), max(240, screen_height - 120)
    return (min(round(1180 * scale), width), min(round(820 * scale), height),
            min(640, width), min(420, height))


class ScrollSurface:
    """Grow to fill a page, or scroll its natural height when space is limited."""
    def __init__(self, parent, background):
        import tkinter as tk
        from tkinter import ttk
        self.outer = ttk.Frame(parent)
        self.canvas = tk.Canvas(self.outer, bg=background, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self.outer, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.frame = ttk.Frame(self.canvas, padding=(0, 0, 12, 8))
        self.window = self.canvas.create_window(0, 0, window=self.frame, anchor="nw")
        self.canvas.bind("<Configure>", self.resize)
        self.frame.bind("<Configure>", self.resize)

    def resize(self, event=None):
        width = max(1, self.canvas.winfo_width())
        height = max(self.canvas.winfo_height(), self.frame.winfo_reqheight())
        # Let Tk track natural height. Fixing the window height here prevents
        # wrapped text from notifying the canvas when its requested height changes.
        self.canvas.itemconfigure(self.window, width=width)
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def contains(self, widget):
        return str(widget).startswith(str(self.canvas) + ".") or widget is self.canvas

    def reveal(self, event):
        if not self.outer.winfo_ismapped():
            return
        self.canvas.update_idletasks()
        top = event.widget.winfo_rooty() - self.canvas.winfo_rooty()
        bottom = top + event.widget.winfo_height()
        if top < 0 or bottom > self.canvas.winfo_height():
            offset = top - 8 if top < 0 else bottom - self.canvas.winfo_height() + 8
            height = max(1, self.frame.winfo_height())
            self.canvas.yview_moveto(max(0, self.canvas.canvasy(0) + offset) / height)


def wrap_to_parent(widget, inset=24):
    """Text uses the actual viewport width, including after a DPI or size change."""
    def resize(event):
        widget.configure(wraplength=max(80, event.width - inset))
    widget.master.bind("<Configure>", resize, add="+")
    return widget


def flow_buttons(parent, buttons, gap=8):
    """Wrap actions onto another row without shrinking their labels."""
    parent.configure(height=48)
    parent.pack_propagate(False)
    def resize(event):
        x, y, row_height = 0, 0, 0
        for button in buttons:
            width, height = button.winfo_reqwidth(), button.winfo_reqheight()
            if x and x + width > event.width:
                x, y, row_height = 0, y + row_height + gap, 0
            button.place(x=x, y=y, width=width, height=height)
            x += width + gap
            row_height = max(row_height, height)
        parent.configure(height=y + row_height + gap)
    parent.bind("<Configure>", resize, add="+")
