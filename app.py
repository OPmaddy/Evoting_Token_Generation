import os
import json
import numpy as np

from ui.base import FullscreenApp
import argparse
import csv
import datetime
from ui.screens import (
    entry_number_screen,
    status_screen,
    already_generated_screen,
    verification_progress_screen,
    rfid_status_screen,
    booth_confirmation_screen
)

from logic.voter import VoterDB
from logic.face import run_face_verification
from logic.token import (
    assign_booth,
    build_token_payload,
    encrypt_payload
)

try:
    from hardware.camera import Camera
except ImportError:
    print("Warning: Picamera2 not found. Using OpenCV Mock Camera instead.")
    import cv2
    class Camera:
        def __init__(self):
            self.cap = cv2.VideoCapture(0)
        def start(self):
            pass
        def stop(self):
            self.cap.release()
        def close(self):
            self.cap.release()
        def capture_frame(self):
            ret, frame = self.cap.read()
            if ret:
                return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return None

# Set to True when testing without actual RFID hardware (e.g., Windows dev)
MOCK_RFID = False
if not MOCK_RFID:
    from hardware.rfid_writer import RFIDTokenWriter

EMBEDDINGS_DIR = "./embeddings"
DUMP_DIR = "./dumped_images"
os.makedirs(DUMP_DIR, exist_ok=True)

def main():
    parser = argparse.ArgumentParser(description="EVoting Token Generation")
    parser.add_argument('--debug', action='store_true', help="Run in benchmarking mode (Face Verification only)")
    args = parser.parse_args()
    
    IS_DEBUG = args.debug

    if IS_DEBUG:
        print("Running in DEBUG (Benchmarking) Mode. Bypassing Electoral Roll and Token Saving.")

    app = FullscreenApp()
    voter_db = VoterDB()
    
    # Load Booth Public Keys
    bmd_keys_path = "bmd_keys.json"
    if os.path.exists(bmd_keys_path):
        with open(bmd_keys_path, "r") as f:
            bmd_keys_data = json.load(f)
        num_booths = bmd_keys_data.get("num_booths", 2)
        booth_keys = bmd_keys_data.get("keys", {})
    else:
        print("Warning: bmd_keys.json not found. Token encryption may fail.")
        num_booths = 2
        booth_keys = {}

    def log_benchmark(entry, attempt, success, label=""):
        try:
            with open("benchmark_results.csv", "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([datetime.datetime.now().isoformat(), entry, attempt, success, label])
        except Exception as e:
            print(f"Failed to log benchmark: {e}")

    def label_benchmark(entry, attempt, success):
        # Build custom UI for labelling
        app.clear()
        import tkinter as tk
        from ui.styles import BG_COLOR, FG_COLOR, ACCENT_COLOR, ERROR_COLOR, FONT_LARGE, FONT_MED
        
        frame = tk.Frame(app.container, bg=BG_COLOR)
        frame.place(relx=0.5, rely=0.5, anchor="center")
        
        title_text = "LABEL FALSE POSITIVE?" if success else "LABEL FALSE NEGATIVE?"
        desc_text = "Was this person NOT who they claimed to be?" if success else "Was this person ACTUALLY who they claimed to be?"
        
        tk.Label(frame, text=title_text, fg=FG_COLOR, bg=BG_COLOR, font=FONT_LARGE).pack(pady=20)
        tk.Label(frame, text=desc_text, fg=FG_COLOR, bg=BG_COLOR, font=FONT_MED).pack(pady=10)
        
        btn_frame = tk.Frame(frame, bg=BG_COLOR)
        btn_frame.pack(pady=30)
        
        choice = {"label": None}
        def on_yes(): choice["label"] = "Yes"
        def on_no(): choice["label"] = "No"
        
        tk.Button(btn_frame, text="YES", command=on_yes, font=FONT_MED, bg=ERROR_COLOR if success else ACCENT_COLOR, fg="white", padx=20, pady=10, cursor="hand2").pack(side="left", padx=20)
        tk.Button(btn_frame, text="NO", command=on_no, font=FONT_MED, bg=ACCENT_COLOR if success else ERROR_COLOR, fg="white", padx=20, pady=10, cursor="hand2").pack(side="left", padx=20)
        
        import time
        while choice["label"] is None and not app.exit_requested:
            app.root.update()
            time.sleep(0.05)
            
        log_benchmark(entry, attempt, success, label=choice.get("label", "Unknown"))
        flow()

    def flow():
        if app.exit_requested:
            app.root.destroy()
            return

        entry = entry_number_screen(app)
        if not entry:
            app.root.after(10, flow)
            return

        voter = voter_db.get_voter(entry)
        
        if not IS_DEBUG:
            if voter is None:
                status_screen(app, "ENTRY NOT FOUND", 
                              "The Entry Number provided was not found in the Electoral Roll.\nPlease verify the number and try again.", 
                              fg="red", on_done=flow)
                return

            if voter_db.has_token(voter):
                already_generated_screen(app, voter, on_done=flow)
                return
        else:
            # Provide mock voter object for face checking flow
            if voter is None:
               voter = {"Entry_Number": entry, "EID_Vector": "E1"} 

        # ---- FACE VERIFICATION ----
        emb_path = os.path.join(EMBEDDINGS_DIR, f"{entry}.npy")
        if not os.path.exists(emb_path):
            # Fallback for demo purposes
            emb_path = os.path.join(EMBEDDINGS_DIR, "madhav.npy")
            
        if not os.path.exists(emb_path):
            status_screen(
                app,
                "SYSTEM ERROR",
                "Biometric reference data is missing for this voter.\nPlease contact the System Administrator immediately.",
                fg="red",
                on_done=flow
            )
            return

        stored_embedding = np.load(emb_path)

        verification_progress_screen(
            app,
            "Please stand still and look directly at the camera.\nEnsure your face is unaffected by strong backlight."
        )
        app.root.update() # Force UI to render before blocking

        cam = Camera()
        cam.start()

        max_attempts = 3
        attempt = 0
        success = False
        images = []

        while attempt < max_attempts and not success:
            attempt += 1
            success, images = run_face_verification(
                camera=cam,
                stored_embedding=stored_embedding,
                dump_dir=DUMP_DIR,
                entry_number=entry
            )
            
            if not success and attempt < max_attempts:
                # Ask user if they want to retry or exit
                app.clear()
                import tkinter as tk
                from ui.styles import BG_COLOR, FG_COLOR, ACCENT_COLOR, ERROR_COLOR, FONT_LARGE, FONT_MED
                
                frame = tk.Frame(app.container, bg=BG_COLOR)
                frame.place(relx=0.5, rely=0.5, anchor="center")
                
                tk.Label(frame, text="VERIFICATION FAILED", fg=ERROR_COLOR, bg=BG_COLOR, font=FONT_LARGE).pack(pady=20)
                tk.Label(frame, text=f"Attempt {attempt}/{max_attempts} failed.\nWould you like to retry or exit?", fg=FG_COLOR, bg=BG_COLOR, font=FONT_MED, justify="center").pack(pady=10)
                
                btn_frame = tk.Frame(frame, bg=BG_COLOR)
                btn_frame.pack(pady=30)
                
                choice = {"action": None}
                def on_retry(): choice["action"] = "retry"
                def on_exit(): choice["action"] = "exit"
                
                tk.Button(btn_frame, text="RETRY", command=on_retry, font=FONT_MED, bg=ACCENT_COLOR, fg="white", padx=20, pady=10, cursor="hand2").pack(side="left", padx=20)
                tk.Button(btn_frame, text="EXIT", command=on_exit, font=FONT_MED, bg=FG_COLOR, fg="white", padx=20, pady=10, cursor="hand2").pack(side="left", padx=20)
                
                import time
                start_time = time.time()
                while choice["action"] is None and not app.exit_requested:
                    app.root.update()
                    if time.time() - start_time >= 1.0:
                        choice["action"] = "retry"
                    
                if choice["action"] == "exit" or app.exit_requested:
                    break
                
        cam.stop()
        if hasattr(cam, 'close'):
            cam.close()

        if not success:
            if IS_DEBUG:
                label_benchmark(entry, attempt, False)
                return

            status_screen(
                app,
                "VERIFICATION FAILED",
                "Biometric verification was unsuccessful.\nPlease try again or contact the Polling Officer.",
                fg="red",
                on_done=flow
            )
            return

        if IS_DEBUG:
            label_benchmark(entry, attempt, True)
            return

        status_screen(
            app,
            "IDENTITY CONFIRMED",
            "Biometric verification successful.\nProceeding to token generation...",
            fg="green",
            delay=2000,
            on_done=lambda: finalize(entry, voter, images)
        )
    def finalize(entry, voter, images):
        booth = assign_booth(entry, voter["EID_Vector"], num_booths)
        payload = build_token_payload(entry, voter["EID_Vector"], booth)
        
        booth_str = str(booth)
        if booth_str not in booth_keys:
            status_screen(app, "SYSTEM ERROR", 
                          f"Public key for Booth {booth} not found.\nPlease contact Administrator.",
                          fg="red", on_done=flow)
            return
            
        public_key_pem = booth_keys[booth_str]
        encrypted = encrypt_payload(payload, public_key_pem)

        def rfid_cb(msg):
            rfid_status_screen(app, msg)

        max_rfid_attempts = 5
        rfid_attempt = 0
        write_success = False

        while rfid_attempt < max_rfid_attempts and not write_success:
            rfid_attempt += 1

            if MOCK_RFID:
                import time
                rfid_cb("Status: Mocking RFID detection...")
                app.root.update()
                time.sleep(0.5)
                
                # Write to file
                try:
                    with open("mock_rfid.txt", "w") as f:
                        f.write(encrypted)
                    rfid_cb("Status: Mocking RFID Write... Success")
                    write_success = True
                except Exception as e:
                    rfid_cb(f"Status: Mocking RFID Write... Failed: {e}")
                    write_success = False
                    
                app.root.update()
                time.sleep(1.0)
            else:
                writer = RFIDTokenWriter(start_block=4)
                write_success = writer.write_token(encrypted, status_cb=rfid_cb)

            if not write_success and rfid_attempt < max_rfid_attempts:
                # Ask user if they want to retry or exit
                app.clear()
                import tkinter as tk
                from ui.styles import BG_COLOR, FG_COLOR, ACCENT_COLOR, ERROR_COLOR, FONT_LARGE, FONT_MED
                
                frame = tk.Frame(app.container, bg=BG_COLOR)
                frame.place(relx=0.5, rely=0.5, anchor="center")
                
                tk.Label(frame, text="WRITE FAILED", fg=ERROR_COLOR, bg=BG_COLOR, font=FONT_LARGE).pack(pady=20)
                tk.Label(frame, text=f"Attempt {rfid_attempt}/{max_rfid_attempts} failed.\nWould you like to retry or exit?", fg=FG_COLOR, bg=BG_COLOR, font=FONT_MED, justify="center").pack(pady=10)
                
                btn_frame = tk.Frame(frame, bg=BG_COLOR)
                btn_frame.pack(pady=30)
                
                choice = {"action": None}
                def on_retry(): choice["action"] = "retry"
                def on_exit(): choice["action"] = "exit"
                
                tk.Button(btn_frame, text="RETRY", command=on_retry, font=FONT_MED, bg=ACCENT_COLOR, fg="white", padx=20, pady=10, cursor="hand2").pack(side="left", padx=20)
                tk.Button(btn_frame, text="EXIT", command=on_exit, font=FONT_MED, bg=FG_COLOR, fg="white", padx=20, pady=10, cursor="hand2").pack(side="left", padx=20)
                
                import time
                start_time = time.time()
                while choice["action"] is None and not app.exit_requested:
                    app.root.update()
                    if time.time() - start_time >= 1.0:
                        choice["action"] = "retry"
                    
                if choice["action"] == "exit" or app.exit_requested:
                    break

        if not write_success:
            status_screen(app, "CARD ERROR",
                          "Failed to write voting token to the Smart Card.\nPlease retry or replace the card.", 
                          fg="red", on_done=flow)
            return

        voter_db.stage_token(
            entry_number=entry,
            token_id=payload["token_id"],
            issued_at=payload["issued_at"],
            img1=images[0] if len(images) > 0 else None,
            img2=images[1] if len(images) > 1 else None,
            booth=booth
        )

        booth_confirmation_screen(app, booth, on_done=flow)

    app.root.after(100, flow)
    app.root.mainloop()



if __name__ == "__main__":
    main()
