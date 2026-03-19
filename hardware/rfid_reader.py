import time

try:
    import board
    import busio
    from adafruit_pn532.i2c import PN532_I2C
    from adafruit_pn532.adafruit_pn532 import MIFARE_CMD_AUTH_A
    HAS_RFID = True
except ImportError:
    HAS_RFID = False

class RFIDEntryReader:
    """
    Reads the Entry Number from Block 1 of a MIFARE Classic RFID card.
    Ported from the Arduino PN532 logic.
    """
    def __init__(self):
        if not HAS_RFID:
            raise RuntimeError("Adafruit PN532 libraries not installed.")
            
        self.i2c = busio.I2C(board.SCL, board.SDA)
        self.pn532 = PN532_I2C(self.i2c, debug=False)
        self.pn532.SAM_configuration()
        self.key = b'\xFF\xFF\xFF\xFF\xFF\xFF'

    def read_entry_number(self) -> str:
        if not HAS_RFID:
            return None
            
        try:
            # Short timeout to not block the polling thread too long
            uid = self.pn532.read_passive_target(timeout=0.2)
            if uid is None:
                return None
                
            if len(uid) == 4:  # MIFARE Classic 1K usually has 4-byte UID
                # Authenticate Block 1 with Key A (0x60)
                auth = self.pn532.mifare_classic_authenticate_block(
                    uid, 1, MIFARE_CMD_AUTH_A, self.key
                )
                if not auth:
                    return None
                    
                data = self.pn532.mifare_classic_read_block(1)
                if data is None:
                    return None
                    
                # Extract string until null terminator
                entry_str = ""
                for b in data:
                    if b == 0:
                        break
                    entry_str += chr(b)
                
                entry_str = entry_str.strip()
                if entry_str:
                    return entry_str
        except Exception as e:
            # Ignore transient I2C errors during polling
            pass
            
        return None

    def close(self):
        """Release the I2C bus resource."""
        try:
            self.i2c.deinit()
        except Exception:
            pass
