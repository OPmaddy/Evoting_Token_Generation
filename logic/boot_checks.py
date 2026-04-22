
import subprocess
import os
import time
import datetime
from ui.screens import status_screen
from ui.styles import SUCCESS_COLOR, ACCENT_COLOR, ERROR_COLOR

def log_boot_check(message):
    log_path = "logs/boot_checks.log"
    os.makedirs("logs", exist_ok=True)
    ts = datetime.datetime.now().isoformat()
    try:
        with open(log_path, "a") as f:
            f.write(f"[{ts}] {message}\n")
    except: pass

def check_wifi(app):
    """Checks if WiFi is connected and returns the SSID."""
    try:
        # Check SSID
        ssid = subprocess.check_output(["iwgetid", "-r"], stderr=subprocess.DEVNULL).decode().strip()
        if ssid:
            return True, ssid
    except Exception:
        pass
    return False, None

def check_ntp_sync(app):
    """Checks if system time is synchronized via NTP."""
    try:
        output = subprocess.check_output(["timedatectl", "show", "--property=NTPSynchronized"], 
                                       stderr=subprocess.DEVNULL).decode().strip()
        if "NTPSynchronized=yes" in output:
            return True, datetime.datetime.now().strftime("%H:%M")
    except Exception:
        pass

    # Quick manual sync attempt if network is likely up
    try:
        # Try to fetch time from google
        cmd = 'sudo date -s "$(wget -qSO- --max-redirect=0 google.com 2>&1 | grep Date: | cut -d\' \' -f5-8)Z"'
        subprocess.run(cmd, shell=True, timeout=5, stderr=subprocess.DEVNULL)
        # Check again
        return True, datetime.datetime.now().strftime("%H:%M")
    except:
        pass

    return False, None

def check_rfid(app, mock=False):
    """Initializes RFID and checks for a response."""
    if mock:
        return True, None

    try:
        from hardware.rfid_writer import RFIDTokenWriter
        writer = RFIDTokenWriter()
        writer.close()
        return True, None
    except Exception as e:
        return False, "Hardware Error"

def run_boot_checks(app, mock_rfid=False):
    """
    Executes boot-up hardware checks. 
    Maintains state so that only failed components are retried.
    """
    if not hasattr(app, 'boot_results'):
        app.boot_results = {
            "wifi": {"ok": False, "val": None},
            "time": {"ok": False, "val": None},
            "rfid": {"ok": False, "val": None}
        }

    while True:
        # Step 1: WiFi (Foundation for Time)
        if not app.boot_results["wifi"]["ok"]:
            ok, ssid = check_wifi(app)
            if ok:
                app.boot_results["wifi"]["ok"] = True
                app.boot_results["wifi"]["val"] = ssid
                app.wifi_ssid = ssid # Export for status bar
                log_boot_check(f"WiFi OK: {ssid}")
        
        # Step 2: Time (Only if WiFi is up)
        if app.boot_results["wifi"]["ok"] and not app.boot_results["time"]["ok"]:
            ok, time_str = check_ntp_sync(app)
            if ok:
                app.boot_results["time"]["ok"] = True
                app.boot_results["time"]["val"] = time_str
                log_boot_check(f"Time Sync OK: {time_str}")

        # Step 3: RFID
        if not app.boot_results["rfid"]["ok"]:
            ok, err = check_rfid(app, mock=mock_rfid)
            if ok:
                app.boot_results["rfid"]["ok"] = True
                app.boot_results["rfid"]["val"] = "Ready"
                log_boot_check("RFID OK")
            else:
                app.boot_results["rfid"]["val"] = err

        # Construct status display
        lines = []
        def fmt(key, label):
            res = app.boot_results[key]
            if res["ok"]:
                return f"{label}: ✓ {res['val']}"
            else:
                status = "✗ FAILED" if res["val"] else "... CHECKING"
                return f"{label}: {status}"

        lines.append(fmt("wifi", "WiFi Network"))
        lines.append(fmt("time", "System Clock"))
        lines.append(fmt("rfid", "RFID Reader "))

        all_ok = all(r["ok"] for r in app.boot_results.values())
        if all_ok:
            status_screen(app, "SYSTEM READY", "\n".join(lines), fg=SUCCESS_COLOR, delay=1500)
            return True

        # Show live progress
        status_screen(app, "HARDWARE INITIALIZATION", 
                      "Ensuring all systems are operational...\n\n" + "\n".join(lines), 
                      fg=ACCENT_COLOR)
        app.root.update()
        time.sleep(2.5) # Wait before next partial retry
