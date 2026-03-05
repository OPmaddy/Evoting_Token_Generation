import tkinter as tk
from ui.styles import BG_COLOR

class FullscreenApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("E-Voting Terminal")

        # Fullscreen for Raspberry Pi
        self.root.attributes("-fullscreen", True)

        self.exit_requested = False

        # ESC to exit (useful on laptop)
        self.root.bind("<Escape>", self._exit)

        self.container = tk.Frame(self.root, bg=BG_COLOR)
        self.container.pack(fill="both", expand=True)

    def clear(self):
        """Remove all widgets from screen"""
        for w in self.container.winfo_children():
            w.destroy()

    def _exit(self, event=None):
        self.exit_requested = True
        self.root.destroy()
