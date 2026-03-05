import time
import board
import busio
from adafruit_pn532.i2c import PN532_I2C
from adafruit_pn532.adafruit_pn532 import MIFARE_CMD_AUTH_B


class RFIDTokenWriter:
    """
    Writes a long token string across consecutive MIFARE Classic blocks.
    Card is tapped ONCE, written fully, then removed.
    """

    def __init__(self, start_block=4):
        self.start_block = start_block
        self.key = b'\xFF\xFF\xFF\xFF\xFF\xFF'

        i2c = busio.I2C(board.SCL, board.SDA)
        self.pn532 = PN532_I2C(i2c, debug=False)
        self.pn532.SAM_configuration()

    # ------------------ SAFETY ------------------

    def _is_trailer_block(self, block_no: int) -> bool:
        return (block_no + 1) % 4 == 0   # 7,11,15,...

    def _prepare_data(self, data: bytes) -> bytes:
        return data[:16].ljust(16, b'\x00')

    # ------------------ MAIN WRITE ------------------

    def write_token(self, token: str, status_cb=None) -> bool:
        raw = token.encode("utf-8")
        raw += b'\x00' * ((16 - len(raw) % 16) % 16)

        chunks = [raw[i:i + 16] for i in range(0, len(raw), 16)]

        if status_cb:
            status_cb("Place RFID card on reader")

        # 🔑 Wait for card ONCE
        uid = None
        start = time.time()
        while uid is None and time.time() - start < 20:
            uid = self.pn532.read_passive_target(timeout=0.5)

        if not uid:
            if status_cb:
                status_cb("No card detected\nTimeout")
            return False

        if status_cb:
            status_cb(f"Card detected\nWriting {len(chunks)} blocks")

        block_no = self.start_block

        for i, chunk in enumerate(chunks):
            while self._is_trailer_block(block_no):
                block_no += 1

            if status_cb:
                status_cb(
                    f"Writing block {block_no} "
                    f"({i + 1}/{len(chunks)})"
                )

            auth = self.pn532.mifare_classic_authenticate_block(
                uid,
                block_no,
                MIFARE_CMD_AUTH_B,
                self.key
            )

            if not auth:
                if status_cb:
                    status_cb(f"Authentication failed at block {block_no}")
                return False

            result = self.pn532.mifare_classic_write_block(
                block_no,
                self._prepare_data(chunk)
            )

            if result not in (None, True):
                if status_cb:
                    status_cb(f"Write failed at block {block_no}")
                return False

            block_no += 1
            time.sleep(0.05)  # short settle delay

        if status_cb:
            status_cb("RFID write complete\nRemove card")

        return True
