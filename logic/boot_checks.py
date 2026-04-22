import subprocess
import os
import time
import datetime
from ui.screens import status_screen

def log_boot_check(message):
    log_path = "logs/boot_checks.log"
    os.makedirs("logs", exist_ok=True)
    ts = datetime.datetime.now().isoformat()
    with open(log_path, "a") as f:
        f.write(f"[{ts}] {message}\n")

def check_wifi(app, max_retries=5, retry_delay=5):
    """Checks if WiFi is connected and returns the SSID."""
    log_boot_check("Starting WiFi check...")
    for attempt in range(1, max_retries + 1):
        try:
            # Try to get SSID using iwgetid
            ssid = subprocess.check_output(["iwgetid", "-r"], stderr=subprocess.DEVNULL).decode().strip()
            if ssid:
                log_boot_check(f"WiFi Connected: {ssid}")
                return True, ssid
        except Exception:
            pass
            
        status_screen(app, "BOOT CHECK - WIFI", 
                      f"Waiting for WiFi connection...\nAttempt {attempt} of {max_retries}", 
                      fg="orange")
        app.root.update()
        time.sleep(retry_delay)
    
    log_boot_check("WiFi check failed after max retries.")
    return False, None

def check_ntp_sync(app, max_retries=5, retry_delay=5):
    """Checks if system time is synchronized via NTP."""
    log_boot_check("Starting NTP sync check...")
    for attempt in range(1, max_retries + 1):
        try:
            # Check if NTP is synchronized
            output = subprocess.check_output(["timedatectl", "show", "--property=NTPSynchronized"], 
                                           stderr=subprocess.DEVNULL).decode().strip()
            if "NTPSynchronized=yes" in output:
                log_boot_check("NTP Synchronized.")
                return True, datetime.datetime.now().strftime("%H:%M")
        except Exception:
            pass

        # Also try a quick manual sync if it's the first few attempts
        if attempt <= 2:
            try:
                cmd = 'sudo date -s "$(wget -qSO- --max-redirect=0 google.com 2>&1 | grep Date: | cut -d\' \' -f5-8)Z"'
                subprocess.run(cmd, shell=True, timeout=10, stderr=subprocess.DEVNULL)
            except:
                pass

        status_screen(app, "BOOT CHECK - TIME", 
                      f"Synchronizing system clock...\nAttempt {attempt} of {max_retries}", 
                      fg="orange")
        app.root.update()
        time.sleep(retry_delay)

    log_boot_check("NTP sync failed after max retries.")
    return False, None

def check_rfid(app, mock=False, max_retries=3, retry_delay=3):
    """Initializes RFID and checks for a response."""
    if mock:
        log_boot_check("RFID check skipped (Mock Mode).")
        return True, None

    log_boot_check("Starting RFID hardware check...")
    for attempt in range(1, max_retries + 1):
        try:
            from hardware.rfid_writer import RFIDTokenWriter
            writer = RFIDTokenWriter()
            # If init succeeds, we assume hardware is responsive
            writer.close()
            log_boot_check("RFID hardware initialized successfully.")
            return True, None
        except Exception as e:
            log_boot_check(f"RFID Init Error (attempt {attempt}): {e}")
            
        status_screen(app, "BOOT CHECK - RFID", 
                      f"Checking RFID hardware...\nAttempt {attempt} of {max_retries}\nError: Hardware not responding", 
                      fg="orange")
        app.root.update()
        time.sleep(retry_delay)

    log_boot_check("RFID hardware check failed after max retries.")
    return False, "Hardware Error"

def run_boot_checks(app, mock_rfid=False):
    """Runs all boot-up hardware and connectivity checks."""
    
    # 1. WiFi
    ok, ssid = check_wifi(app)
    if not ok: return False
    app.wifi_ssid = ssid
    
    # 2. Time
    ok, time_str = check_ntp_sync(app)
    if not ok: return False
    
    # 3. RFID
    ok, err = check_rfid(app, mock=mock_rfid)
    if not ok: return False
    
    return True
