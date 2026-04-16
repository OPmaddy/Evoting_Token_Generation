# E-Voting System: Election Operations Guide

This guide provides comprehensive instructions for running and managing an election using the Centralized Token Coordination Server.

---

## 🏗️ System Architecture Overview

The system uses a **Two-Stage mTLS (Mutual TLS)** architecture for security:
1.  **Stage 1 (Master Certificate)**: A permanent management credential used by TGstations only to "bootstrap" their identity.
2.  **Stage 2 (Election Certificates)**: Unique, temporary credentials generated per-election for all voting and audit operations.

---

## 🛠️ Step 1: Initial Server Setup

### 1. Install Dependencies
Ensure you have the required Python libraries on the server:
```bash
pip install flask cryptography pandas pymongo gunicorn
```

### 2. Generate Master Credentials
Run this command ONCE to initialize the Master CA and Master Client Certificate:
```bash
cd server_end
python -c "from election_manager import ElectionManager; em = ElectionManager('.'); em.setup_master_certs()"
```
This creates the `master_certs/` directory and the `ca_bundle.crt`.

### 3. Start the Server
Run the server using Gunicorn. Use the provided production command:
```bash
nohup /home/madhav/Evoting_Token_Generation/server_end/venv/bin/gunicorn --chdir /home/madhav/Evoting_Token_Generation/server_end -c gunicorn_config.py app:application > /home/madhav/Evoting_Token_Generation/server_end/logs/server_logs.log 2>&1 &
```

---

## 📡 Step 2: Station Initial Preparation

Every Token Generation Station (TGstation) needs the **Master Certificate** to communicate with the server for the first time.

1.  **Locate Certificates**: On the server, find `server_end/master_certs/master_client.crt`, `master_client.key`, and `master_ca.crt`.
2.  **Manual Transfer**: Copy these files to the TGstation at:
    `~/Evoting_Token_Generation/certs/master/`
3.  **Identity**: Ensure each station has its unique ID in `~/Evoting_Token_Generation/device_id.txt` (e.g., `1`, `2`, `3`).

---

## 🌐 Step 3: Browser Access & Identity Verification

Because the server enforces **Mutual TLS (mTLS)**, your web browser must present a valid certificate to the server. Without this, the server will reject the connection immediately.

### 1. Locate the Admin Certificate
On the server, find the browser-ready certificate file:
`server_end/master_certs/admin_browser.p12`

### 2. Import the Certificate into your Browser
You must import this file into your "Personal Certificates" store:

#### **Chrome / Edge / Windows**
1.  Open Chrome Settings -> **Privacy and Security** -> **Security**.
2.  Select **Manage Device Certificates** (opens Windows Certificate Manager).
3.  Go to the **Personal** tab and click **Import**.
4.  Browse for `admin_browser.p12`.
5.  **Password**: The default password is `admin123`.
6.  Restart your browser.

#### **Firefox**
1.  Firefox Settings -> **Privacy & Security**.
2.  Scroll to **Certificates** and click **View Certificates**.
3.  In the **Your Certificates** tab, click **Import**.
4.  Select `admin_browser.p12`.
5.  **Password**: `admin123`.

### 3. Access the Dashboard
Navigate to:
`https://<server-ip>:5000/admin/dashboard`

When prompted by your browser, select the **"EVoting Admin User"** certificate.

---

## 🗳️ Step 4: Running an Election

### 1. Access the Dashboard
Open your browser and navigate to:
`https://<server-ip>:5000/admin/dashboard`
*(Log in using your admin credentials if prompted).*

### 2. Configure & Start
1.  Go to the **"New Election"** tab.
2.  **Upload Files**:
    - `Electoral_Roll.csv`: The list of eligible voters.
    - `bmd_keys.json`: The encryption keys for the Booth Management Devices.
3.  **Setup Stations**:
    - Enter the total number of TGstations.
    - For each station, enter the **BMD IDs** it is allowed to handle (e.g., Station 1 handles BMDs 1 and 2).
4.  **Set End Time**: Choose the scheduled end time for the election.
5.  **Click "Generate & Start"**: This archives old data and generates new Stage 2 certs for all stations.

---

## 🔄 Step 4: Provisioning TGstations

Once the election is started on the server:
1.  **Turn on the TGstations**.
2.  Run the application: `python app.py`.
3.  **Automatic Provisioning**:
    - The station detects it lacks election certs.
    - It uses the **Master Cert** to call `/api/device/<id>/reinit`.
    - It downloads its unique Election Certs, Electoral Roll, and BMD mapping.
    - **Self-Reboot**: The station will automatically reboot to apply the new state.
4.  **Ready to Vote**: After reboot, the station is ready for the election flow.

---

## 📊 Step 5: Post-Election Operations

### 1. End Election
On the Dashboard, click **"END ELECTION & COLLECT RESULTS"**.
- This stops all stations from generating further tokens.
- It prepares the final audit logs.

### 2. Download Audit ZIP
Go to the **"Reports"** tab and click **"Download Master Audit ZIP"**.
This ZIP contains:
- `master_audit_report.csv`: Every token issued, its timestamp, and the device ID.
- `regeneration_history.log`: Audit trail of any tokens that were re-issued (overridden).
- `raw_device_logs/`: All internal logs uploaded by the pins during the election.

---

## 🛡️ Security Maintenance

### Rotating Master Credentials
If a Master Certificate is compromised or you wish to refresh the management layer:
1.  Go to the **Dashboard**.
2.  In the **Security & Certificates** section, click **"ROTATE MASTER CREDENTIALS"**.
3.  **⚠️ WARNING**: This invalidates all master certs on all stations. You must manually repeat **Step 2 (Station Preparation)** for all devices before any further provisioning can occur.

### Logs
Server logs are stored in `server_end/logs/`. Individual device logs are synced to `server_end/device_logs/` upon election conclusion.

---
**System Maintainer Note**: Ensure the server time is synchronized via NTP, as all mTLS certificates and token timestamps rely on accurate system time.
