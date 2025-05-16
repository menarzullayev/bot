import os
import base64
import datetime
import uuid
from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_session import Session
from dotenv import load_dotenv
import openai
from werkzeug.utils import secure_filename
from PIL import Image
import pytesseract
from pdf2image import convert_from_bytes
import PyPDF2
import docx
import pandas as pd
import logging

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='templates')

# Session configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'secret-key-123')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './flask_session'
app.config['SESSION_COOKIE_NAME'] = 'elektron_talim_session'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {
    'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'txt',
    'csv', 'xls', 'xlsx', 'py', 'js', 'java', 'cpp', 'zip'
}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

Session(app)

openai.api_key = os.getenv('OPENAI_API_KEY')
if not openai.api_key:
    logger.error("OPENAI_API_KEY not found in .env file!")

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
    logger.info(f"Created '{app.config['UPLOAD_FOLDER']}' directory")

if not os.path.exists(app.config['SESSION_FILE_DIR']):
    os.makedirs(app.config['SESSION_FILE_DIR'])
    logger.info(f"Created '{app.config['SESSION_FILE_DIR']}' directory")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def save_file(file):
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        try:
            file.save(filepath)
            logger.info(f"File saved: {filepath}")
            return unique_filename
        except Exception as e:
            logger.error(f"Error saving file: {e}")
            return None
    return None




def extract_text_from_file(filepath, filename):
    ext = filename.split('.')[-1].lower()
    text = ""
    try:
        if ext in ['txt', 'py', 'js', 'java', 'cpp']:
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()
        elif ext == 'docx':
            doc = docx.Document(filepath)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif ext == 'pdf':
            try:
                with open(filepath, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                if not text.strip():
                    logger.info(f"No text found in PDF, trying OCR: {filename}")
                    images = convert_from_bytes(open(filepath, 'rb').read())
                    for img in images:
                        text += pytesseract.image_to_string(img) + "\n"
            except Exception as e:
                 logger.error(f"Error reading PDF ({filename}): {e}")
                 text = f"PDF read error: {e}"

        elif ext == 'csv':
            df = pd.read_csv(filepath)
            text = f"CSV file with {len(df)} rows and {len(df.columns)} columns:\n\n"
            text += df.head().to_string()
        elif ext in ['xls', 'xlsx']:
            df = pd.read_excel(filepath)
            text = f"Excel file with {len(df)} rows and {len(df.columns)} columns:\n\n"
            text += df.head().to_string()
        elif ext == 'zip':
             text = "ZIP file uploaded. Contents not extracted."
        else:
            text = f"File type ({ext}) not supported or could not be read."

    except Exception as e:
        logger.error(f"Error reading file ({filename}): {e}")
        text = f"Error reading file: {e}"
    return text

def image_to_base64(filepath):
    try:
        with open(filepath, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            logger.info(f"Image converted to base64: {filepath}")
            return encoded_string
    except Exception as e:
        logger.error(f"Error converting image to base64 ({filepath}): {e}")
        return None

@app.route('/')
def home():
    if 'chat_history' not in session:
        session['chat_history'] = []
    return render_template('index.html', chat_history=session['chat_history'])

@app.route('/send_message', methods=['POST'])
def send_message():
    user_message = request.form.get('message')
    files = request.files.getlist('files')

    if not user_message and not files:
        return jsonify({'error': 'No message or file provided'}), 400

    if 'chat_history' not in session:
        session['chat_history'] = []

    messages_for_openai = [
        {"role": "system", "content": "You are an educational assistant chatbot. Help users with learning materials, tests, and resources."}
    ]

    for chat in session['chat_history']:
        role = 'user' if chat['type'] == 'user' else 'assistant'
        messages_for_openai.append({"role": role, "content": chat['message']})

    current_user_message_content = []

    if user_message:
        current_user_message_content.append({"type": "text", "text": user_message})

    for file in files:
        filename = save_file(file)
        if filename:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            ext = filename.split('.')[-1].lower()

            if ext in ['png', 'jpg', 'jpeg', 'gif']:
                base64_img = image_to_base64(filepath)
                if base64_img:
                    current_user_message_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/{ext};base64,{base64_img}"
                        }
                    })
                else:
                    logger.warning(f"Failed to convert image to base64: {filename}")
                    current_user_message_content.append({"type": "text", "text": f"Image upload error: {filename}"})
            else:
                content = extract_text_from_file(filepath, filename)
                current_user_message_content.append({"type": "text", "text": f"File uploaded: {filename}\nContent:\n{content[:5000]}"})

    if current_user_message_content:
         messages_for_openai.append({"role": "user", "content": current_user_message_content})

    session['chat_history'].append({
        'type': 'user',
        'message': user_message,
        'files': [],
        'timestamp': datetime.datetime.now().isoformat()
    })

    try:
        logger.info("Sending request to OpenAI API...")
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=messages_for_openai,
            max_tokens=3000
        )
        bot_response = response.choices[0].message.content
        logger.info("Received response from OpenAI API")

        session['chat_history'].append({
            'type': 'bot',
            'message': bot_response,
            'files': [],
            'timestamp': datetime.datetime.now().isoformat()
        })
        session.modified = True

        return jsonify({
            'message': bot_response,
            'files': []
        })
    except Exception as e:
        logger.error(f"OpenAI API request error: {e}")
        return jsonify({'error': f"Error connecting to chatbot: {str(e)}"}), 500

@app.route('/clear_history', methods=['POST'])
def clear_history():
    session['chat_history'] = []
    session.modified = True
    logger.info("Chat history cleared")
    return jsonify({'success': True})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    try:
        safe_filename = secure_filename(filename)
        return send_from_directory(app.config['UPLOAD_FOLDER'], safe_filename)
    except Exception as e:
        logger.error(f"Error serving file ({filename}): {e}")
        return "File not found or error occurred.", 404

if __name__ == '__main__':
    logger.info("Starting Flask application...")
    app.run(debug=True)