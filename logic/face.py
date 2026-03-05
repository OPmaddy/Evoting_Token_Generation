import os
import time
import cv2
import numpy as np
from PIL import Image
import insightface
import dlib
import threading
import concurrent.futures
from scipy.signal import find_peaks

from src.anti_spoof_predict import AntiSpoofPredict
from src.generate_patches import CropImage
from src.utility import parse_model_name

# ================= Configuration =================
DEVICE_ID = 0
FACE_MATCH_THRESHOLD = 0.45

# States
STATE_DETECTION = 1
STATE_ALIGNMENT = 2
STATE_RECORDING = 3
STATE_PROCESSING = 4
STATE_RESULT = 5
STATE_DONE = 6

# Thresholds
ALIGN_TOLERANCE = 0.4
ALIGN_DURATION = 2.0       # Hold alignment for 1 second
RECORDING_FRAMES = 90      # ~1.5 seconds at 30 fps

# ================= Models =================
class FaceSystem:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = FaceSystem()
        return cls._instance

    def __init__(self):
        print("Loading InsightFace...")
        self.face_app = insightface.app.FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        self.face_app.prepare(ctx_id=DEVICE_ID, det_size=(640, 480))
        
        print("Loading SilentFace...")
        self.anti_spoof_model = AntiSpoofPredict(DEVICE_ID)
        self.image_cropper = CropImage()
        self.anti_spoof_models_dir = "./resources/anti_spoof_models"
        
        print("Loading Dlib...")
        self.detector = dlib.get_frontal_face_detector()
        self.predictor = dlib.shape_predictor("resources/detection_model/shape_predictor_68_face_landmarks.dat")
        self.LEFT_EYE = list(range(36, 42))
        self.RIGHT_EYE = list(range(42, 48))

    def detect_faces(self, frame):
        return self.face_app.get(frame)

    def check_liveness(self, frame, face_bbox):
        x1, y1, x2, y2 = face_bbox
        image_bbox = [x1, y1, x2-x1, y2-y1]
        
        prediction = np.zeros((1, 3))
        for model_name in os.listdir(self.anti_spoof_models_dir):
            h, w, _, scale = parse_model_name(model_name)
            param = {
                "org_img": frame,
                "bbox": image_bbox,
                "scale": scale,
                "out_w": w,
                "out_h": h,
                "crop": True,
            }
            if scale is None:
                param["crop"] = False
            img = self.image_cropper.crop(**param)
            prediction += self.anti_spoof_model.predict(img, os.path.join(self.anti_spoof_models_dir, model_name))
        
        label = np.argmax(prediction)
        value = prediction[0][label] / 2
        is_real = (label == 1)
        return is_real, value

    def _calculate_ear(self, eye):
        A = np.linalg.norm(eye[1] - eye[5])
        B = np.linalg.norm(eye[2] - eye[4])
        C = np.linalg.norm(eye[0] - eye[3])
        if C == 0: return 0.0
        return (A + B) / (2.0 * C)

    def get_ear(self, frame, face_bbox=None):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if face_bbox is not None:
            x1, y1, x2, y2 = face_bbox
            dlib_rect = dlib.rectangle(int(x1), int(y1), int(x2), int(y2))
        else:
            faces = self.detector(gray)
            if len(faces) == 0: return 0.0, 0.0
            dlib_rect = faces[0]
            
        shape = self.predictor(gray, dlib_rect)
        coords = np.array([(shape.part(i).x, shape.part(i).y) for i in range(68)])
        left_ear = self._calculate_ear(coords[self.LEFT_EYE])
        right_ear = self._calculate_ear(coords[self.RIGHT_EYE])
        return left_ear, right_ear

# ================= Controller =================
class UIController:
    def __init__(self, sys, stored_embedding, dump_dir, entry_number):
        self.sys = sys
        self.stored_embedding = stored_embedding
        self.dump_dir = dump_dir
        self.entry_number = entry_number
        
        self.state = STATE_DETECTION
        self.state_start_time = time.time()
        
        # Alignment
        self.align_start_time = 0
        
        # Recording buffer
        self.recording_buffer = [] 
        
        # UI Data
        self.frame = None
        self.ui_msg = "Looking for Face..."
        self.ui_color = (255, 255, 255)
        self.bbox = None
        
        # Result details
        self.result_text = ""
        self.processing_progress = ""
        self.is_success = False
        self.saved_images = []
        
        self.lock = threading.Lock()
        self.running = True

    def set_state(self, new_state):
        if self.state != new_state:
            print(f"Transitioning from {self.state} to {new_state}")
            self.state = new_state
            self.state_start_time = time.time()
            if new_state == STATE_RECORDING:
                self.recording_buffer = []
            elif new_state == STATE_ALIGNMENT:
                self.align_start_time = 0
            elif new_state == STATE_DETECTION:
                self.bbox = None

    def process_frame(self, frame):
        with self.lock:
            self.frame = frame.copy()
            height, width = frame.shape[:2]

            if self.state == STATE_DETECTION:
                faces = self.sys.detect_faces(frame)
                if faces:
                    main_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                    self.bbox = main_face.bbox.astype(int)
                    self.set_state(STATE_ALIGNMENT)
                else:
                    self.ui_msg = "Looking for Face..."
                    self.ui_color = (255, 255, 255)
                    self.bbox = None

            elif self.state == STATE_ALIGNMENT:
                faces = self.sys.detect_faces(frame)
                if not faces:
                    self.set_state(STATE_DETECTION)
                    return
                
                main_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                self.bbox = main_face.bbox.astype(int)
                
                cx = (self.bbox[0] + self.bbox[2]) / 2
                cy = (self.bbox[1] + self.bbox[3]) / 2
                
                target_x1 = width * (0.5 - ALIGN_TOLERANCE/2)
                target_x2 = width * (0.5 + ALIGN_TOLERANCE/2)
                target_y1 = height * 0.1
                target_y2 = height * 0.9

                if (target_x1 < cx < target_x2) and (target_y1 < cy < target_y2):
                    self.ui_msg = "Hold Still..."
                    self.ui_color = (0, 255, 0)
                    if self.align_start_time == 0:
                        self.align_start_time = time.time()
                    elif time.time() - self.align_start_time >= ALIGN_DURATION:
                        self.set_state(STATE_RECORDING)
                else:
                    self.align_start_time = 0
                    self.ui_msg = "Align face in the center box."
                    self.ui_color = (0, 0, 255)

            elif self.state == STATE_RECORDING:
                self.recording_buffer.append((time.time(), frame.copy()))
                self.ui_msg = "Please BLINK now! Recording..."
                self.ui_color = (0, 255, 255)
                
                if len(self.recording_buffer) >= RECORDING_FRAMES:
                    self.set_state(STATE_PROCESSING)

            elif self.state == STATE_PROCESSING:
                pass # Handled by the background thread

            elif self.state == STATE_RESULT:
                self.ui_msg = self.result_text
                if time.time() - self.state_start_time > 3.0:
                    self.set_state(STATE_DONE)

    def render(self):
        with self.lock:
            if self.frame is None:
                return None
            
            display_frame = self.frame.copy()
            height, width = display_frame.shape[:2]
            
            if self.state in [STATE_DETECTION, STATE_ALIGNMENT]:
                target_w = int(width * ALIGN_TOLERANCE)
                target_h = int(height * 0.8)
                tx1 = int((width - target_w) / 2)
                ty1 = int(height * 0.1)
                tx2 = tx1 + target_w
                ty2 = ty1 + target_h
                cv2.rectangle(display_frame, (tx1, ty1), (tx2, ty2), self.ui_color, 2)
            
            if self.bbox is not None and self.state == STATE_ALIGNMENT:
                cv2.rectangle(display_frame, (self.bbox[0], self.bbox[1]), (self.bbox[2], self.bbox[3]), self.ui_color, 2)

            msg = self.ui_msg
            if self.state == STATE_PROCESSING:
                msg = f"Processing... {self.processing_progress}"
                
            lines = msg.split('\n')
            for i, line in enumerate(lines):
                cv2.putText(display_frame, line, (20, 50 + i*40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, self.ui_color, 2)
                
            state_names = ["", "Detection", "Alignment", "Recording", "Processing", "Result", "Done"]
            cv2.putText(display_frame, f"State: {state_names[self.state]}", (20, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            
            return display_frame

    def _process_frame_one(self, frm):
        faces = self.sys.detect_faces(frm)
        if not faces:
            return {"forfeit": True, "reason": "No face found on Anchor Frame!"}
        
        main_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
        bbox = main_face.bbox.astype(int)
        
        is_match = False
        if np.dot(main_face.normed_embedding, self.stored_embedding) >= FACE_MATCH_THRESHOLD:
            is_match = True
            
        is_real, _ = self.sys.check_liveness(frm, main_face.bbox)
        
        return {
            "forfeit": False,
            "bbox": bbox,
            "is_real": is_real,
            "is_match": is_match,
        }

    def _process_blink_frame(self, index, frm, anchor_bbox):
        left_ear, right_ear = self.sys.get_ear(frm, anchor_bbox)
        
        if left_ear == 0.0 or right_ear == 0.0:
            return {"index": index, "forfeit": True, "reason": f"Face moved or lost at Frame {index+1}"}
        
        avg_ear = (left_ear + right_ear) / 2.0
        
        return {
            "index": index,
            "forfeit": False,
            "left_ear": left_ear,
            "right_ear": right_ear,
            "avg_ear": avg_ear
        }

    def run_processing_task(self):
        with self.lock:
            self.processing_progress = "Validating faces..."
            buffer_copy = list(self.recording_buffer)
            
        print("Starting offline parallel processing of", len(buffer_copy), "frames")
        
        self.processing_progress = "Validating Anchor Frame..."
        
        anchor_ts, anchor_frm = buffer_copy[0]
        anchor_data = self._process_frame_one(anchor_frm)
        
        if anchor_data["forfeit"]:
            print(f"Forfeiting: {anchor_data['reason']}")
            with self.lock:
                self.result_text = f"FAILED\n{anchor_data['reason']}"
                self.ui_color = (0, 0, 255)
                self.is_success = False
                self.set_state(STATE_RESULT)
            return
            
        anchor_bbox = anchor_data["bbox"]
        is_real = anchor_data["is_real"]
        is_match = anchor_data["is_match"]
        
        results = []
        frames_done = 0
        total_frames = len(buffer_copy)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_index = {
                executor.submit(self._process_blink_frame, i, frm, anchor_bbox): i 
                for i, (ts, frm) in enumerate(buffer_copy)
            }
            
            for future in concurrent.futures.as_completed(future_to_index):
                if not self.running: return
                
                res = future.result()
                
                if res["forfeit"]:
                    print(f"Forfeiting: {res['reason']}")
                    executor.shutdown(wait=False, cancel_futures=True)
                    with self.lock:
                        self.result_text = "FAILED\nFace moved during recording!"
                        self.ui_color = (0, 0, 255)
                        self.is_success = False
                        self.set_state(STATE_RESULT)
                    return
                    
                results.append(res)
                frames_done += 1
                with self.lock:
                    self.processing_progress = f"Frame {frames_done}/{total_frames}"

        if len(results) == 0:
            with self.lock:
                self.result_text = "FAILED\nNo faces found in recording!"
                self.ui_color = (0, 0, 255)
                self.is_success = False
                self.set_state(STATE_RESULT)
            return

        results.sort(key=lambda x: x["index"])

        ear_history = []
        for res in results:
            ear_history.append(res["avg_ear"])
            
        ear_array = np.array(ear_history)
        peaks, properties = find_peaks(-ear_array, prominence=0.08, width=1, distance=5)
        blinks_detected = len(peaks)
        
        print(f"Results -> Real: {is_real}, Match: {is_match}, Blinks: {blinks_detected}")
        
        with self.lock:
            if is_real and is_match and blinks_detected > 0:
                self.result_text = f"VERIFIED: SUCCESS\nBlink: Detected"
                self.ui_color = (0, 255, 0)
                self.is_success = True
                
                try:
                    p1 = os.path.join(self.dump_dir, f"{self.entry_number}_face_1.jpg")
                    cv2.imwrite(p1, anchor_frm)
                    self.saved_images.append(p1)
                    
                    if blinks_detected > 0:
                        blink_peak = peaks[0]
                        _, blink_frm = buffer_copy[blink_peak]
                        p2 = os.path.join(self.dump_dir, f"{self.entry_number}_face_blink.jpg")
                        cv2.imwrite(p2, blink_frm)
                        self.saved_images.append(p2)
                    else:
                        _, frm2 = buffer_copy[-1]
                        p2 = os.path.join(self.dump_dir, f"{self.entry_number}_face_2.jpg")
                        cv2.imwrite(p2, frm2)
                        self.saved_images.append(p2)
                except Exception as e:
                    print(f"Warning: Failed to save images: {e}")
            else:
                fail_reason = ""
                if not is_real: fail_reason += "Fake Face "
                if not is_match: fail_reason += "Mismatch Identity "
                if blinks_detected == 0: fail_reason += "No Blink "
                self.result_text = f"FAILED\n{fail_reason.strip()}"
                self.ui_color = (0, 0, 255)
                self.is_success = False
            self.set_state(STATE_RESULT)

# ================= Runner =================
def run_face_verification(
    camera,
    stored_embedding,
    dump_dir,
    entry_number
):
    """
    Returns:
      success (bool),
      image_paths (list[str])
    """
    sys = FaceSystem.get_instance()
    controller = UIController(sys, stored_embedding, dump_dir, entry_number)
    
    processing_thread = None
    cv2.namedWindow("Face Verification Module", cv2.WINDOW_NORMAL)
    
    try:
        while controller.running:
            rgb_frame = camera.capture_frame()
            if rgb_frame is None:
                continue
                
            # frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
            frame = rgb_frame

            if controller.state == STATE_DONE:
                break
                
            if controller.state != STATE_PROCESSING:
                controller.process_frame(frame)
            elif controller.state == STATE_PROCESSING and (processing_thread is None or not processing_thread.is_alive()):
                processing_thread = threading.Thread(target=controller.run_processing_task, daemon=True)
                processing_thread.start()
            
            display_img = controller.render()
            if display_img is not None:
                cv2.imshow("Face Verification Module", display_img)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                controller.running = False
                break
                
            time.sleep(0.01)
            
    finally:
        controller.running = False
        if processing_thread and processing_thread.is_alive():
            processing_thread.join(timeout=2.0)
        
        # Ensure windows are destroyed
        try:
            cv2.destroyWindow("Face Verification Module")
        except cv2.error:
            pass
        cv2.waitKey(1)

    return controller.is_success, controller.saved_images
