import cv2
import numpy as np
import os
import insightface
import time
import threading
import platform
import concurrent.futures

try:
    from picamera2 import Picamera2
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False
    # If on windows or picamera fails to load, we can fallback or just raise error.
    # User requested consistently using picamera2 everywhere, but testing on Windows might need cv2 fallback.
    # We will use picamera2 if it's available, otherwise fallback to cv2 for dev.

from src.anti_spoof_predict import AntiSpoofPredict
from src.generate_patches import CropImage
from src.utility import parse_model_name
import dlib
from scipy.signal import find_peaks

# ================= Configuration =================
EMBEDDINGS_DIR = './embeddings'
ANTI_SPOOF_MODELS_DIR = "./resources/anti_spoof_models"
DEVICE_ID = 0
FACE_MATCH_THRESHOLD = 0.5

# States
STATE_DETECTION = 1
STATE_ALIGNMENT = 2
STATE_RECORDING = 3
STATE_PROCESSING = 4
STATE_RESULT = 5

# Thresholds
ALIGN_TOLERANCE = 0.4
ALIGN_DURATION = 2.0       # Hold alignment for 1 second
RECORDING_FRAMES = 90      # ~1.5 seconds at 30 fps
PASS_RATIO = 0.6
EAR_THRESHOLD = 0.22
CONSECUTIVE_FRAMES = 1

# ================= Models =================
def load_embeddings(emb_dir):
    features = {}
    if not os.path.exists(emb_dir):
        print(f"Directory not found: {emb_dir}")
        return features
    for f in os.listdir(emb_dir):
        if f.endswith('.npy'):
            name = os.path.splitext(f)[0]
            features[name] = np.load(os.path.join(emb_dir, f))
    return features

class FaceSystem:
    def __init__(self):
        print("Loading InsightFace...")
        self.face_app = insightface.app.FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        self.face_app.prepare(ctx_id=DEVICE_ID, det_size=(640, 480))
        self.known_embeddings = load_embeddings(EMBEDDINGS_DIR)
        
        print("Loading SilentFace...")
        self.anti_spoof_model = AntiSpoofPredict(DEVICE_ID)
        self.image_cropper = CropImage()
        
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
        for model_name in os.listdir(ANTI_SPOOF_MODELS_DIR):
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
            prediction += self.anti_spoof_model.predict(img, os.path.join(ANTI_SPOOF_MODELS_DIR, model_name))
        
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
    def __init__(self, sys):
        self.sys = sys
        self.state = STATE_DETECTION
        self.state_start_time = time.time()
        
        # Alignment
        self.align_start_time = 0
        
        # Recording buffer
        self.recording_buffer = []  # [(timestamp, frame, bbox_from_insightface)]
        
        # UI Data
        self.frame = None
        self.ui_msg = "Looking for Face..."
        self.ui_color = (255, 255, 255)
        self.bbox = None
        
        # Result details
        self.result_text = ""
        self.processing_progress = ""
        
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
                # Keep tracking face lightly to ensure it's still there
                # Or just record blindly for N frames to save time?
                # Best to record blindly to ensure high FPS during recording
                self.recording_buffer.append((time.time(), frame.copy()))
                self.ui_msg = "Please BLINK now! Recording..."
                self.ui_color = (0, 255, 255)
                
                if len(self.recording_buffer) >= RECORDING_FRAMES:
                    self.set_state(STATE_PROCESSING)

            elif self.state == STATE_PROCESSING:
                # In this state, the UI frozen message is handled differently because the main thread 
                # will be blocked running the models sequentially, OR we can run it in a thread.
                # Running in a thread allows UI to keep painting "Processing...".
                pass # Handled by the background thread

            elif self.state == STATE_RESULT:
                self.ui_msg = self.result_text
                # Color is set by processing thread
                if time.time() - self.state_start_time > 5.0:
                    self.set_state(STATE_DETECTION)


    def render(self):
        # Called by main thread to draw UI
        with self.lock:
            if self.frame is None:
                return None
            
            display_frame = self.frame.copy()
            height, width = display_frame.shape[:2]
            
            # Draw Alignment Box
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
                
            # Draw message text
            lines = msg.split('\n')
            for i, line in enumerate(lines):
                cv2.putText(display_frame, line, (20, 50 + i*40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, self.ui_color, 2)
                
            # Status bar
            state_names = ["", "Detection", "Alignment", "Recording", "Processing", "Result"]
            cv2.putText(display_frame, f"State: {state_names[self.state]}", (20, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            
            return display_frame

    def _process_frame_one(self, frm):
        """Heavy Anchor Frame: Runs InsightFace detection, Matching, and Liveness."""
        faces = self.sys.detect_faces(frm)
        if not faces:
            return {"forfeit": True, "reason": "No face found on Anchor Frame!"}
        
        main_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
        bbox = main_face.bbox.astype(int)
        
        # Match Identity
        is_match = False
        matched_name = "Unknown"
        if self.sys.known_embeddings:
            for k_name, k_emb in self.sys.known_embeddings.items():
                if np.dot(main_face.normed_embedding, k_emb) >= FACE_MATCH_THRESHOLD:
                    matched_name = k_name
                    is_match = True
                    break
        else:
            is_match = True
            matched_name = "No Known Base"
            
        # Assess Liveness
        is_real, _ = self.sys.check_liveness(frm, main_face.bbox)
        
        return {
            "forfeit": False,
            "bbox": bbox,
            "is_real": is_real,
            "is_match": is_match,
            "matched_name": matched_name
        }

    def _process_blink_frame(self, index, frm, anchor_bbox):
        """Lightweight Frame: Only runs Dlib EAR on the pre-calculated bounding box."""
        left_ear, right_ear = self.sys.get_ear(frm, anchor_bbox)
        
        # If the face moved out of the box, dlib will return EARs of 0.0
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
        
        main_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
        
        # 2. Match Identity
        is_match = False
        matched_name = "Unknown"
        if self.sys.known_embeddings:
            for k_name, k_emb in self.sys.known_embeddings.items():
                if np.dot(main_face.normed_embedding, k_emb) >= FACE_MATCH_THRESHOLD:
                    matched_name = k_name
                    is_match = True
                    break
        else:
            is_match = True
            matched_name = "No Known Base"
            
        # 3. Assess Liveness
        is_real, _ = self.sys.check_liveness(frm, main_face.bbox)
        
        # 4. Blink Detection
        left_ear, right_ear = self.sys.get_ear(frm, main_face.bbox)
        
        # Save frame with EAR values mapping immediately
        # debug_img = frm.copy()
        # text = f"L_EAR: {left_ear:.3f} | R_EAR: {right_ear:.3f}"
        # cv2.putText(debug_img, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        # cv2.imwrite(os.path.join(log_dir, f"frame_{index:04d}.jpg"), debug_img)
        
        avg_ear = (left_ear + right_ear) / 2.0
        
        return {
            "index": index,
            "forfeit": False,
            "is_real": is_real,
            "is_match": is_match,
            "matched_name": matched_name,
            "left_ear": left_ear,
            "right_ear": right_ear,
            "avg_ear": avg_ear
        }

    def run_processing_task(self):
        # Runs the heavy models on self.recording_buffer
        with self.lock:
            self.processing_progress = "Validating faces..."
            buffer_copy = list(self.recording_buffer)
            
        print("Starting offline parallel processing of", len(buffer_copy), "frames")
        
        # Setup EAR Logger and Image Dump Directory
        session_id = time.strftime('%Y%m%d_%H%M%S')
        log_dir = os.path.join("ear_logs", session_id)
        os.makedirs(log_dir, exist_ok=True)
        
        # ear_log_file = open(os.path.join(log_dir, "ear_log_prod.txt"), "a")
        # ear_log_file.write(f"\n--- NEW RECORDING SESSION: {session_id} ---\n")
        
        # ----------------------------------------------------
        # 1. Process Anchor Frame (Frame 1) Synchronously
        # ----------------------------------------------------
        self.processing_progress = "Validating Anchor Frame..."
        
        anchor_ts, anchor_frm = buffer_copy[0]
        anchor_data = self._process_frame_one(anchor_frm)
        
        if anchor_data["forfeit"]:
            print(f"Forfeiting: {anchor_data['reason']}")
            with self.lock:
                self.result_text = f"FAILED\n{anchor_data['reason']}"
                self.ui_color = (0, 0, 255)
                self.set_state(STATE_RESULT)
            return
            
        anchor_bbox = anchor_data["bbox"]
        is_real = anchor_data["is_real"]
        is_match = anchor_data["is_match"]
        matched_name = anchor_data["matched_name"]
        
        # ----------------------------------------------------
        # 2. Process Blink Detection Concurrently
        # ----------------------------------------------------
        results = []
        frames_done = 0
        total_frames = len(buffer_copy)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # Submit blink tasks (including frame 1 for full EAR history)
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
                        self.set_state(STATE_RESULT)
                    return
                    
                results.append(res)
                frames_done += 1
                with self.lock:
                    self.processing_progress = f"Frame {frames_done}/{total_frames}"

        # ear_log_file.close()

        if len(results) == 0:
            with self.lock:
                self.result_text = "FAILED\nNo faces found in recording!"
                self.ui_color = (0, 0, 255)
                self.set_state(STATE_RESULT)
            return

        # --- Re-sort Results by Frame Index to Recover Temporal Order ---
        results.sort(key=lambda x: x["index"])

        ear_history = []
        
        for res in results:
            ear_history.append(res["avg_ear"])
            
        # --- Peak (Valley) Detection for Blinks ---
        ear_array = np.array(ear_history)
        # We find peaks on the inverted array to find valleys
        ear_array = np.array(ear_history)
        
        # TUNING find_peaks FOR BLINKS based on your sample data:
        # Your baseline EAR is ~0.33 to 0.35. During a blink, it drops to ~0.19 to 0.24.
        # This is a drop of about 0.10 to 0.15. 
        # prominence=0.08: Must be a clear valley dropping at least 0.08 from surrounding level (avoids noise).
        # width=1: The blink must be at least 1 frame wide (filters sudden glitches).
        # distance=5: There should be at least 5 frames between separate blinks (can't blink twice instantly).
        peaks, properties = find_peaks(-ear_array, prominence=0.08, width=1, distance=5)
        blinks_detected = len(peaks)

        total_frames_processed = len(results)
        
        print(f"Results -> Real: {is_real}, Match: {is_match}, Blinks: {blinks_detected}")
        
        with self.lock:
            if is_real and is_match and blinks_detected > 0:
                self.result_text = f"VERIFIED: {matched_name}\nBlink: Detected"
                self.ui_color = (0, 255, 0)
            else:
                fail_reason = ""
                if not is_real: fail_reason += "Fake Face "
                if not is_match: fail_reason += "Mismatch Identity "
                if blinks_detected == 0: fail_reason += "No Blink "
                self.result_text = f"FAILED\n{fail_reason.strip()}"
                self.ui_color = (0, 0, 255)
            self.set_state(STATE_RESULT)


# ================= Main =================
def main():
    sys = FaceSystem()
    controller = UIController(sys)
    
    # Initialize Camera
    use_picamera = PICAMERA_AVAILABLE and platform.system() == "Linux"
    if use_picamera:
        print("Starting Picamera2...")
        picam2 = Picamera2()
        config = picam2.create_video_configuration(main={"size": (640, 480), "format": "RGB888"})
        picam2.configure(config)
        picam2.start()
    else:
        print("Starting cv2.VideoCapture (Fallback)...")
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("Running face verification module. Press 'q' to quit.")

    # Processing Thread Variables
    processing_thread = None

    try:
        while controller.running:
            if use_picamera:
                frame = picam2.capture_array()
            else:
                ret, frame = cap.read()
                if not ret: 
                    print("Failed to grab frame.")
                    break
            
            # Send to controller
            if controller.state != STATE_PROCESSING:
                controller.process_frame(frame)
            elif controller.state == STATE_PROCESSING and (processing_thread is None or not processing_thread.is_alive()):
                # Trigger processing in the background once when we enter the state
                processing_thread = threading.Thread(target=controller.run_processing_task, daemon=True)
                processing_thread.start()
            
            # Render UI
            display_img = controller.render()
            if display_img is not None:
                # If in OpenCV, BGR is expected. Both PiCam2 arrays and OpenCV default might differ.
                # Assuming standard OpenCV camera reads BGR. PiCam2 configured as RGB888.
                # if use_picamera:
                #     display_img = cv2.cvtColor(display_img, cv2.COLOR_RGB2BGR)
                    
                cv2.imshow("Face Verification Module", display_img)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                controller.running = False
                break
                
            time.sleep(0.01)
            
    finally:
        controller.running = False
        if use_picamera:
            picam2.close()
        else:
            cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
