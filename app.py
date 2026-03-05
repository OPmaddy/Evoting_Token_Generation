import os
import json
import numpy as np

from ui.base import FullscreenApp
from ui.screens import (
    entry_number_screen,
    status_screen,
    already_generated_screen,
    verification_progress_screen,
    rfid_status_screen,
    booth_confirmation_screen
)

from logic.voter import VoterDB
from hardware.camera import Camera
from logic.face import run_face_verification
from logic.token import (
    assign_booth,
    build_token_payload,
    encrypt_payload
)

# Set to True when testing without actual RFID hardware (e.g., Windows dev)
MOCK_RFID = True
if not MOCK_RFID:
    from hardware.rfid_writer import RFIDTokenWriter

EMBEDDINGS_DIR = "./embeddings"
DUMP_DIR = "./dumped_images"
os.makedirs(DUMP_DIR, exist_ok=True)

def main():
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

    def flow():
        if app.exit_requested:
            app.root.destroy()
            return

        entry = entry_number_screen(app)
        if not entry:
            app.root.after(10, flow)
            return

        voter = voter_db.get_voter(entry)
        if voter is None:
            status_screen(app, "ENTRY NOT FOUND", 
                          "The Entry Number provided was not found in the Electoral Roll.\nPlease verify the number and try again.", 
                          fg="red", on_done=flow)
            return

        if voter_db.has_token(voter):
            already_generated_screen(app, voter, on_done=flow)
            return

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
                # Optional: Show a brief retry message
                status_screen(
                    app,
                    "VERIFICATION RETRY",
                    f"Attempt {attempt} failed. Retrying ({attempt}/{max_attempts})...\nPlease align your face and blink when prompted.",
                    fg="orange",
                    delay=2000,
                    on_done=None # Blocking is fine here, or just update
                )
                app.root.update()
                
        cam.stop()
        if hasattr(cam, 'close'):
            cam.close()

        if not success:
            status_screen(
                app,
                "VERIFICATION FAILED",
                "Biometric verification was unsuccessful.\nPlease try again or contact the Polling Officer.",
                fg="red",
                on_done=flow
            )
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
            except Exception as e:
                rfid_cb(f"Status: Mocking RFID Write... Failed: {e}")
                
            app.root.update()
            time.sleep(1.0)
            write_success = True
        else:
            writer = RFIDTokenWriter(start_block=4)
            write_success = writer.write_token(encrypted, status_cb=rfid_cb)

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
