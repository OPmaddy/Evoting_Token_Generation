from picamera2 import Picamera2
import cv2

class Camera:
    def __init__(self):
        self.cam = Picamera2()
        self.cam.configure(
            self.cam.create_preview_configuration(
                main={"format": "RGB888", "size": (640, 480)}
            )
        )

    def start(self):
        self.cam.start()

    def stop(self):
        self.cam.stop()

    def close(self):
        self.cam.close()

    def capture_frame(self):
        """
        Returns RGB frame as numpy array
        """
        frame = self.cam.capture_array()
        return frame
