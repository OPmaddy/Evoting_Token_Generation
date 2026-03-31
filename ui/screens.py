# ui/screens.py
import tkinter as tk
import os
from PIL import Image, ImageTk

from ui.styles import (
    BG_COLOR, FG_COLOR, FG_SECONDARY,
    ACCENT_COLOR, SUCCESS_COLOR, ERROR_COLOR, WARNING_COLOR,
    FONT_LARGE, FONT_MED, FONT_SMALL, FONT_HEADER, FONT_FAMILY
)


def _center_frame(app):
    frame = tk.Frame(app.container, bg=BG_COLOR)
    frame.place(relx=0.5, rely=0.5, anchor="center")
    return frame

def _styled_button(parent, text, command, bg=ACCENT_COLOR, fg="white"):
    # Helper for consistent buttons
    return tk.Button(
        parent, text=text, font=FONT_MED,
        command=command,
        bg=bg, fg=fg,
        activebackground=FG_SECONDARY, activeforeground="white",
        relief="flat", padx=20, pady=10, cursor="hand2"
    )

# ---------------- ENTRY SCREEN ---------------- #

# ---------------- ENTRY SCREEN ---------------- #

def entry_number_screen(app, mock_rfid=True):
    app.clear()
    result = {"value": None}

    # Use a main frame that fills the screen to allow better layout control
    # instead of just a centered box, but getting it centered is nice.
    # We'll stick to _center_frame but ensure it handles the height.
    frame = _center_frame(app)

    # Compact Layout for Pi (480px height)
    tk.Label(frame, text="VOTER IDENTIFICATION",
             fg=FG_SECONDARY, bg=BG_COLOR, font=("Segoe UI", 24, "bold")).pack(pady=(0, 5))

    tk.Label(frame, text="Please enter your unique Entry Number below:",
             fg=FG_COLOR, bg=BG_COLOR, font=("Segoe UI", 14)).pack(pady=2)

    entry = tk.Entry(frame, font=("Segoe UI", 20), justify="center", 
                     bg="white", fg="black", highlightthickness=1, relief="solid",
                     width=18)
    entry.pack(pady=5, ipady=5)
    entry.focus()

    def submit():
        val = entry.get().strip()
        if val:
            result["value"] = val

    # --- Keyboard ---
    kb_frame = tk.Frame(frame, bg=BG_COLOR)
    kb_frame.pack(pady=5)

    def on_key(char):
        if char == "⌫":
            current = entry.get()
            entry.delete(len(current)-1, tk.END)
        else:
            entry.insert(tk.END, char)

    keys = [
        "1234567890",
        "QWERTYUIOP",
        "ASDFGHJKL",
        "ZXCVBNM"
    ]

    # Style for keys
    KEY_BG = "#FFFFFF"
    KEY_FG = "#333333"
    KEY_ACTIVE_BG = "#E0E0E0"

    for row_idx, row_chars in enumerate(keys):
        row_frame = tk.Frame(kb_frame, bg=BG_COLOR)
        row_frame.pack(pady=1) # Minimal pad between rows
        
        for char in row_chars:
            tk.Button(
                row_frame, text=char, font=("Segoe UI", 12, "bold"),
                width=4, height=1, # Reduced height
                bg=KEY_BG, fg=KEY_FG,
                activebackground=KEY_ACTIVE_BG,
                relief="raised", bd=1,
                command=lambda c=char: on_key(c)
            ).pack(side="left", padx=2, pady=1)

    # Backspace
    last_row_frame = kb_frame.winfo_children()[-1]
    tk.Button(
        last_row_frame, text="⌫", font=("Segoe UI", 12, "bold"),
        width=4, height=1,
        bg="#ffcccc", fg="#cc0000",
        activebackground="#ffa3a3",
        relief="raised", bd=1,
        command=lambda: on_key("⌫")
    ).pack(side="left", padx=2, pady=1)

    # --- Actions ---
    btn_frame = tk.Frame(frame, bg=BG_COLOR)
    btn_frame.pack(pady=10) # Reduced from 20

    # Custom compact styled button to avoid the huge padding in default _styled_button
    tk.Button(
        btn_frame, text="PROCEED", font=FONT_MED,
        command=submit,
        bg=ACCENT_COLOR, fg="white",
        activebackground=FG_SECONDARY, activeforeground="white",
        relief="flat", padx=20, pady=5, cursor="hand2"
    ).pack()
    
    # Bind Enter key
    app.root.bind('<Return>', lambda e: submit())

    # --- RFID Background Polling ---
    import threading
    import time
    stop_event = threading.Event()
    
    def rfid_poll():
        try:
            from hardware.rfid_reader import RFIDEntryReader
            reader = RFIDEntryReader()
            while not stop_event.is_set():
                val = reader.read_entry_number()
                if val:
                    # Update the UI state from the main thread safely
                    app.root.after(0, lambda v=val: result.update({"value": v}))
                    break
                time.sleep(0.3)
            reader.close()
        except Exception as e:
            print(f"RFID Reader disabled/error: {e}")

    if not mock_rfid:
        threading.Thread(target=rfid_poll, daemon=True).start()

    # Wait until value entered or exit
    while result["value"] is None and not app.exit_requested:
        app.root.update()
        time.sleep(0.05)
    
    stop_event.set()
    app.root.unbind('<Return>')
    return result["value"]


# ---------------- STATUS SCREEN ---------------- #

def status_screen(app, title, message, fg=FG_COLOR, delay=None, on_done=None):
    app.clear()
    frame = _center_frame(app)

    # Convert generic color names to theme colors if possible
    title_fg = fg
    if fg == "red": title_fg = ERROR_COLOR
    elif fg == "green": title_fg = SUCCESS_COLOR
    elif fg == "white": title_fg = FG_COLOR # Default fallback

    tk.Label(frame, text=title, fg=title_fg,
             bg=BG_COLOR, font=FONT_LARGE).pack(pady=20)

    tk.Label(frame, text=message, fg=FG_COLOR,
             bg=BG_COLOR, font=FONT_MED, justify="center").pack(pady=10)

    if delay is not None and on_done:
        app.root.after(delay, on_done)
    elif on_done:
        _styled_button(frame, "CONTINUE", on_done).pack(pady=30)


# ---------------- DUPLICATE TOKEN ---------------- #

# ---------------- DUPLICATE TOKEN ---------------- #

def already_generated_screen(app, voter, on_done=None):
    app.clear()
    frame = _center_frame(app)

    # Title
    tk.Label(frame, text="⚠️ ALREADY VOTED",
             fg=WARNING_COLOR, bg=BG_COLOR, font=("Segoe UI", 24, "bold")).pack(pady=(10, 5))

    # Booth Number (Prominent)
    booth_num = voter.get('Booth_Number') or 'Unknown'
    tk.Label(frame, text=f"ASSIGNED BOOTH: {booth_num}",
             fg=ACCENT_COLOR, bg=BG_COLOR, font=("Segoe UI", 40, "bold")).pack(pady=5)

    # Timestamp
    ts = voter.get('Token_Timestamp') or 'Unknown'
    tk.Label(frame, text=f"Previously Verified At: {ts}",
             fg=FG_SECONDARY, bg=BG_COLOR, font=("Segoe UI", 12)).pack(pady=2)

    # Images (Compact for Pi)
    img1_path = voter.get('Image1Path')
    img2_path = voter.get('Image2Path')
    
    imgs_frame = tk.Frame(frame, bg=BG_COLOR)
    imgs_frame.pack(pady=10)
    
    app.current_images = [] # Keep refs

    for path in [img1_path, img2_path]:
        if path and os.path.exists(path):
            try:
                pil_img = Image.open(path)
                pil_img.thumbnail((140, 140)) # Reduced from 220
                tk_img = ImageTk.PhotoImage(pil_img)
                app.current_images.append(tk_img)
                
                # Image container with border
                cont = tk.Frame(imgs_frame, bg="#ddd", bd=1)
                cont.pack(side="left", padx=10)
                
                lbl = tk.Label(cont, image=tk_img, bg="white")
                lbl.pack(padx=2, pady=2)
            except Exception as e:
                print(f"Error loading image {path}: {e}")
                tk.Label(imgs_frame, text="Img Error", bg=BG_COLOR, fg=ERROR_COLOR, font=FONT_SMALL).pack(side="left", padx=5)
        else:
             tk.Label(imgs_frame, text="No Img", bg=BG_COLOR, fg=FG_SECONDARY, font=FONT_SMALL).pack(side="left", padx=5)

    # Dispute Message
    name = voter.get('Name', 'Unknown')
    msg = (f"Voter Name: {name}\n"
           "Record indicates this voter has already engaged with the system.\n"
           "If disputed, contact Polling Officer.")
           
    tk.Label(frame, text=msg,
             fg=ERROR_COLOR, bg=BG_COLOR, font=("Segoe UI", 12), justify="center").pack(pady=10)

    # Auto-timeout handling
    timer_id = None
    
    def manual_continue():
        if timer_id:
            app.root.after_cancel(timer_id)
        if on_done:
            on_done()

    _styled_button(frame, "CONTINUE", manual_continue, bg=FG_SECONDARY).pack(pady=10)
    
    # 10 Second Timeout
    if on_done:
        timer_id = app.root.after(10000, on_done)


# ---------------- FACE VERIFICATION ---------------- #

def verification_progress_screen(app, message):
    app.clear()
    frame = _center_frame(app)

    tk.Label(frame, text="IDENTITY VERIFICATION",
             fg=ACCENT_COLOR, bg=BG_COLOR, font=FONT_LARGE).pack(pady=20)

    tk.Label(frame, text=message,
             fg=FG_COLOR, bg=BG_COLOR, font=FONT_MED,
             justify="center").pack(pady=20)

    # Add a spinner placeholder or progress text
    tk.Label(frame, text="Processing...", fg=FG_SECONDARY, bg=BG_COLOR, font=FONT_SMALL).pack(pady=10)

    app.root.update()


# ---------------- RFID STATUS ---------------- #

def rfid_status_screen(app, message):
    # On first call (or after a clear), build the full screen layout.
    # On subsequent calls, only update the status label text to avoid flickering.
    if not hasattr(app, '_rfid_status_label') or app._rfid_status_label is None:
        app.clear()
        frame = _center_frame(app)

        # Title
        tk.Label(frame, text="TOKEN GENERATION",
                 fg=ACCENT_COLOR, bg=BG_COLOR, font=FONT_LARGE).pack(pady=(20, 10))

        # Static Instruction
        tk.Label(frame, text="Please place your Smart Card on the sensor pad.",
                 fg=FG_COLOR, bg=BG_COLOR, font=FONT_MED).pack(pady=5)

        tk.Label(frame, text="Hold the card steady until writing is complete.",
                 fg=FG_SECONDARY, bg=BG_COLOR, font=FONT_SMALL).pack(pady=(0, 20))

        # Dynamic Status Label (kept as a reference for updates)
        status_label = tk.Label(frame, text=message,
                                fg=ACCENT_COLOR, bg=BG_COLOR, font=("Consolas", 14),
                                justify="center")
        status_label.pack(pady=10)
        app._rfid_status_label = status_label
    else:
        # Just update the text — no screen rebuild
        app._rfid_status_label.config(text=message)

    app.root.update()


# ---------------- BOOTH CONFIRMATION ---------------- #

def booth_confirmation_screen(app, booth, on_done=None):
    app.clear()
    frame = _center_frame(app)

    tk.Label(frame, text="VERIFICATION SUCCESSFUL",
             fg=SUCCESS_COLOR, bg=BG_COLOR, font=FONT_HEADER).pack(pady=20)

    tk.Label(frame, text="You are authorized to vote.",
             fg=FG_COLOR, bg=BG_COLOR, font=FONT_MED).pack(pady=10)

    tk.Label(frame, text=f"Please proceed to:",
             fg=FG_SECONDARY, bg=BG_COLOR, font=FONT_SMALL).pack(pady=(20, 5))
             
    tk.Label(frame, text=f"BOOTH {booth}",
             fg=ACCENT_COLOR, bg=BG_COLOR, font=("Segoe UI", 60, "bold")).pack(pady=10)

    _styled_button(frame, "FINISH", on_done, bg=SUCCESS_COLOR).pack(pady=30)


# ---------------- VOTER CONFIRMATION ---------------- #

def voter_confirmation_screen(app, voter):
    app.clear()
    result = {"confirmed": None}
    frame = _center_frame(app)

    # Title
    tk.Label(frame, text="CONFIRM VOTER IDENTITY",
             fg=FG_SECONDARY, bg=BG_COLOR, font=("Segoe UI", 24, "bold")).pack(pady=(10, 20))

    # Voter Name (Large & Clear)
    name = voter.get('Name', 'Unknown Name')
    tk.Label(frame, text=name.upper(),
             fg=ACCENT_COLOR, bg=BG_COLOR, font=("Segoe UI", 36, "bold"),
             wraplength=600, justify="center").pack(pady=10)

    # Entry Number
    entry = voter.get('Entry_Number', 'Unknown')
    tk.Label(frame, text=f"Entry Number: {entry}",
             fg=FG_COLOR, bg=BG_COLOR, font=("Segoe UI", 18)).pack(pady=5)

    # Buttons Container
    btn_frame = tk.Frame(frame, bg=BG_COLOR)
    btn_frame.pack(pady=30)

    def on_confirm():
        result["confirmed"] = True

    def on_cancel():
        result["confirmed"] = False

    # Confirm Button
    tk.Button(
        btn_frame, text="CONFIRM & PROCEED", font=("Segoe UI", 16, "bold"),
        command=on_confirm,
        bg=SUCCESS_COLOR, fg="white",
        activebackground="#1b5e20", activeforeground="white",
        relief="flat", padx=30, pady=15, cursor="hand2"
    ).pack(side="left", padx=20)

    # Cancel Button
    tk.Button(
        btn_frame, text="INCORRECT / CANCEL", font=("Segoe UI", 16, "bold"),
        command=on_cancel,
        bg=ERROR_COLOR, fg="white",
        activebackground="#b71c1c", activeforeground="white",
        relief="flat", padx=30, pady=15, cursor="hand2"
    ).pack(side="left", padx=20)

    # Wait loop
    import time
    while result["confirmed"] is None and not app.exit_requested:
        app.root.update()
        time.sleep(0.05)

    return result["confirmed"]
