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
    tk.Label(frame, text=f"DEVICE ID: {getattr(app, 'device_id', 'Unknown')}",
             fg=FG_SECONDARY, bg=BG_COLOR, font=("Segoe UI", 10, "bold")).pack(pady=(0, 2))

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

# ---------------- PASSWORD SCREEN ---------------- #

def password_prompt_screen(app):
    app.clear()
    result = {"value": None}

    frame = _center_frame(app)

    tk.Label(frame, text="SYSTEM RESET",
             fg=ERROR_COLOR, bg=BG_COLOR, font=("Segoe UI", 24, "bold")).pack(pady=(0, 5))

    tk.Label(frame, text="Enter administrative password:",
             fg=FG_COLOR, bg=BG_COLOR, font=("Segoe UI", 14)).pack(pady=2)

    entry = tk.Entry(frame, font=("Segoe UI", 20), justify="center", show="*",
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
        "qwertyuiop",
        "asdfghjkl",
        "zxcvbnm",
        "-_@."
    ]

    KEY_BG = "#FFFFFF"
    KEY_FG = "#333333"
    KEY_ACTIVE_BG = "#E0E0E0"

    for row_idx, row_chars in enumerate(keys):
        row_frame = tk.Frame(kb_frame, bg=BG_COLOR)
        row_frame.pack(pady=1) 
        
        for char in row_chars:
            tk.Button(
                row_frame, text=char, font=("Segoe UI", 12, "bold"),
                width=4, height=1, 
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

    btn_frame = tk.Frame(frame, bg=BG_COLOR)
    btn_frame.pack(pady=10) 

    tk.Button(
        btn_frame, text="PROCEED", font=FONT_MED,
        command=submit,
        bg=ACCENT_COLOR, fg="white",
        activebackground=FG_SECONDARY, activeforeground="white",
        relief="flat", padx=20, pady=5, cursor="hand2"
    ).pack()
    
    app.root.bind('<Return>', lambda e: submit())

    import time
    while result["value"] is None and not app.exit_requested:
        app.root.update()
        time.sleep(0.05)
    
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

# ---------------- ADMIN DASHBOARD ---------------- #

def admin_dashboard_screen(app):
    app.clear()
    result = {"action": None}
    frame = _center_frame(app)

    tk.Label(frame, text="ADMIN DASHBOARD",
             fg=ACCENT_COLOR, bg=BG_COLOR, font=("Segoe UI", 24, "bold")).pack(pady=(10, 5))

    tk.Label(frame, text=f"Station ID: {getattr(app, 'device_id', '1')}",
             fg=FG_SECONDARY, bg=BG_COLOR, font=("Segoe UI", 12, "bold")).pack(pady=(0, 10))

    btn_frame = tk.Frame(frame, bg=BG_COLOR)
    btn_frame.pack(pady=10)

    def on_reset(): result["action"] = "RESET"
    def on_set_bmds(): result["action"] = "SET_BMDS"
    def on_regenerate(): result["action"] = "REGENERATE"
    def on_reinit(): result["action"] = "REINIT_ELECTIONS"
    def on_fw_update(): result["action"] = "FIRMWARE_UPDATE"
    def on_reset_pwd(): result["action"] = "RESET_PASSWORD"
    def on_exit(): result["action"] = "EXIT"

    _styled_button(btn_frame, "RE-INITIALIZE ELECTIONS", on_reinit, bg=ERROR_COLOR).pack(pady=5, fill="x")
    _styled_button(btn_frame, "FIRMWARE UPDATE", on_fw_update, bg=WARNING_COLOR).pack(pady=5, fill="x")
    _styled_button(btn_frame, "SET ALLOWED BMDS", on_set_bmds, bg=ACCENT_COLOR).pack(pady=5, fill="x")
    _styled_button(btn_frame, "CUSTOM READER", lambda: result.update({"action": "CUSTOM_READER"}), bg=ACCENT_COLOR).pack(pady=5, fill="x")
    _styled_button(btn_frame, "REGENERATE TOKEN", on_regenerate, bg=WARNING_COLOR).pack(pady=5, fill="x")
    _styled_button(btn_frame, "RESET PASSWORD", on_reset_pwd, bg=FG_SECONDARY).pack(pady=5, fill="x")
    _styled_button(btn_frame, "EXIT ADMIN MENU", on_exit, bg=FG_SECONDARY).pack(pady=10, fill="x")

    import time
    while result["action"] is None and not app.exit_requested:
        app.root.update()
        time.sleep(0.05)

    return result["action"]

# ---------------- SET BMDS ---------------- #

def set_bmds_screen(app, num_booths, current_allowed):
    app.clear()
    result = {"done": False}
    # Create a copy to edit
    temp_allowed = list(current_allowed)
    
    frame = _center_frame(app)

    tk.Label(frame, text="SET ALLOWED BMDs",
             fg=ACCENT_COLOR, bg=BG_COLOR, font=("Segoe UI", 24, "bold")).pack(pady=(10, 20))

    bmds_frame = tk.Frame(frame, bg=BG_COLOR)
    bmds_frame.pack(pady=10)

    # We will need references to the buttons to update their colors
    btn_refs = {}

    def toggle_bmd(b):
        if b in temp_allowed:
            # Prevent removing the last allowed BMD
            if len(temp_allowed) > 1:
                temp_allowed.remove(b)
        else:
            temp_allowed.append(b)
        update_btn(b)

    def update_btn(b):
        is_allowed = b in temp_allowed
        text = f"BMD {b}\n\nALLOWED" if is_allowed else f"BMD {b}\n\nDEACTIVATED"
        bg = SUCCESS_COLOR if is_allowed else ERROR_COLOR
        btn_refs[b].config(text=text, bg=bg)

    for i in range(1, num_booths + 1):
        # Place them in a grid or row
        b_btn = tk.Button(
            bmds_frame, font=("Segoe UI", 16, "bold"),
            command=lambda b=i: toggle_bmd(b),
            fg="white", activeforeground="white",
            relief="flat", width=12, height=4, cursor="hand2"
        )
        b_btn.pack(side="left", padx=10, pady=10)
        btn_refs[i] = b_btn
        update_btn(i)

    def on_done():
        result["done"] = True

    _styled_button(frame, "SAVE & RETURN", on_done, bg=FG_SECONDARY).pack(pady=30)

    import time
    while not result["done"] and not app.exit_requested:
        app.root.update()
        time.sleep(0.05)

    return temp_allowed

# ---------------- REGENERATE PROMPT ---------------- #

def regenerate_prompt_screen(app):
    app.clear()
    result = {"value": None, "cancelled": False}

    frame = _center_frame(app)

    tk.Label(frame, text="REGENERATE TOKEN",
             fg=WARNING_COLOR, bg=BG_COLOR, font=("Segoe UI", 24, "bold")).pack(pady=(0, 5))

    tk.Label(frame, text="Enter Voter Entry Number:",
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

    def cancel():
        result["cancelled"] = True

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

    KEY_BG = "#FFFFFF"
    KEY_FG = "#333333"
    KEY_ACTIVE_BG = "#E0E0E0"

    for row_idx, row_chars in enumerate(keys):
        row_frame = tk.Frame(kb_frame, bg=BG_COLOR)
        row_frame.pack(pady=1) 
        for char in row_chars:
            tk.Button(
                row_frame, text=char, font=("Segoe UI", 12, "bold"),
                width=4, height=1, 
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

    btn_frame = tk.Frame(frame, bg=BG_COLOR)
    btn_frame.pack(pady=10) 

    tk.Button(
        btn_frame, text="REGENERATE", font=FONT_MED,
        command=submit,
        bg=WARNING_COLOR, fg="white",
        activebackground=FG_SECONDARY, activeforeground="white",
        relief="flat", padx=20, pady=5, cursor="hand2"
    ).pack(side="left", padx=10)
    
    tk.Button(
        btn_frame, text="CANCEL", font=FONT_MED,
        command=cancel,
        bg=FG_SECONDARY, fg="white",
        activebackground=FG_SECONDARY, activeforeground="white",
        relief="flat", padx=20, pady=5, cursor="hand2"
    ).pack(side="left", padx=10)
    
    app.root.bind('<Return>', lambda e: submit())

    import time
    while result["value"] is None and not result["cancelled"] and not app.exit_requested:
        app.root.update()
        time.sleep(0.05)
    
    app.root.unbind('<Return>')
    return result["value"] if not result["cancelled"] else None

# ---------------- RESET PASSWORD ---------------- #

def reset_password_screen(app):
    app.clear()
    result = {"old": None, "new": None, "cancelled": False}

    frame = _center_frame(app)
    
    tk.Label(frame, text="RESET ADMIN PASSWORD",
             fg=WARNING_COLOR, bg=BG_COLOR, font=("Segoe UI", 24, "bold")).pack(pady=(0, 5))

    tk.Label(frame, text="Old Password:", fg=FG_COLOR, bg=BG_COLOR, font=("Segoe UI", 12)).pack()
    entry_old = tk.Entry(frame, font=("Segoe UI", 16), justify="center", show="*", width=18)
    entry_old.pack(pady=2, ipady=3)
    entry_old.focus()

    tk.Label(frame, text="New Password:", fg=FG_COLOR, bg=BG_COLOR, font=("Segoe UI", 12)).pack()
    entry_new = tk.Entry(frame, font=("Segoe UI", 16), justify="center", show="*", width=18)
    entry_new.pack(pady=2, ipady=3)

    # Active Entry tracking for keyboard
    active_entry = [entry_old]
    def set_active(e): active_entry[0] = e.widget
    entry_old.bind("<FocusIn>", set_active)
    entry_new.bind("<FocusIn>", set_active)

    def submit():
        o = entry_old.get().strip()
        n = entry_new.get().strip()
        if o and n:
            result["old"] = o
            result["new"] = n

    def cancel():
        result["cancelled"] = True

    kb_frame = tk.Frame(frame, bg=BG_COLOR)
    kb_frame.pack(pady=5)

    def on_key(char):
        curr_entry = active_entry[0]
        if char == "⌫":
            current = curr_entry.get()
            curr_entry.delete(len(current)-1, tk.END)
        else:
            curr_entry.insert(tk.END, char)

    keys = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm", "-_@."]
    KEY_BG = "#FFFFFF"
    KEY_FG = "#333333"
    
    for row_chars in keys:
        row_frame = tk.Frame(kb_frame, bg=BG_COLOR)
        row_frame.pack(pady=1) 
        for char in row_chars:
            tk.Button(row_frame, text=char, font=FONT_SMALL, width=3, bg=KEY_BG, fg=KEY_FG,
                      command=lambda c=char: on_key(c)).pack(side="left", padx=1, pady=1)

    # Backspace
    last_row = kb_frame.winfo_children()[-1]
    tk.Button(last_row, text="⌫", font=FONT_SMALL, width=3, bg="#ffcccc", fg="#cc0000",
              command=lambda: on_key("⌫")).pack(side="left", padx=1, pady=1)

    btn_frame = tk.Frame(frame, bg=BG_COLOR)
    btn_frame.pack(pady=5)
    _styled_button(btn_frame, "CONFIRM", submit, bg=SUCCESS_COLOR).pack(side="left", padx=5)
    _styled_button(btn_frame, "CANCEL", cancel, bg=ERROR_COLOR).pack(side="left", padx=5)

    import time
    while result["old"] is None and not result["cancelled"] and not app.exit_requested:
        app.root.update()
        time.sleep(0.05)
    
    return (result["old"], result["new"]) if not result["cancelled"] else (None, None)

# ---------------- CONFIRM ACTION ---------------- #

def confirm_action_screen(app, title, message):
    app.clear()
    result = {"confirmed": None}
    frame = _center_frame(app)

    tk.Label(frame, text=title, fg=WARNING_COLOR, bg=BG_COLOR, font=FONT_LARGE).pack(pady=20)
    tk.Label(frame, text=message, fg=FG_COLOR, bg=BG_COLOR, font=FONT_MED, justify="center").pack(pady=20)

    btn_frame = tk.Frame(frame, bg=BG_COLOR)
    btn_frame.pack(pady=30)

    def on_yes(): result["confirmed"] = True
    def on_no(): result["confirmed"] = False

    _styled_button(btn_frame, "YES, PROCEED", on_yes, bg=ERROR_COLOR).pack(side="left", padx=20)
    _styled_button(btn_frame, "NO, CANCEL", on_no, bg=FG_COLOR).pack(side="left", padx=20)

    import time
    while result["confirmed"] is None and not app.exit_requested:
        app.root.update()
        time.sleep(0.05)

    return result["confirmed"]

# ---------------- TIME WINDOW ENDED ---------------- #

def time_window_ended_screen(app):
    app.clear()
    result = {"action": None}

    frame = _center_frame(app)
    
    tk.Label(frame, text="ELECTION TIME ENDED", fg=ERROR_COLOR, bg=BG_COLOR, font=FONT_LARGE).pack(pady=(0, 20))
    tk.Label(frame, text="The designated time window for this election has closed.\nTokens can no longer be generated.", fg=FG_COLOR, bg=BG_COLOR, font=FONT_MED, justify="center").pack(pady=10)

    btn_frame = tk.Frame(frame, bg=BG_COLOR)
    btn_frame.pack(pady=30)
    
    def on_samurai(): result["action"] = "SAMURAI_UNLOCK"

    _styled_button(btn_frame, "ADMIN ACCESS", on_samurai, bg=WARNING_COLOR).pack(pady=10)

    import time
    while result["action"] is None and not app.exit_requested:
        app.root.update()
        time.sleep(0.05)

    if result["action"] == "SAMURAI_UNLOCK":
        # Prompt for password from admins 
        pwd = password_prompt_screen(app)
        # Verify pwd upstream, but we will return what they want to do
        app.clear()
        f2 = _center_frame(app)
        tk.Label(f2, text="ADMIN OVERRIDE", fg=ACCENT_COLOR, bg=BG_COLOR, font=FONT_LARGE).pack(pady=20)
        bf = tk.Frame(f2, bg=BG_COLOR)
        bf.pack(pady=20)
        
        inner_res = {"choice": None}
        def ch_ext(): inner_res["choice"] = "EXTEND_ELECTION"
        def ch_end(): inner_res["choice"] = "END_ELECTION"
        def ch_cancel(): inner_res["choice"] = "CANCEL"
        
        _styled_button(bf, "EXTEND ELECTION", ch_ext, bg=SUCCESS_COLOR).pack(side="left", padx=10)
        _styled_button(bf, "END ELECTION", ch_end, bg=ERROR_COLOR).pack(side="left", padx=10)
        _styled_button(bf, "CANCEL", ch_cancel, bg=FG_SECONDARY).pack(side="left", padx=10)
        
        while inner_res["choice"] is None and not app.exit_requested:
            app.root.update()
            time.sleep(0.05)
            
        return inner_res["choice"], pwd

    return None, None

# ---------------- CUSTOM RFID READER ---------------- #

def custom_rfid_reader_screen(app):
    app.clear()
    
    # We use a container that allows the scrollable log and results
    frame = tk.Frame(app.container, bg=BG_COLOR)
    frame.place(relheight=1, relwidth=1)

    tk.Label(frame, text="CUSTOM RFID READER",
             fg=ACCENT_COLOR, bg=BG_COLOR, font=("Segoe UI", 24, "bold")).pack(pady=(10, 5))

    # Log/Status Area
    log_frame = tk.Frame(frame, bg="#1e1e1e", bd=2, relief="sunken")
    log_frame.pack(fill="both", expand=True, padx=20, pady=5)

    log_text = tk.Text(log_frame, bg="#1e1e1e", fg="#33ff33", font=("Consolas", 10),
                      state="disabled", wrap="word", height=10)
    log_text.pack(side="left", fill="both", expand=True)

    scrollbar = tk.Scrollbar(log_frame, command=log_text.yview)
    scrollbar.pack(side="right", fill="y")
    log_text.config(yscrollcommand=scrollbar.set)

    def write_log(msg):
        log_text.config(state="normal")
        log_text.insert(tk.END, msg + "\n")
        log_text.see(tk.END)
        log_text.config(state="disabled")
        app.root.update()

    # Result Area
    result_label = tk.Label(frame, text="RESULT STRING:", fg=FG_SECONDARY, bg=BG_COLOR, font=("Segoe UI", 10, "bold"))
    result_label.pack(pady=(10, 0))

    result_box = tk.Text(frame, bg="#ffffff", fg="#000000", font=("Segoe UI", 10),
                        height=4, wrap="char")
    result_box.pack(fill="x", padx=20, pady=5)
    result_box.config(state="disabled")

    def show_result(text):
        result_box.config(state="normal")
        result_box.delete("1.0", tk.END)
        result_box.insert(tk.END, text)
        result_box.config(state="disabled")
        app.root.update()

    # Controls
    btn_frame = tk.Frame(frame, bg=BG_COLOR)
    btn_frame.pack(pady=10)

    exit_requested = [False]
    def on_exit(): exit_requested[0] = True

    _styled_button(btn_frame, "EXIT READER", on_exit, bg=FG_SECONDARY).pack()

    return write_log, show_result, lambda: exit_requested[0]
