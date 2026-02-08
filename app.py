import os
import re
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, send_file, session
from flask_cors import CORS
from openai import OpenAI
from PyPDF2 import PdfReader
from docx import Document

# ==================================================================================
# 1. OCR & DEPENDENCY INITIALIZATION
# ==================================================================================
OCR_AVAILABLE = False
TESSERACT_INSTALLED = False
PYMUPDF_AVAILABLE = False

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageOps
    OCR_AVAILABLE = True
    
    if os.name == 'nt':
        tesseract_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        ]
        for path in tesseract_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                TESSERACT_INSTALLED = True
                print(f"✅ Tesseract found: {path}")
                break
        
        if not TESSERACT_INSTALLED:
            try:
                pytesseract.get_tesseract_version()
                TESSERACT_INSTALLED = True
                print("✅ Tesseract found in PATH")
            except:
                print("⚠️ Tesseract not found")
    else:
        try:
            pytesseract.get_tesseract_version()
            TESSERACT_INSTALLED = True
            print("✅ Tesseract available")
        except:
            print("⚠️ Tesseract not installed")
            
except ImportError:
    print("⚠️ pytesseract/PIL not installed")

try:
    import fitz
    PYMUPDF_AVAILABLE = True
    print("✅ PyMuPDF available")
except ImportError:
    print("⚠️ PyMuPDF not installed")

# ==================================================================================
# 2. FLASK APPLICATION SETUP
# ==================================================================================
app = Flask(__name__)
app.secret_key = 'law_mitra_2026_secure_session_key'
CORS(app, supports_credentials=True)

DOCUMENT_STORE = {}

# ==================================================================================
# 3. API CONFIGURATION
# ==================================================================================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY", "ccadf396-d583-4b3b-92e1-bfbe8bf38c04")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    default_headers={
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "Law Mitra"
    }
)

fallback_client = OpenAI(
    base_url="https://api.sambanova.ai/v1",
    api_key=SAMBANOVA_API_KEY
)

try:
    client.models.list()
    print("✅ OpenRouter API connected")
except Exception as e:
    print(f"⚠️ OpenRouter connection issue: {e}")

# ==================================================================================
# 4. DOCUMENT TEXT EXTRACTION
# ==================================================================================
def extract_text_from_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    
    try:
        # PDF PROCESSING
        if ext == '.pdf':
            try:
                reader = PdfReader(file_path)
                text = ""
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                
                # OCR fallback for scanned PDFs
                if not text.strip():
                    if OCR_AVAILABLE and TESSERACT_INSTALLED and PYMUPDF_AVAILABLE:
                        print("📄 PDF appears scanned. Attempting OCR...")
                        doc = fitz.open(file_path)
                        ocr_text = ""
                        for page_num, page in enumerate(doc):
                            try:
                                pix = page.get_pixmap(dpi=300)
                                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                                img = ImageOps.grayscale(img)
                                img = ImageEnhance.Contrast(img).enhance(2.5)
                                img = ImageEnhance.Sharpness(img).enhance(2.0)
                                
                                try:
                                    page_text = pytesseract.image_to_string(img, lang='eng+mar', config='--psm 6')
                                except:
                                    page_text = pytesseract.image_to_string(img, lang='eng', config='--psm 6')
                                
                                ocr_text += f"\n--- Page {page_num + 1} ---\n{page_text}\n"
                            except Exception as page_error:
                                print(f"OCR failed for page {page_num + 1}: {page_error}")
                                continue
                        
                        if ocr_text.strip():
                            text = ocr_text
                            print(f"✅ OCR extracted {len(text)} characters")
                    else:
                        missing = []
                        if not OCR_AVAILABLE: missing.append("pytesseract/PIL")
                        if not TESSERACT_INSTALLED: missing.append("Tesseract Engine")
                        if not PYMUPDF_AVAILABLE: missing.append("PyMuPDF")
                        return None, f"Cannot perform OCR. Missing: {', '.join(missing)}"
                
                if not text.strip():
                    return None, "PDF appears empty"
                
                return text, None
                
            except Exception as e:
                return None, f"PDF reading error: {str(e)}"
        
        # DOCX PROCESSING
        elif ext == '.docx':
            try:
                doc = Document(file_path)
                text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
                
                if not text.strip():
                    return None, "DOCX file is empty"
                
                return text, None
            except Exception as e:
                return None, f"DOCX reading error: {str(e)}"
        
        # TEXT FILE PROCESSING
        elif ext == '.txt':
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                
                if not text.strip():
                    return None, "Text file is empty"
                
                return text, None
            except UnicodeDecodeError:
                try:
                    with open(file_path, 'r', encoding='latin-1') as f:
                        text = f.read()
                    return text, None
                except Exception as e:
                    return None, f"Text file encoding error: {str(e)}"
            except Exception as e:
                return None, f"Text file error: {str(e)}"
        
        # IMAGE PROCESSING (OCR)
        elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
            if not OCR_AVAILABLE:
                return None, "OCR libraries not installed. Run: pip install pytesseract pillow"
            
            if not TESSERACT_INSTALLED:
                return None, "Tesseract OCR not installed"
            
            try:
                img = Image.open(file_path)
                
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                try:
                    img = ImageOps.grayscale(img)
                    enhancer = ImageEnhance.Contrast(img)
                    img = enhancer.enhance(2.5)
                    enhancer = ImageEnhance.Sharpness(img)
                    img = enhancer.enhance(2.0)
                    print("✅ Image preprocessing complete")
                except Exception as prep_error:
                    print(f"⚠️ Image preprocessing failed: {prep_error}")
                
                try:
                    text = pytesseract.image_to_string(img, lang='eng+mar', config='--psm 6')
                    print(f"✅ OCR (eng+mar) extracted {len(text)} characters")
                except:
                    print("⚠️ Bilingual OCR failed, falling back to English")
                    text = pytesseract.image_to_string(img, lang='eng', config='--psm 6')
                    print(f"✅ OCR (eng) extracted {len(text)} characters")
                
                if not text.strip():
                    return None, "No readable text found in image"
                
                print(f"📝 OCR Preview: {text[:200]}...")
                
                return text, None
                
            except pytesseract.TesseractNotFoundError:
                return None, "Tesseract OCR not found in system"
            except Exception as e:
                return None, f"Image OCR error: {str(e)}"
        
        else:
            return None, f"Unsupported file type: {ext}"
    
    except Exception as e:
        return None, f"File processing error: {str(e)}"

# ==================================================================================
# 5. FRAUD DETECTION ANALYZER
# ==================================================================================
def analyze_document_for_fraud(text):
    warnings = []
    
    dates = re.findall(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', text)
    if len(set(dates)) > 1:
        warnings.append("⚠️ Multiple different dates found")
    
    names = re.findall(r'\b[A-Z][a-z]{2,15}\s[A-Z][a-z]{2,15}\b', text)
    for name in names:
        if re.search(r'(.)\1{2,}', name):
            warnings.append(f"⚠️ Suspicious name pattern: '{name}'")
    
    legal_keywords = ['signature', 'seal', 'stamp', 'authorized', 'certified']
    found_keywords = [kw for kw in legal_keywords if kw.lower() in text.lower()]
    if len(found_keywords) < 2:
        warnings.append("⚠️ Document may be missing official stamps/signatures")
    
    if text.count('  ') > len(text) / 50:
        warnings.append("⚠️ Unusual spacing detected")
    
    return warnings

# ==================================================================================
# 6. SYSTEM PROMPT BUILDER
# ==================================================================================
def initialize_messages(session_id=None, user_name=None):
    doc_text = ""
    fraud_warnings = []
    
    if session_id and session_id in DOCUMENT_STORE:
        doc_data = DOCUMENT_STORE[session_id]
        doc_text = doc_data.get('text', '')
        fraud_warnings = doc_data.get('fraud_warnings', [])
        print(f"🔍 System prompt building WITH document ({len(doc_text)} chars)")
    else:
        print(f"🔍 System prompt building WITHOUT document")
    
    system_content = f"""You are **LAW MITRA** – An intelligent Indian Legal Information Assistant.

**YOUR IDENTITY:**
- Your name: Law Mitra (लॉ मित्र)
- User's name: {user_name if user_name else "User"}
- Language: Respond in English, use Marathi for complex legal terms

**CRITICAL MEMORY INSTRUCTION:**
- You have access to the LAST 100 QUESTIONS in this conversation
- Always check previous questions before answering
- Remember names, dates, and details mentioned

**GLOBAL EXECUTION PRIORITY:**

═══════════════════════════════════════════════════════════════
🔴 PRIORITY #1: DOCUMENT MODE (HIGHEST PRIORITY)
═══════════════════════════════════════════════════════════════

When a document is uploaded, you MUST:

1. **IMMEDIATE UNDERSTANDING:**
   - Read and comprehend the entire document
   - Do NOT refuse analysis based on topic or sensitivity
   - Applies to: Legal docs, certificates, contracts, letters, etc.

2. **RESPONSE FORMAT - CRITICAL RULES:**
   
   **For SIMPLE questions (name, date, single fact):**
   - Use: <b>Label:</b> Value
   - Examples:
     * "name" → "<b>Name:</b> Rajendra Shinde"
     * "date of birth" → "<b>Date of Birth:</b> 25/08/1983"
   
   **For SUMMARY or DETAILED EXPLANATION:**
   - Use HTML: <b>Bold</b> for headings, <br> for line breaks, <br><br> for paragraphs
   - Structure with sections:
     * <b>विषय (Subject):</b><br>
     * <b>महत्वाची माहिती (Key Details):</b><br>
     * <b>उद्देश (Purpose):</b><br>
     * <b>कायदेशीर संदर्भ (Legal Context):</b><br>

3. **FRAUD DETECTION:**
   - Check for date mismatches, name inconsistencies, missing stamps
   - Warn user if fraud indicators found

4. **ANSWERING QUESTIONS:**
   - Answer ONLY from document content
   - If info not in document: "दस्तऐवजात [X] बद्दल माहिती नाही।"
   - Never fabricate or guess

═══════════════════════════════════════════════════════════════
🟡 PRIORITY #2: INDIAN LAW CONSULTATION MODE (No Document)
═══════════════════════════════════════════════════════════════

When NO document:
- Answer ONLY Indian law questions
- Topics: Criminal, Civil, Family, Property law, etc.
- Use simple language with Marathi translations

═══════════════════════════════════════════════════════════════
📄 CURRENT SESSION DOCUMENT
═══════════════════════════════════════════════════════════════
"""

    if doc_text:
        system_content += f"""
**DOCUMENT STATUS:** ✅ Uploaded and Active

**FRAUD CHECK RESULTS:**
{chr(10).join(fraud_warnings) if fraud_warnings else "✅ No obvious fraud indicators detected"}

**DOCUMENT CONTENT:**
{doc_text[:45000]}

**END OF DOCUMENT**
═══════════════════════════════════════════════════════════════

You are now in DOCUMENT MODE. Follow Priority #1 rules strictly.
"""
    else:
        system_content += """
**DOCUMENT STATUS:** ❌ No document uploaded

You are in INDIAN LAW CONSULTATION MODE. Follow Priority #2 rules.
═══════════════════════════════════════════════════════════════
"""

    return {"role": "system", "content": system_content}

# ==================================================================================
# 7. FLASK ROUTES
# ==================================================================================

@app.route('/')
def index():
    return send_file('law_mitra.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        ext = os.path.splitext(file.filename)[1].lower()
        allowed_extensions = ['.pdf', '.docx', '.txt', '.png', '.jpg', '.jpeg', '.gif', '.bmp']
        
        if ext not in allowed_extensions:
            if ext == '.doc':
                return jsonify({"error": "Old .doc format not supported. Please convert to .docx"}), 400
            return jsonify({"error": f"Unsupported file type: {ext}"}), 400
        
        # Session management
        if 'session_id' not in session:
            session['session_id'] = str(uuid.uuid4())
        
        session_id = session['session_id']
        
        # Save file temporarily
        upload_dir = os.path.join(os.getcwd(), 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        
        safe_filename = f"{uuid.uuid4()}_{file.filename}"
        file_path = os.path.join(upload_dir, safe_filename)
        
        try:
            file.save(file_path)
        except Exception as save_error:
            return jsonify({"error": f"File save error: {str(save_error)}"}), 500
        
        # Extract text
        try:
            text, error_msg = extract_text_from_file(file_path)
            
            # Clean up file
            try:
                os.remove(file_path)
            except:
                pass
            
            if error_msg:
                return jsonify({"error": error_msg}), 400
            
            if not text or not text.strip():
                return jsonify({"error": "No extractable text found in file"}), 400
            
            # Fraud detection
            fraud_warnings = analyze_document_for_fraud(text)
            
            # Store in server memory
            DOCUMENT_STORE[session_id] = {
                'text': text,
                'filename': file.filename,
                'upload_time': datetime.now().isoformat(),
                'fraud_warnings': fraud_warnings
            }
            
            # ✅ CRITICAL FIX: Reset session messages WITH document context
            user_name = session.get('user_name')
            session['messages'] = [
                initialize_messages(session_id=session_id, user_name=user_name)
            ]
            session.modified = True
            
            print(f"✅ Document stored for session {session_id} ({len(text)} chars)")
            print(f"✅ Session messages reset with document context")
            
            response_data = {
                "message": f"File '{file.filename}' processed successfully",
                "filename": file.filename,
                "text_length": len(text),
                "fraud_warnings": fraud_warnings
            }
            
            return jsonify(response_data)
            
        except Exception as extract_error:
            try:
                os.remove(file_path)
            except:
                pass
            
            print(f"Extraction error: {str(extract_error)}")
            import traceback
            traceback.print_exc()
            
            return jsonify({"error": f"Processing error: {str(extract_error)}"}), 500
            
    except Exception as e:
        print(f"Upload error: {str(e)}")
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500

@app.route('/chat', methods=['POST'])
def chat():
    try:
        # Session initialization
        if 'session_id' not in session:
            session['session_id'] = str(uuid.uuid4())
        
        session_id = session['session_id']
        user_name = session.get('user_name')
        
        # ✅ DEBUG: Check if document exists
        has_document = session_id in DOCUMENT_STORE
        print(f"📊 Session ID: {session_id}")
        print(f"📄 Document available: {has_document}")
        if has_document:
            doc_info = DOCUMENT_STORE[session_id]
            print(f"📝 Document: {doc_info['filename']} ({len(doc_info['text'])} chars)")
        
        # Initialize or refresh messages
        if 'messages' not in session:
            session['messages'] = [initialize_messages(session_id=session_id, user_name=user_name)]
        else:
            # ✅ FIX: Refresh system prompt
            session['messages'][0] = initialize_messages(session_id=session_id, user_name=user_name)
            print(f"✅ System prompt refreshed with document context")
        
        # Get user message
        data = request.json
        user_message = data.get("message", "").strip()
        
        if not user_message:
            return jsonify({"response": "Please enter a message."}), 400
        
        # Identity detection
        name_match = re.search(r"(?:i am|my name is|maz nav|mi)\s+([a-zA-Z]+)", user_message.lower())
        if name_match:
            detected_name = name_match.group(1).capitalize()
            ignored_words = ['looking', 'searching', 'asking', 'law', 'mitra', 'bot', 'ai']
            
            if detected_name.lower() not in ignored_words:
                session['user_name'] = detected_name
                session.modified = True
                print(f"✅ User identified: {detected_name}")
        
        # Append user message
        session['messages'].append({"role": "user", "content": user_message})
        
        # Save to conversation history
        if 'conversation_history' not in session:
            session['conversation_history'] = []
        
        history_entry = {
            'id': str(uuid.uuid4()),
            'question': user_message,
            'timestamp': datetime.now().isoformat(),
            'preview': user_message[:60] + '...' if len(user_message) > 60 else user_message
        }
        
        session['conversation_history'].insert(0, history_entry)
        
        if len(session['conversation_history']) > 100:
            session['conversation_history'] = session['conversation_history'][:100]
        
        # API call with fallback
        bot_response = None
        
        try:
            # Primary: OpenRouter
            completion = client.chat.completions.create(
                model="meta-llama/llama-3.3-70b-instruct",
                messages=session['messages'],
                temperature=0.3,
                max_tokens=2500,
                top_p=0.9
            )
            bot_response = completion.choices[0].message.content
            print("✅ Response from OpenRouter")
            
        except Exception as primary_error:
            print(f"⚠️ OpenRouter failed: {primary_error}")
            print("🔄 Attempting SambaNova fallback...")
            
            try:
                # Fallback: SambaNova
                completion = fallback_client.chat.completions.create(
                    model="Meta-Llama-3.3-70B-Instruct",
                    messages=session['messages'],
                    temperature=0.3,
                    max_tokens=2500
                )
                bot_response = completion.choices[0].message.content
                print("✅ Response from SambaNova (fallback)")
                
            except Exception as fallback_error:
                print(f"❌ Both APIs failed. OpenRouter: {primary_error}, SambaNova: {fallback_error}")
                return jsonify({
                    "response": "⚠️ AI service temporarily unavailable. Please try again."
                }), 503
        
        # Success - save response
        if bot_response:
            session['messages'].append({"role": "assistant", "content": bot_response})
            
            # Prune conversation if too long
            if len(session['messages']) > 100:
                system_msg = session['messages'][0]
                recent_msgs = session['messages'][-99:]
                session['messages'] = [system_msg] + recent_msgs
            
            session.modified = True
            
            return jsonify({"response": bot_response})
        else:
            return jsonify({"response": "⚠️ No response generated."}), 500
            
    except Exception as e:
        print(f"❌ Chat error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"response": "⚠️ Server error. Please refresh and try again."}), 500

@app.route('/newchat', methods=['POST'])
def new_chat():
    try:
        session_id = session.get('session_id')
        user_name = session.get('user_name')
        
        # Reset messages but keep document
        session['messages'] = [
            initialize_messages(session_id=session_id, user_name=user_name)
        ]
        session.modified = True
        
        conversations = [msg for msg in session['messages'] if msg['role'] != 'system']
        
        return jsonify({
            "response": "New chat started",
            "conversations": conversations
        })
        
    except Exception as e:
        print(f"New chat error: {e}")
        return jsonify({"error": "Failed to start new chat"}), 500

@app.route('/conversations', methods=['GET'])
def get_conversations():
    if 'messages' not in session:
        return jsonify({"conversations": []})
    
    conversations = [msg for msg in session['messages'] if msg['role'] != 'system']
    return jsonify({"conversations": conversations})

@app.route('/history', methods=['GET'])
def get_history():
    if 'conversation_history' not in session:
        session['conversation_history'] = []
    
    return jsonify({"history": session['conversation_history']})

@app.route('/clear_document', methods=['POST'])
def clear_document():
    try:
        session_id = session.get('session_id')
        
        if session_id and session_id in DOCUMENT_STORE:
            del DOCUMENT_STORE[session_id]
            print(f"✅ Document cleared for session {session_id}")
        
        user_name = session.get('user_name')
        session['messages'] = [initialize_messages(session_id=session_id, user_name=user_name)]
        session.modified = True
        
        return jsonify({"message": "Document cleared successfully"})
        
    except Exception as e:
        print(f"Clear document error: {e}")
        return jsonify({"error": "Failed to clear document"}), 500

@app.route('/status', methods=['GET'])
def status():
    session_id = session.get('session_id', 'None')
    has_document = session_id in DOCUMENT_STORE if session_id else False
    
    return jsonify({
        "status": "online",
        "ocr_available": OCR_AVAILABLE and TESSERACT_INSTALLED,
        "pymupdf_available": PYMUPDF_AVAILABLE,
        "session_id": session_id,
        "document_uploaded": has_document,
        "user_name": session.get('user_name', 'Not set'),
        "message_count": len(session.get('messages', [])),
        "api_primary": "OpenRouter",
        "api_fallback": "SambaNova"
    })

# ==================================================================================
# 8. APPLICATION ENTRY POINT
# ==================================================================================
if __name__ == '__main__':
    print("=" * 70)
    print("🚀 LAW MITRA BACKEND SERVER")
    print("=" * 70)
    print(f"✅ Server starting on: http://localhost:5000")
    print(f"✅ OCR Available: {OCR_AVAILABLE and TESSERACT_INSTALLED}")
    print(f"✅ PDF OCR Available: {PYMUPDF_AVAILABLE}")
    print(f"✅ Primary API: OpenRouter")
    print(f"✅ Fallback API: SambaNova")
    print("=" * 70)
    
    app.run(debug=True, port=5000, host='0.0.0.0')
