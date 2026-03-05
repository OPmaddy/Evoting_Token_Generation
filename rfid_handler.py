# rfid_handler.py
import time
import board
import busio
from adafruit_pn532.i2c import PN532_I2C
from adafruit_pn532.adafruit_pn532 import MIFARE_CMD_AUTH_B


class RFIDHandler:
    def __init__(self, block=4):
        self.block = block
        self.key = b'\xFF\xFF\xFF\xFF\xFF\xFF'

        i2c = busio.I2C(board.SCL, board.SDA)
        self.pn532 = PN532_I2C(i2c, debug=False)
        self.pn532.SAM_configuration()

    def _prepare_data(self, text: str) -> bytes:
        """
        Converts token string to exactly 16 bytes
        """
        return text.encode("utf-8")[:16].ljust(16, b'\x00')

    def write_token_blocking(self, token: str, status_cb=None):
        """
        Blocks until token is successfully written.
        status_cb(msg) → UI callback
        """
        data = self._prepare_data(token)

        if status_cb:
            status_cb("Place blank RFID card on reader")

        while True:
            uid = self.pn532.read_passive_target(timeout=0.5)
            if not uid:
                continue

            if status_cb:
                status_cb("Card detected\nWriting token...")

            auth = self.pn532.mifare_classic_authenticate_block(
                uid,
                self.block,
                MIFARE_CMD_AUTH_B,
                self.key
            )

            if not auth:
                if status_cb:
                    status_cb("Authentication failed\nTry another card")
                time.sleep(2)
                continue

            success = self.pn532.mifare_classic_write_block(
                self.block,
                data
            )

            if success:
                if status_cb:
                    status_cb("RFID write successful\nRemove card")
                time.sleep(2)
                return True
            else:
                if status_cb:
                    status_cb("Write failed\nKeep card steady")
                time.sleep(1)
