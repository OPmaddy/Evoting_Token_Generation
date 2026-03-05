# tester.py
import time
from datetime import datetime
from ui.base import FullscreenApp
from ui.screens import (
    entry_number_screen,
    status_screen,
    already_generated_screen,
    verification_progress_screen,
    rfid_status_screen,
    booth_confirmation_screen
)

def main():
    app = FullscreenApp()

    # Mock data for testing
    mock_voter_duplicate = {
        "Name": "John Doe",
        "Booth_Number": "15",
        "Token_Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Image1Path": "dummy_path_1.jpg",
        "Image2Path": "dummy_path_2.jpg"
    }

    def flow():
        # 1. Entry Screen
        entry = entry_number_screen(app)
        
        if not entry:
            app.root.after(100, flow)
            return

        print(f"DEBUG: Input received: {entry}")

        # Test Branching based on input
        if entry.lower() in ["dup", "d"]:
            # Test "Already Generated" Screen
            already_generated_screen(app, mock_voter_duplicate, on_done=flow)

        elif entry.lower() in ["err", "e"]:
            # Test Error Screen
            status_screen(
                app, 
                "TEST ERROR", 
                "This is a test of the error display.\nSystem has encountered a simulated fault.", 
                fg="red", 
                on_done=flow
            )

        else:
            # Test Happy Path
            happy_path_sequence(entry)

    def happy_path_sequence(entry):
        # 2. Status Screen (Lookup success)
        status_screen(
            app, 
            "ENTRY ACCEPTED",
            f"Entry Number: {entry}\nProceeding to verification...",
            fg="green",
            delay=1500,
            on_done=lambda: face_verification_sim(entry)
        )

    def face_verification_sim(entry):
        # 3. Face Verification Progress
        verification_progress_screen(
            app, 
            "Please stand still and look directly at the camera.\nEnsure your face is unaffected by strong backlight."
        )
        # Simulate processing time
        app.root.after(2500, lambda: rfid_sim(entry))

    def rfid_sim(entry):
        # 4. RFID Generation
        # Simulate the callbacks from RFIDTokenWriter
        messages = [
            "Place RFID card on reader",
            "Card detected\nWriting 4 blocks",
            "Writing block 4 (1/4)",
            "Writing block 5 (2/4)",
            "Writing block 6 (3/4)",
            "Writing block 7 (4/4)",
            "RFID write complete\nRemove card"
        ]
        
        delay_accum = 0
        for i, msg in enumerate(messages):
            # Schedule each status update
            # We need to capture the current msg in lambda, so use default arg m=msg
            app.root.after(delay_accum, lambda m=msg: rfid_status_screen(app, m))
            delay_accum += 800 # 800ms between updates
            
        # Move to booth screen after all updates + small pause
        app.root.after(delay_accum + 500, lambda: booth_sim(entry))

    def booth_sim(entry):
        # 5. Success / Booth Allocation
        # Mock booth assignment
        assigned_booth = int(hash(entry) % 20) + 1
        booth_confirmation_screen(app, booth=assigned_booth, on_done=flow)

    app.root.after(100, flow)
    print("Tester running. Valid commands on Entry Screen:")
    print("  'dup' or 'd' -> Simulate Already Voted user")
    print("  'err' or 'e' -> Simulate Error message")
    print("  <any other>  -> Simulate successful voting flow")
    app.root.mainloop()


if __name__ == "__main__":
    main()
