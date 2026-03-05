# Biometric Authentication and Voting Token Station

This repository contains the codebase for a Biometric Authentication and Voting Token Generation Station, designed to run on a Raspberry Pi. It handles voter identity verification using facial recognition, assigns a voting booth, generates a voting payload, encrypts it using hardware-bound RSA keys, and writes the encrypted payload to an RFID Smart Card.

## 📌 Overview

The system ensures highly secure, spoof-resistant voting token generation:
1. **Identity Verification:** Looks up the voter in the Electoral Roll and performs facial recognition (with liveness/anti-spoofing).
2. **Booth Assignment:** Dynamically assigns the voter to an available Ballot Marking Device (BMD).
3. **Payload Encryption:** Encrypts the voter's token payload (containing their eligible elections and booth assignment) using the assigned BMD's public RSA key.
4. **Hardware-bound Decryption:** Ensures that the written RFID card can *only* be decrypted by the exact physical Raspberry Pi of the assigned booth, leveraging the device's unique MAC address and CPU serial.

## 📂 Expected Preloaded Data

For the application to function correctly, several files and directories **must be preloaded** into the root of the project directory.

> **Note:** The `embeddings/` folder and `bmd_keys.json` containing sensitive biometric and cryptographic data are ignored by Git via `.gitignore`.

1. **`Electoral_Roll.csv`**
   - A CSV file containing the list of eligible voters.
   - **Expected Format:** `Entry_Number,Name,Vector of which Elections he is elidgible for`
   - **Example:** `2022EE11737,Madhav Gupta,E1;E3;E6`

2. **`embeddings/` Directory**
   - A directory containing pre-computed NumPy (`.npy`) facial embedding vectors for each registered voter.
   - **Naming Convention:** Must be named strictly by the `Entry_Number` (e.g., `2022EE11737.npy`).

3. **`bmd_keys.json`**
   - A JSON file containing the total number of booths and their respective Public RSA keys (in PEM format).
   - The application uses these public keys to encrypt the token payload for the assigned booth.
   - **Example Structure:**
     ```json
     {
       "num_booths": 2,
       "keys": {
         "1": "-----BEGIN PUBLIC KEY-----\n...",
         "2": "-----BEGIN PUBLIC KEY-----\n..."
       }
     }
     ```

## ⚙️ How the Codebase Works

### 1. The Authentication Flow (`app.py`)
The main execution begins in `app.py`. 
- A Fullscreen GUI initializes and requests the voter's Entry Number.
- The system checks `Electoral_Roll.csv` (via `logic.voter`) to verify the entry exists and the voter hasn't already been issued a token.
- It then loads the reference biometric data from `embeddings/{entry_number}.npy`.
- The camera begins capturing frames and executes **Face Verification** (`logic.face`).

### 2. Payload Generation & Encryption
- Upon successful biometric verification, a token payload is constructed (`logic.token.build_token_payload`). This payload includes the elections the voter is eligible for.
- A booth is assigned using a deterministic or load-balanced algorithm.
- The system retrieves the assigned booth's public key from `bmd_keys.json` and encrypts the payload using **RSA-OAEP (SHA-256)** encryption.

### 3. RFID Writing (`rfid_handler.py`)
- The encrypted ciphertext token is formatted and written to an initialized MIFARE Classic RFID Smart Card via the PN532 I2C interface.
- If testing on Windows/Dev environment, `MOCK_RFID = True` will write the token to a local `mock_rfid.txt` file instead of hardware.

### 4. BMD Decryption & Hardware Identity (`hardware_crypto.py` & `rf_read.py`)
- When the voter takes their RFID card to the Ballot Marking Device (BMD), a script like `rf_read.py` reads the payload.
- **Security Check:** `hardware_crypto.py` derives a deterministic, strong passphrase purely from the local Raspberry Pi's physical Hardware (MAC Address + CPU Serial from `/proc/cpuinfo`).
- This passphrase unlocks `private.pem`. If the SD card is stolen and placed in a different Pi, the MAC/Serial will change, the passphrase will be wrong, and the private key cannot be unlocked, preventing ballot decryption.

## 📜 Key Scripts & Modules

- **`app.py` / `prod.py`**: The main GUI applications coordinating UI, Camera, Identity Check, and Token assignment.
- **`generate_bmd_keys.py`**: A deployment utility run *once* per BMD machine. It generates an RSA key pair, locks the `private.pem` to the hardware using `hardware_crypto.py`, and outputs a unencrypted `public.pem` (which the central server collects to build `bmd_keys.json`).
- **`hardware_crypto.py`**: Core security module preventing hardware swapping. Derives decryption passphrases from physical hardware signatures.
- **`rfid_handler.py`**: Hardware interface logic for writing Data to an RFID card using the Adafruit PN532 library.
- **`rf_read.py`**: Standalone reader tool used by the BMDs. Reads the encrypted block from the MIFARE card, accesses the hardware-bound private key, and decrypts the payload for voting.

## 🚀 Setup & Execution

### Prerequisites
- Raspberry Pi with a camera module connected and enabled.
- PN532 RFID Module connected via I2C (SDA/SCL).

### Installation (Raspberry Pi)
We have provided a bash script that installs all system dependencies (libcamera, GUI tools, i2c components), creates a python virtual environment, and installs the requirements.

1. Clone the repository and navigate into it:
   ```bash
   git clone <repository-url>
   cd Evoting_Token_Generation
   ```

2. **Enable I2C on the Raspberry Pi:**
   - Run `sudo raspi-config`
   - Navigate to `Interface Options` -> `I2C` -> `Enable`
   - Select `Yes` and `Finish`
   - Reboot your Pi: `sudo reboot`

3. **Run the Automated Setup Script:**
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```
   *Note: The script requires `sudo` privileges for system package installation. It will initialize a virtual environment (`venv`) for Python.*

### Running the System
Ensure `Electoral_Roll.csv`, `embeddings/`, and `bmd_keys.json` are placed in the directory.

1. Activate the virtual environment generated by the setup script:
   ```bash
   source venv/bin/activate
   ```

2. Run the token generation app:
   ```bash
   python app.py
   ```
   *(Use `sudo` if the PN532 I2C interface requires elevated permissions depending on your OS configuration).*

> **Note on Embeddings Model:**
> If you are setting this up for the very first time, the underlying FaceAnalysis framework (`insightface` / `onnxruntime`) will automatically download the required model weights upon the first run of the script. No manual installation of the AI models is necessary!
