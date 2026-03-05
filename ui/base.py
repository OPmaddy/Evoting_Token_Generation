import tkinter as tk
from ui.styles import BG_COLOR

class FullscreenApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("E-Voting Terminal")

        # Force an initial size and update before setting fullscreen
        self.root.geometry("800x600")
        self.root.update_idletasks()
        
        # Fullscreen for Raspberry Pi, fallback to zoomed for Windows
        self.root.attributes("-fullscreen", True)
        self.root.update_idletasks()
        self.root.update()
        try:
            self.root.state('zoomed')
        except tk.TclError:
            pass

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
