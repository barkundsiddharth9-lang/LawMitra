import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, session, send_file
from flask_cors import CORS
from openai import OpenAI
from PyPDF2 import PdfReader
from docx import Document

# Try to import OCR libraries for image text extraction
OCR_AVAILABLE = False
TESSERACT_INSTALLED = False

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
    
    # Try to set Tesseract path for Windows (common installation locations)
    if os.name == 'nt':  # Windows
        possible_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'C:\Users\{}\AppData\Local\Tesseract-OCR\tesseract.exe'.format(os.getenv('USERNAME', '')),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                TESSERACT_INSTALLED = True
                break
        
        # If not found in common paths, try to use system PATH
        if not TESSERACT_INSTALLED:
            try:
                pytesseract.get_tesseract_version()
                TESSERACT_INSTALLED = True
            except:
                TESSERACT_INSTALLED = False
    else:
        # For non-Windows, check if tesseract is in PATH
        try:
            pytesseract.get_tesseract_version()
            TESSERACT_INSTALLED = True
        except:
            TESSERACT_INSTALLED = False
            
except ImportError:
    OCR_AVAILABLE = False
    print("Warning: pytesseract or PIL not installed. Image OCR will not be available.")

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a secure key
CORS(app)

def extract_text_from_file(file_path):
    """Extract text from various file formats with error handling."""
    ext = os.path.splitext(file_path)[1].lower()
    
    try:
        if ext == '.pdf':
            try:
                reader = PdfReader(file_path)
                text = ""
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text
                if not text.strip():
                    return None, "PDF file appears to be empty or contains only images. Please ensure the PDF has selectable text."
                return text, None
            except Exception as e:
                return None, f"Error reading PDF: {str(e)}"
        
        elif ext == '.docx':
            try:
                doc = Document(file_path)
                text = ""
                for para in doc.paragraphs:
                    if para.text:
                        text += para.text + "\n"
                if not text.strip():
                    return None, "DOCX file appears to be empty."
                return text, None
            except Exception as e:
                return None, f"Error reading DOCX file: {str(e)}"
        
        elif ext == '.txt':
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                if not text.strip():
                    return None, "Text file appears to be empty."
                return text, None
            except UnicodeDecodeError:
                # Try with different encoding
                try:
                    with open(file_path, 'r', encoding='latin-1') as f:
                        text = f.read()
                    if not text.strip():
                        return None, "Text file appears to be empty."
                    return text, None
                except Exception as e:
                    return None, f"Error reading text file: {str(e)}"
            except Exception as e:
                return None, f"Error reading text file: {str(e)}"
        
        elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
            # Image file - use OCR to extract text
            if not OCR_AVAILABLE:
                return None, "Image OCR libraries not available. Please install: pip install pytesseract pillow"
            
            if not TESSERACT_INSTALLED:
                return None, "Tesseract OCR engine is not installed. Please download and install Tesseract OCR from: https://github.com/UB-Mannheim/tesseract/wiki (Windows installer). After installation, restart the server."
            
            try:
                # Open and process image
                image = Image.open(file_path)
                
                # Convert to RGB if necessary (for PNG with transparency, etc.)
                if image.mode != 'RGB':
                    image = image.convert('RGB')
                
                # Use pytesseract to extract text
                text = pytesseract.image_to_string(image, lang='eng')
                
                if not text.strip():
                    return None, "No text could be extracted from the image. Please ensure the image contains clear, readable text."
                
                return text, None
            except pytesseract.TesseractNotFoundError:
                return None, "Tesseract OCR engine not found. Please install Tesseract OCR from: https://github.com/UB-Mannheim/tesseract/wiki and restart the server."
            except Exception as e:
                return None, f"Error extracting text from image: {str(e)}"
        
        else:
            return None, f"Unsupported file type: {ext}"
    
    except Exception as e:
        return None, f"Unexpected error processing file: {str(e)}"

def initialize_messages(include_document=True):
    content = """You are an expert in Indian laws and legal documentation related to India. You only provide legal information on Indian regulations, documentation requirements, and laws.

Your expertise includes:
- Constitution of India
- Bharatiya Nyaya Sanhita (BNS)
- Indian Penal Code (IPC)
- Code of Criminal Procedure (CrPC)
- Property laws and documentation requirements
- Legal procedures and regulations
- Punishments and fines under Indian law

IMPORTANT RULES:
1. ONLY answer queries related to Indian legal frameworks, regulations, and documentation requirements.
2. If asked about documents needed for property transactions (buying flats in Pune/Mumbai, land in specific talukas, etc.), provide a detailed list of required documents.
3. If asked about punishments or fines under Indian law, provide accurate information.
4. If asked anything unrelated to Indian legal context (like who a person is, general knowledge, or topics outside Indian law), simply respond: "That's beyond my scope. I can only assist with Indian legal frameworks, regulations, and documentation requirements."
5. Focus exclusively on Indian legal documentation, property laws, regulatory requirements, and legal procedures.

Strict Formatting Instructions:
1. Use <strong>bold</strong> for legal sections, Act names, and important terms.
2. Use <ul class='styled-list'><li>...</li></ul> for lists (like document lists).
3. If explaining a process, use <ol class='styled-list'><li>...</li></ol>.
4. Separate paragraphs with <br><br>.
5. Always conclude with a bold Disclaimer: 'This is for informational purposes only. For specific legal advice, please consult a qualified attorney.'"""
    
    if include_document and 'document_text' in session and session.get('document_text'):
        content += f"\n\nUploaded Document Content:\n{session['document_text'][:2000]}"  # Limit to 2000 chars to avoid token limit
    
    return {
        "role": "system", 
        "content": content
    }
# API Configuration - Choose one:
# Option 1: OpenRouter (Recommended for better model selection)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")

# Option 2: SambaNova (Original)
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY", "ccadf396-d583-4b3b-92e1-bfbe8bf38c04")

# Use OpenRouter by default, fallback to SambaNova
USE_OPENROUTER = os.getenv("USE_OPENROUTER", "true").lower() == "true"

if USE_OPENROUTER:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
        default_headers={
            "HTTP-Referer": "http://localhost:5000",  # Optional: for tracking
            "X-Title": "Law Mitra"  # Optional: for tracking
        }
    )
    DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct"  # OpenRouter model format
else:
    client = OpenAI(
        base_url="https://api.sambanova.ai/v1",
        api_key=SAMBANOVA_API_KEY
    )
    DEFAULT_MODEL = "Meta-Llama-3.3-70B-Instruct"  # SambaNova model format

@app.route('/')
def index():
    return send_file('law_mitra.html')

@app.route('/newchat', methods=['POST'])
def new_chat():
    # Keep document text but start fresh conversation
    session['messages'] = [
        initialize_messages(include_document=True),
        {
            "role": "assistant",
            "content": "Hello! I'm Law Mitra, your AI legal assistant for Indian law. I can help you understand legal concepts, explain procedures, and provide guidance on various legal matters.<br><br>How can I assist you today?"
        }
    ]
    conversations = [msg for msg in session['messages'] if msg['role'] != 'system']
    return jsonify({"response": "New chat started.", "conversations": conversations})

@app.route('/conversations', methods=['GET'])
def get_conversations():
    if 'messages' not in session:
        return jsonify({"conversations": []})
    # Return only user and assistant messages, exclude system
    conversations = [msg for msg in session['messages'] if msg['role'] != 'system']
    return jsonify({"conversations": conversations})

@app.route('/history', methods=['GET'])
def get_history():
    """Get all conversation history with timestamps"""
    if 'conversation_history' not in session:
        session['conversation_history'] = []
    return jsonify({"history": session['conversation_history']})

@app.route('/history', methods=['POST'])
def save_to_history():
    """Save a conversation to history"""
    data = request.json
    question = data.get('question', '')
    timestamp = data.get('timestamp', datetime.now().isoformat())
    
    if 'conversation_history' not in session:
        session['conversation_history'] = []
    
    # Add to history (most recent first)
    history_item = {
        'id': str(uuid.uuid4()),
        'question': question,
        'timestamp': timestamp,
        'preview': question[:50] + '...' if len(question) > 50 else question
    }
    
    session['conversation_history'].insert(0, history_item)
    
    # Keep only last 50 conversations
    if len(session['conversation_history']) > 50:
        session['conversation_history'] = session['conversation_history'][:50]
    
    return jsonify({"success": True, "history": session['conversation_history']})

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400
        
        # Check file extension
        ext = os.path.splitext(file.filename)[1].lower()
        allowed_extensions = ['.pdf', '.docx', '.txt', '.png', '.jpg', '.jpeg', '.gif', '.bmp']
        
        if ext not in allowed_extensions:
            if ext == '.doc':
                return jsonify({"error": "Old .doc format is not supported. Please convert to .docx format."}), 400
            return jsonify({"error": f"Unsupported file type: {ext}. Supported types: PDF, DOCX, TXT, PNG, JPG, JPEG"}), 400
        
        # Save to uploads folder
        upload_folder = os.path.join(os.getcwd(), 'uploads')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        # Use secure filename to avoid path issues
        safe_filename = f"{uuid.uuid4()}_{file.filename}"
        file_path = os.path.join(upload_folder, safe_filename)
        
        try:
            file.save(file_path)
        except Exception as save_error:
            print(f"Error saving file: {str(save_error)}")
            return jsonify({"error": f"Error saving file: {str(save_error)}"}), 500
        
        # Extract text
        try:
            text, error_msg = extract_text_from_file(file_path)
            
            if error_msg:
                # Clean up the file
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except:
                        pass
                print(f"Extraction error: {error_msg}")
                return jsonify({"error": error_msg}), 400
            
            if not text or not text.strip():
                # Clean up the file
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except:
                        pass
                return jsonify({"error": "File appears to be empty or contains no extractable text."}), 400
            
            # Store document text in session
            session['document_text'] = text
            
            # Update system message if conversation exists
            if 'messages' in session and len(session['messages']) > 0:
                session['messages'][0] = initialize_messages(include_document=True)
            
            return jsonify({
                "message": f"File {file.filename} uploaded and processed successfully.",
                "filename": file.filename
            })
            
        except Exception as extract_error:
            # Clean up the file on error
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            print(f"Error extracting text: {str(extract_error)}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Error processing file: {str(extract_error)}"}), 500
            
    except Exception as e:
        print(f"Error in upload_file: {str(e)}")
        return jsonify({"error": f"Upload error: {str(e)}"}), 500

@app.route('/chat', methods=['POST'])
def chat():
    try:
        if 'messages' not in session:
            session['messages'] = [
                initialize_messages()
            ]

        user_data = request.json
        user_message = user_data.get("message")

        if not user_message:
            return jsonify({"response": "Please enter a valid message."}), 400

        # Append user message to session
        session['messages'].append({"role": "user", "content": user_message})
        
        # Save question to history
        if 'conversation_history' not in session:
            session['conversation_history'] = []
        
        history_item = {
            'id': str(uuid.uuid4()),
            'question': user_message,
            'timestamp': datetime.now().isoformat(),
            'preview': user_message[:50] + '...' if len(user_message) > 50 else user_message
        }
        session['conversation_history'].insert(0, history_item)
        
        # Keep only last 50 conversations
        if len(session['conversation_history']) > 50:
            session['conversation_history'] = session['conversation_history'][:50]

        # Use configured model (OpenRouter or SambaNova)
        try:
            completion = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=session['messages'],
                temperature=0.1, 
                max_tokens=2500
            )
            
            bot_response = completion.choices[0].message.content
            
            # Append assistant response to session
            session['messages'].append({"role": "assistant", "content": bot_response})
            
            # Limit session messages to prevent it from growing too large
            # Keep system message (first) and last 5 messages
            if len(session['messages']) > 10:
                session['messages'] = [session['messages'][0]] + session['messages'][-5:]
            
            # Markdown clean up for HTML rendering
            formatted_response = bot_response.replace('\n', '<br>')
            
            return jsonify({"response": formatted_response})
        
        except Exception as api_error:
            # Remove the user message from session since we couldn't process it
            if session['messages'] and session['messages'][-1].get('role') == 'user':
                session['messages'].pop()
            
            error_str = str(api_error)
            
            # Handle rate limit errors
            if '429' in error_str or 'rate_limit' in error_str.lower() or 'Rate limit' in error_str:
                error_message = "⏱️ Rate limit exceeded. The model is currently busy. Please wait a few moments and try again."
                print(f"Rate limit error: {error_str}")
                return jsonify({"response": error_message}), 429
            
            # Handle authentication errors
            elif '401' in error_str or 'unauthorized' in error_str.lower() or 'authentication' in error_str.lower():
                error_message = "🔐 Authentication error. Please check API credentials."
                print(f"Auth error: {error_str}")
                return jsonify({"response": error_message}), 401
            
            # Handle other API errors
            elif 'error' in error_str.lower():
                # Try to extract error message from API response
                if 'message' in error_str:
                    error_message = f"⚠️ API Error: {error_str}"
                else:
                    error_message = "⚠️ API service error. Please try again in a moment."
                print(f"API error: {error_str}")
                return jsonify({"response": error_message}), 500
            
            # Generic error
            else:
                error_message = f"⚠️ Service temporarily unavailable. Please try again in a moment."
                print(f"Unknown error: {error_str}")
                return jsonify({"response": error_message}), 500

    except Exception as e:
        # Error logging for debugging
        print(f"Error in /chat: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"response": "⚠️ An unexpected error occurred. Please try again."}), 500

if __name__ == '__main__':
    print("🚀 Law Mitra Backend starting on http://localhost:5000")
    app.run(debug=True, port=5000)