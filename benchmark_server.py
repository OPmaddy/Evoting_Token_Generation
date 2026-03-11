import os
import sqlite3
import pandas as pd
import numpy as np
import cv2
import insightface
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

# Constants
DB_PATH = "voters.db"
CSV_PATH = "./Electoral_Roll.csv"
EMBEDDINGS_DIR = "./embeddings"

# Initialize insightface model only once
print("Initializing InsightFace for Flask app...")
face_app = insightface.app.FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
face_app.prepare(ctx_id=0, det_size=(640, 480))


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Benchmark Registration</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 20px; background-color: #f4f4f9; display: flex; flex-direction: column; align-items: center; }
        .container { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 100%; max-width: 400px; text-align: center;}
        h2 { color: #333; margin-top: 0; }
        .form-group { margin-bottom: 20px; text-align: left; }
        label { display: block; margin-bottom: 5px; color: #555; font-weight: bold;}
        input[type="text"] { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; font-size: 16px;}
        .camera-button { position: relative; overflow: hidden; display: inline-block; width: 100%; padding: 15px 0; background-color: #4CAF50; color: white; border-radius: 8px; font-size: 18px; font-weight: bold; cursor: pointer; text-align: center; margin-bottom: 20px; border: none;}
        .camera-button input[type=file] { font-size: 100px; position: absolute; left: 0; top: 0; opacity: 0; cursor: pointer; height: 100%; }
        button[type="submit"] { background-color: #007BFF; color: white; padding: 15px; border: none; border-radius: 8px; width: 100%; font-size: 18px; font-weight: bold; cursor: pointer; transition: background 0.3s;}
        button[type="submit"]:hover { background-color: #0056b3; }
        .status { margin-top: 15px; padding: 10px; border-radius: 6px; display: none; font-weight: bold;}
        .status.success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; display: block;}
        .status.error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; display: block;}
        .preview-container { margin-bottom: 20px; text-align: center; }
        #preview { max-width: 100%; max-height: 250px; border-radius: 8px; display: none; margin: 0 auto;}
    </style>
</head>
<body>
    <div class="container">
        <h2>Register Benchmark Data</h2>
        <form id="uploadForm">
            <div class="form-group">
                <label for="name">Name</label>
                <input type="text" id="name" name="name" required placeholder="e.g. John Doe">
            </div>
            
            <div class="form-group">
                <label for="entry_number">Entry Number</label>
                <input type="text" id="entry_number" name="entry_number" required placeholder="e.g. 2022CS10001">
            </div>
            
            <div class="preview-container">
                <img id="preview" alt="Image Preview" />
            </div>

            <div class="camera-button">
                <span>Capture Photo 📷</span>
                <input type="file" id="photo" name="photo" accept="image/*" capture="environment" required>
            </div>
            
            <button type="submit" id="submitBtn">Generate Embedding</button>
        </form>
        <div id="statusMsg" class="status"></div>
    </div>

    <script>
        const photoInput = document.getElementById('photo');
        const preview = document.getElementById('preview');
        const form = document.getElementById('uploadForm');
        const statusMsg = document.getElementById('statusMsg');
        const submitBtn = document.getElementById('submitBtn');

        photoInput.addEventListener('change', function(e) {
            if (e.target.files && e.target.files[0]) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    preview.src = e.target.result;
                    preview.style.display = 'block';
                }
                reader.readAsDataURL(e.target.files[0]);
            }
        });

        form.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            submitBtn.disabled = true;
            submitBtn.textContent = 'Processing...';
            statusMsg.style.display = 'none';
            statusMsg.className = 'status';
            
            try {
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    statusMsg.textContent = result.message;
                    statusMsg.classList.add('success');
                    form.reset();
                    preview.style.display = 'none';
                } else {
                    statusMsg.textContent = result.error || 'An error occurred';
                    statusMsg.classList.add('error');
                }
            } catch (error) {
                statusMsg.textContent = 'Network error. Please try again.';
                statusMsg.classList.add('error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Generate Embedding';
            }
        });
    </script>
</body>
</html>
"""

def extract_embedding(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None, "Failed to decode image"
        
    faces = face_app.get(img)
    if not faces:
        return None, "No face found in image. Please try again with better lighting."
        
    # Get the largest face
    main_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
    return main_face.normed_embedding, None

def update_database(name, entry_number):
    try:
        entry_number_upper = entry_number.upper()
        # Ensure DB has voter table
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        # Check if exists
        cur.execute("SELECT Entry_Number FROM voters WHERE Entry_Number=?", (entry_number,))
        exists = cur.fetchone()
        
        if not exists:
            # Add to SQL DB
            cur.execute(
                "INSERT INTO voters (Entry_Number, Name, EID_Vector) VALUES (?, ?, ?)",
                (entry_number, name, "E1") # default eligibility
            )
            conn.commit()
            
            # Add to CSV
            if os.path.exists(CSV_PATH):
                df = pd.read_csv(CSV_PATH)
                if not df['Entry_Number'].astype(str).str.contains(entry_number).any():
                    new_row = {"Entry_Number": entry_number, "Name": name, "Vector of which Elections he is elidgible for": "E1"}
                    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                    df.to_csv(CSV_PATH, index=False)
                    print(f"Added {entry_number} to {CSV_PATH}")
                    
        conn.close()
        return True
    except Exception as e:
        print(f"Database update error: {e}")
        return False

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/upload', methods=['POST'])
def upload():
    try:
        name = request.form.get('name', '').strip()
        entry_number = request.form.get('entry_number', '').strip()
        photo = request.files.get('photo')
        
        if not name or not entry_number or not photo:
            return jsonify({'error': 'Missing required fields'}), 400
            
        print(f"Processing upload for {name} ({entry_number})...")
        
        # Extract embedding
        img_bytes = photo.read()
        embedding, err = extract_embedding(img_bytes)
        
        if err:
            return jsonify({'error': err}), 400
            
        # Save embedding
        os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
        emb_path = os.path.join(EMBEDDINGS_DIR, f"{entry_number}.npy")
        np.save(emb_path, embedding)
        print(f"Saved embedding to {emb_path}")
        
        # Update Electoral Roll/DB
        update_database(name, entry_number)
        
        return jsonify({'message': f'Embedding successfully generated for {entry_number}'}), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500

if __name__ == '__main__':
    # Run server on all interfaces so mobile can access it
    app.run(host='0.0.0.0', port=5000, debug=True)
