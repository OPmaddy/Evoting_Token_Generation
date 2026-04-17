import os
import sys
import json

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
    booth_confirmation_screen,
    voter_confirmation_screen,
    password_prompt_screen,
    admin_dashboard_screen,
    set_bmds_screen,
    regenerate_prompt_screen,
    reset_password_screen,
    confirm_action_screen,
    time_window_ended_screen
)
import subprocess
import requests
import zipfile
import base64
import shutil
import io

from logic.voter import VoterDB
from logic.token import (
    assign_booth,
    build_token_payload,
    encrypt_payload
)

# --- Early bypass-face detection (before importing heavy face libraries) ---
_BYPASS_FACE_EARLY = '--bypass-face' in sys.argv
_MOCK_RFID_EARLY = '--mock-rfid' in sys.argv

if not _BYPASS_FACE_EARLY:
    import numpy as np
    from logic.face import run_face_verification

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
else:
    print("[bypass-face] Skipping face verification library imports.")

# Set to True when testing without actual RFID hardware (e.g., Windows dev)
MOCK_RFID = _MOCK_RFID_EARLY
if not MOCK_RFID:
    from hardware.rfid_writer import RFIDTokenWriter

EMBEDDINGS_DIR = "./embeddings"
DUMP_DIR = "./dumped_images"
os.makedirs(DUMP_DIR, exist_ok=True)

def main():
    parser = argparse.ArgumentParser(description="EVoting Token Generation")
    parser.add_argument('--debug', action='store_true', help="Run in benchmarking mode (Face Verification only)")
    parser.add_argument('--bypass-face', action='store_true', help="Skip face verification and jump straight to token generation")
    parser.add_argument('--mock-rfid', action='store_true', help="Bypass actual RFID hardware and write to mock_rfid.txt")
    args = parser.parse_args()
    
    IS_DEBUG = args.debug
    BYPASS_FACE = args.bypass_face

    if IS_DEBUG:
        print("Running in DEBUG (Benchmarking) Mode. Bypassing Electoral Roll and Token Saving.")

    app = FullscreenApp()
    
    # Load Allowed BMDs from disk
    allowed_bmds_path = "allowed_bmds.json"
    if os.path.exists(allowed_bmds_path):
        try:
            with open(allowed_bmds_path, "r") as f:
                app.allowed_bmds = json.load(f).get("allowed", [1])
        except Exception as e:
            print(f"Warning: Failed to load allowed_bmds.json: {e}")
            app.allowed_bmds = [1]
    else:
        app.allowed_bmds = [1]
        
    app.voter_db = VoterDB()
    
    # Load Booth Public Keys
    bmd_keys_path = "bmd_keys.json"
    if os.path.exists(bmd_keys_path):
        with open(bmd_keys_path, "r") as f:
            bk_data = json.load(f)
        app.num_booths = bk_data.get("num_booths", 2)
        app.booth_keys = bk_data.get("keys", {})
    else:
        app.num_booths = 2
        app.booth_keys = {}
        print("Warning: bmd_keys.json not found. Token encryption may fail.")

    # Load Device ID
    app.device_id = "1"
    if os.path.exists("device_id.txt"):
        with open("device_id.txt", "r") as f:
            app.device_id = f.read().strip()
            
    # Load Election End Time
    app.election_end_time = None
    if os.path.exists("election_end_time.txt"):
        with open("election_end_time.txt", "r") as f:
            try:
                # Use .replace(tzinfo=None) to ensure naive datetime for simple comparison
                app.election_end_time = datetime.datetime.fromisoformat(f.read().strip()).replace(tzinfo=None)
            except:
                pass
                
    # Sync Time (Admin requires Sudo process)
    try:
        print("Attempting to sync time via NTP from Google...")
        # Use a single string for shell=True to allow bash-style $() substitution
        cmd = 'sudo date -s "$(wget -qSO- --max-redirect=0 google.com 2>&1 | grep Date: | cut -d\' \' -f5-8)Z"'
        subprocess.run(cmd, shell=True, timeout=10)
    except Exception as e:
        print(f"Time sync failed: {e}")

    def reboot_system():
        """Ensure disk is synced and reboot the system."""
        print("Syncing disks and rebooting...")
        subprocess.run(["sync"])
        subprocess.run(["sudo", "reboot"])

    def _send_logs_to_server(app):
        """Zip the logs directory and send it to the server."""
        try:
            if not os.path.exists("logs"):
                print("No logs directory found to send.")
                return False

            # Create a zip in memory
            memory_file = io.BytesIO()
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk("logs"):
                    for file in files:
                        zf.write(os.path.join(root, file))
            memory_file.seek(0)

            # Use voter_db's session if available, or create new one
            # Note: voter_db is defined in main() closure, but we can pass it or access via app
            # For simplicity, we'll try to use the session with certs
            
            from client_config import SERVER_URL, DEVICE_ID, CLIENT_CERT, CLIENT_KEY, CA_CERT, DISABLE_TLS
            
            session = requests.Session()
            if not DISABLE_TLS and os.path.exists(CLIENT_CERT):
                session.cert = (CLIENT_CERT, CLIENT_KEY)
                if os.path.exists(CA_CERT):
                    session.verify = CA_CERT
            elif DISABLE_TLS:
                session.verify = False

            url = f"{SERVER_URL.rstrip('/')}/api/device/{app.device_id}/logs"
            files = {'log': (f"logs_device_{app.device_id}.zip", memory_file, 'application/zip')}
            
            resp = session.post(url, files=files, timeout=30)
            if resp.status_code == 200:
                print("Logs successfully sent to server.")
                return True
            else:
                print(f"Failed to send logs: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            print(f"Error sending logs: {e}")
            return False

    def _fetch_reinit_config(app):
        """Fetch full configuration and certificates from server and apply them."""
        try:
            from client_config import (
                SERVER_URL, DEVICE_ID, CLIENT_CERT, CLIENT_KEY, CA_CERT, 
                DISABLE_TLS, MASTER_CERT, MASTER_KEY, MASTER_CA
            )
            
            session = requests.Session()
            
            def attempt_request(use_master=False):
                if not DISABLE_TLS:
                    if use_master:
                        if os.path.exists(MASTER_CERT) and os.path.exists(MASTER_KEY):
                            session.cert = (MASTER_CERT, MASTER_KEY)
                            session.verify = MASTER_CA if os.path.exists(MASTER_CA) else True
                        else:
                            return None, "Master certificates missing"
                    else:
                        if os.path.exists(CLIENT_CERT) and os.path.exists(CLIENT_KEY):
                            session.cert = (CLIENT_CERT, CLIENT_KEY)
                            session.verify = CA_CERT if os.path.exists(CA_CERT) else True
                        else:
                            return attempt_request(use_master=True)
                else:
                    session.verify = False

                url = f"{SERVER_URL.rstrip('/')}/api/device/{app.device_id}/reinit"
                try:
                    return session.get(url, timeout=30), None
                except Exception as e:
                    return None, str(e)

            # Execution
            resp, error = attempt_request(use_master=False)
            
            # If failed with election cert, retry with master
            if error or (resp and resp.status_code in (403, 401)):
                print(f"Provisioning with election certs failed ({error or resp.status_code}), falling back to Master...")
                resp, error = attempt_request(use_master=True)

            if error or not resp or resp.status_code != 200:
                print(f"Failed to fetch reinit config: {error or (resp.status_code if resp else 'No response')} {resp.text if resp else ''}")
                return False
                
            data = resp.json()
            if data.get("status") != "success":
                return False
                
            config = data.get("config", {})
            certs = data.get("certificates", {})
            
            # 1. Update Certificates (if they changed)
            # CAUTION: Overwriting current certs might be risky if network fails mid-write
            # But the requirement is to refetch them.
            os.makedirs("certs", exist_ok=True)
            if certs.get("ca_crt"):
                with open(os.path.join("certs", "ca.crt"), "w") as f: f.write(certs["ca_crt"])
            if certs.get("device_crt"):
                with open(os.path.join("certs", f"device_{app.device_id}.crt"), "w") as f: f.write(certs["device_crt"])
            if certs.get("device_key"):
                with open(os.path.join("certs", f"device_{app.device_id}.key"), "w") as f: f.write(certs["device_key"])
                
            # 2. Update allowed_bmds.json
            with open("allowed_bmds.json", "w") as f:
                json.dump({"allowed": config.get("allowed_bmds", [1])}, f)
            app.allowed_bmds = config.get("allowed_bmds", [1])
                
            # 3. Update bmd_keys.json
            with open("bmd_keys.json", "w") as f:
                json.dump(config.get("bmd_keys", {}), f)
                
            # 4. Update Electoral_Roll.csv
            e_roll_b64 = config.get("electoral_roll_b64")
            if e_roll_b64:
                with open("Electoral_Roll.csv", "wb") as f:
                    f.write(base64.b64decode(e_roll_b64))
                    
            # 5. Update election_end_time.txt
            end_time_str = config.get("election_end_time")
            if end_time_str:
                with open("election_end_time.txt", "w") as f:
                    f.write(end_time_str)
                try:
                    # Strip timezone info for naive comparison
                    app.election_end_time = datetime.datetime.fromisoformat(end_time_str).replace(tzinfo=None)
                except:
                    pass
            
            return True
        except Exception as e:
            print(f"Error fetching reinit config: {e}")
            return False

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

    def flow(regenerate_entry=None):
        if app.exit_requested:
            app.root.destroy()
            return

        # Check Time Window before anything
        admin_override = False
        if app.election_end_time and datetime.datetime.now() > app.election_end_time:
            choice, pwd = time_window_ended_screen(app)
            if choice == "EXTEND_ELECTION":
                # Verify pwd
                admin_pwd = "admin"
                if os.path.exists("admin_sec.json"):
                    with open("admin_sec.json", "r") as f:
                        admin_pwd = json.load(f).get("pwd", "admin")
                if pwd == admin_pwd:
                    # Extend by clearing the end time for now locally, or you could add 1 hour
                    app.election_end_time = datetime.datetime.now() + datetime.timedelta(hours=2)
                    try:
                        with open("election_end_time.txt", "w") as f:
                            f.write(app.election_end_time.isoformat())
                    except:
                        pass
                else:
                    status_screen(app, "ACCESS DENIED", "Incorrect password", fg="red", delay=2000, on_done=flow)
                    return
            elif choice == "END_ELECTION":
                admin_pwd = "admin"
                if os.path.exists("admin_sec.json"):
                    with open("admin_sec.json", "r") as f:
                        admin_pwd = json.load(f).get("pwd", "admin")
                if pwd == admin_pwd:
                    status_screen(app, "ENDING ELECTION", "Packaging and sending logs to server...", fg="orange")
                    app.root.update()
                    # Trigger end election log send
                    _send_logs_to_server(app)
                    status_screen(app, "ELECTION ENDED", "Logs transferred. System locked.", fg="green")
                    app.root.update()
                    import time; time.sleep(4)
                    return
                else:
                    status_screen(app, "ACCESS DENIED", "Incorrect password", fg="red", delay=2000, on_done=flow)
                    return
            else:
                app.root.after(10, flow)
                return

        if regenerate_entry:
            entry = regenerate_entry
        else:
            entry = entry_number_screen(app, mock_rfid=MOCK_RFID)
            if not entry:
                app.root.after(10, flow)
                return

        if not regenerate_entry and entry.strip().upper() == "SAMURAI":
            pwd = password_prompt_screen(app)
            
            admin_pwd = "admin"
            if os.path.exists("admin_sec.json"):
                with open("admin_sec.json", "r") as f:
                    admin_pwd = json.load(f).get("pwd", "admin")
                    
            if pwd == admin_pwd: 
                while True:
                    action = admin_dashboard_screen(app)
                    if action == "EXIT":
                        app.root.after(10, flow)
                        return
                    elif action == "RESET":
                        status_screen(app, "RESETTING SYSTEM", "Rotating logs and fetching new electoral roll...", fg="orange")
                        app.root.update()
                        success, msg = app.voter_db.rotate_files_and_reinitialize()
                        if success:
                            status_screen(app, "RESET SUCCESSFUL", msg + "\nRebooting...", fg="green", delay=3000, on_done=reboot_system)
                        else:
                            status_screen(app, "RESET FAILED", msg, fg="red", delay=4000, on_done=flow)
                        return
                    elif action == "SET_BMDS":
                        app.allowed_bmds = set_bmds_screen(app, app.num_booths, app.allowed_bmds)
                        try:
                            with open("allowed_bmds.json", "w") as f:
                                json.dump({"allowed": app.allowed_bmds}, f)
                        except Exception as e:
                            print(f"Failed to save allowed BMDs: {e}")
                    elif action == "REGENERATE":
                        target_entry = regenerate_prompt_screen(app)
                        if target_entry:
                            app.root.after(10, lambda: flow(regenerate_entry=target_entry))
                            return
                    elif action == "FIRMWARE_UPDATE":
                        status_screen(app, "UPDATING FIRMWARE", "Pulling latest code...", fg="orange")
                        app.root.update()
                        try:
                            # Stash any local changes to ensure pull succeeds
                            subprocess.run(["git", "stash"], cwd=os.path.dirname(__file__))
                            subprocess.run(["git", "pull"], check=True, cwd=os.path.dirname(__file__))
                            status_screen(app, "UPDATE SUCCESS", "Code updated. System will reboot.", fg="green", delay=3000, on_done=reboot_system)
                        except Exception as e:
                            status_screen(app, "UPDATE FAILED", str(e), fg="red", delay=3000, on_done=flow)
                        return
                    elif action == "RESET_PASSWORD":
                        old, new = reset_password_screen(app)
                        if old == admin_pwd and new:
                            try:
                                with open("admin_sec.json", "w") as f:
                                    json.dump({"pwd": new}, f)
                                status_screen(app, "SUCCESS", "Password updated.", fg="green", delay=2000)
                            except:
                                status_screen(app, "ERROR", "Failed to save password.", fg="red", delay=2000)
                        elif old is not None:
                            status_screen(app, "ERROR", "Incorrect old password.", fg="red", delay=2000)
                    elif action == "REINIT_ELECTIONS":
                        c1 = confirm_action_screen(app, "RE-INITIALIZE ELECTIONS?", "WARNING: This will END the current election,\narchive all local databases and imagery,\nand wipe local state.\n\nAre you sure you want to proceed?")
                        if c1:
                            c2 = confirm_action_screen(app, "FINAL CONFIRMATION", "This action is strictly IRREVERSIBLE.\nLogs will be synced to the Server.\n\nProceed?")
                            if c2:
                                status_screen(app, "RE-INITIALIZING", "Sending logs to server...", fg="orange")
                                app.root.update()
                                _send_logs_to_server(app)
                                success, msg = app.voter_db.rotate_files_and_reinitialize() 
                                
                                status_screen(app, "RE-INITIALIZING", "Fetching remote configuration...", fg="orange")
                                app.root.update()
                                s_res = _fetch_reinit_config(app)
                                if s_res:
                                    # Refresh the VoterDB object to use new certs if they changed
                                    app.voter_db = VoterDB()
                                    
                                    # Refresh BMD keys and booth count
                                    if os.path.exists("bmd_keys.json"):
                                        with open("bmd_keys.json", "r") as f:
                                            _bk_data = json.load(f)
                                        app.num_booths = _bk_data.get("num_booths", 2)
                                        app.booth_keys = _bk_data.get("keys", {})
                                        
                                    status_screen(app, "SUCCESS", "Elections Re-Initialized.\nRebooting...", fg="green", delay=3000, on_done=reboot_system)
                                else:
                                    status_screen(app, "PARTIAL FAIL", "Archived local logs, but server fetch failed.", fg="red", delay=3000, on_done=flow)
                                return
            else:
                status_screen(app, "ACCESS DENIED", "Incorrect password", fg="red", delay=2000, on_done=flow)
            return
 
        voter = app.voter_db.get_voter_local(entry)
 
        if not IS_DEBUG:
            if voter is None:
                status_screen(app, "ENTRY NOT FOUND", 
                              "The Entry Number provided was not found in the Electoral Roll.\nPlease verify the number and try again.", 
                              fg="red", on_done=flow)
                return
        else:
            # Provide mock voter object for face checking flow
            if voter is None:
               voter = {"Entry_Number": entry, "EID_Vector": "E1", "Name": "Mock Debug Voter"} 
 
        # Immediate mandatory confirmation step using local info
        if not voter_confirmation_screen(app, voter):
            app.root.after(10, flow)
            return
 
        # Fetch remote status only after the user confirms their name
        status_screen(app, "VERIFYING STATUS", "Connecting to central server...\nPlease wait.", fg="white")
        app.root.update()
        
        voter = app.voter_db.sync_voter_remote(voter)
 
        if not IS_DEBUG:
            if not regenerate_entry and app.voter_db.has_token(voter):
                already_generated_screen(app, voter, on_done=flow)
                return
 
            # Check if another device is already processing this voter
            if app.voter_db.is_in_progress(voter):
                status_screen(app, "IN PROGRESS",
                              "This voter is currently being processed by another device.\nPlease wait or try a different voter.",
                              fg="orange", on_done=flow)
                return
 
            # Request permission from the central server to generate token
            req_ok, req_msg = app.voter_db.request_token(entry, regenerate=bool(regenerate_entry))
            if not req_ok:
                status_screen(app, "REQUEST DENIED",
                              f"Cannot generate token for this voter:\n{req_msg}",
                              fg="red", on_done=flow)
                return

        # ---- FACE VERIFICATION ----
        if BYPASS_FACE:
            print("Bypassing face verification...")
            app.root.after(0, lambda: finalize(entry, voter, []))
            return

        emb_path = os.path.join(EMBEDDINGS_DIR, f"{entry}.npy")
            
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

            # Release the lock on the central server so another device can try
            app.voter_db.cancel_token(entry)

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
        if not app.allowed_bmds:
            status_screen(app, "SYSTEM ERROR", "No BMDs are currently allowed.\nAdmin must configure BMDs.", fg="red", on_done=flow)
            return

        booth = assign_booth(entry, voter["EID_Vector"], app.allowed_bmds)
        payload = build_token_payload(entry, voter["EID_Vector"], booth)
        
        booth_str = str(booth)
        if booth_str not in app.booth_keys:
            status_screen(app, "SYSTEM ERROR", 
                          f"Public key for Booth {booth} not found.\nPlease contact Administrator.",
                          fg="red", on_done=flow)
            return
            
        public_key_pem = app.booth_keys[booth_str]
        encrypted = encrypt_payload(payload, public_key_pem)

        def rfid_cb(msg):
            rfid_status_screen(app, msg)

        max_rfid_attempts = 5
        rfid_attempt = 0
        write_success = False

        writer = None
        if not MOCK_RFID:
            try:
                writer = RFIDTokenWriter(start_block=4)
            except Exception as e:
                status_screen(app, "HARDWARE ERROR", f"RFID initialization failed: {e}", fg="red", on_done=flow)
                return

        try:
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
                # Release the lock on the central server
                app.voter_db.cancel_token(entry)

                status_screen(app, "CARD ERROR",
                              "Failed to write voting token to the Smart Card.\nPlease retry or replace the card.", 
                              fg="red", on_done=flow)
                return

            # Save full audit record to LOCAL SQLite (images, timestamps)
            app.voter_db.stage_token(
                entry_number=entry,
                token_id=payload["token_id"],
                issued_at=payload["issued_at"],
                img1=images[0] if len(images) > 0 else None,
                img2=images[1] if len(images) > 1 else None,
                booth=booth
            )

            # Notify central server that generation succeeded (sync)
            app.voter_db.confirm_token(
                entry_number=entry,
                token_id=payload["token_id"],
                booth=booth
            )

            booth_confirmation_screen(app, booth, on_done=flow)
        finally:
            if writer is not None:
                writer.close()

    app.root.after(100, flow)
    app.root.mainloop()



if __name__ == "__main__":
    main()
