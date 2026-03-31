# Face Verification & Anti-Spoofing Architecture

This document provides a thorough overview of the face verification and anti-spoofing pipeline implemented in the eVoting Token Generation system.

## 1. Overview
The biometric verification process incorporates both **Passive Liveness Detection** (using Deep Learning anti-spoofing models) and **Active Liveness Detection** (using heuristic blink detection) to guarantee maximum security against presentation attacks (e.g., printed photos, screens/tablets, 3D masks). The system is designed as a state machine that guides the user through face alignment, records a short video buffer, and validates all security constraints in parallel.

## 2. Models & Libraries Used

The system utilizes three primary machine learning models, each tailored for specific sub-tasks:

### A. InsightFace (`buffalo_l` model)
- **Role**: Face Detection, Face Alignment, and Feature Extraction (Embeddings).
- **Execution**: Runs on CPU (`CPUExecutionProvider`) initialized at 640x480 resolution.
- **Why**: DeepInsight's ArcFace provides state-of-the-art accuracy for facial recognition, producing highly discriminative 512-dimensional feature vectors.
- **Threshold**: Embedded similarity matching uses a dot-product threshold of `0.45` to determine a positive match against pre-enrolled voter embeddings (`.npy` files).

### B. Silent-Face-Anti-Spoofing (MiniFASNet)
- **Role**: Passive Liveness Detection (Anti-Spoofing).
- **Execution**: Uses ensemble predictions from multiple models loaded from `./resources/anti_spoof_models`.
- **How it works**: The models analyze texture, lighting, and depth cues (like moiré patterns from screens or reflectance from photo paper) on the cropped face bounding box to classify the input as `Real` (1) or `Fake` (0).
- **Output**: Generates a confidence score. If the highest confidence corresponds to the `Real` class, passive liveness is confirmed.

### C. Dlib (`shape_predictor_68_face_landmarks.dat`)
- **Role**: Active Liveness Detection (Blink Detection).
- **Execution**: Standard frontal face detector with a 68-point facial landmark predictor.
- **How it works**: Extracts coordinates for the Left Eye (points 36-41) and Right Eye (points 42-47). These coordinates are used to calculate the **Eye Aspect Ratio (EAR)**, a reliable mathematical heuristic for detecting eye closures over a sequence of frames.

---

## 3. The Verification Pipeline (State Machine)

The UI and camera loop operate asynchronously through the following state transitions to ensure a smooth user experience.

### State 1: Detection (`STATE_DETECTION`)
The system polls the camera feed using InsightFace to locate faces. It identifies the outermost bounding box of the largest face in the frame.
- **Transition**: If a face is found, moves to `Alignment`.

### State 2: Alignment (`STATE_ALIGNMENT`)
The UI displays a bounding box and asks the user to position their face in the center of the frame.
- The user's face must fall within a strict central tolerance zone (`ALIGN_TOLERANCE` = 40% of frame width).
- **Transition**: The user must hold their face steadily inside this box for exactly **2.0 seconds**. Once completed, it moves to `Recording`. If the face leaves the box, the timer resets.

### State 3: Recording (`STATE_RECORDING`)
The system prompts the user to **BLINK**.
- It captures exactly **90 frames** (~3 seconds at 30 FPS) into an in-memory buffer.
- Real-time ML inference is paused during this phase to guarantee a high framing rate (ensuring fast blinks are not missed).
- **Transition**: After 90 frames are collected, moves to `Processing`.

### State 4: Processing (`STATE_PROCESSING`)
The 90-frame buffer is processed *offline* (in a background thread) to avoid freezing the UI. This is divided into two parts:

1. **Anchor Frame Validation**:
   - The first frame (`Anchor Frame`) is extracted. 
   - **Identity Match**: Extracted embedding is compared to the stored embedding (Must be >= 0.45).
   - **Liveness Match**: SilentFace Anti-Spoofing model processes the cropped face. Must return `Real`.
   - If either fails, the entire process is immediately forfeited.

2. **Blink Processing (Parallel)**:
   - The 90 frames are dispatched to a `ThreadPoolExecutor` (10 workers).
   - Dlib locates the face and calculates the Average EAR (Eye Aspect Ratio) for each frame.
   - If Dlib fails to find a face in any frame due to rapid motion leaving the anchor bounding box, the verification is forfeited.

3. **Peak Detection**:
   - The EAR history is plotted as an array.
   - `scipy.signal.find_peaks` is used on the negative EAR array to identify rapid dips (prominence=0.08).
   - The system counts the number of valid blinks.

### State 5 & 6: Result & Done
The final check demands:
1. `is_real == True` (Passed anti-spoofing)
2. `is_match == True` (Passed facial recognition)
3. `blinks_detected > 0` (Passed active blink test)

If all conditions are met:
- The Anchor Frame and the exact Blink Frame are saved to `./dumped_images/` as an audit trail.
- The UI triggers an `IDENTITY CONFIRMED` status, signaling the main application to proceed with Smart Card token generation.

## 4. Security Considerations
- **Concurrency**: Parallel EAR calculation minimizes the processing delay after recording.
- **Fail-Fast**: If the anchor frame is a spoof or incorrect identity, the heavy 90-frame blink calculation is skipped entirely.
- **Strict Blink Prominence**: `prominence=0.08` ensures that natural micro-fluctuations in eye shape are not incorrectly classified as deliberate blinks.
