import os, sqlite3, json, uuid, hashlib
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_from_directory
from dotenv import load_dotenv
import anthropic

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'jackspeak-secret')

ANTHROPIC_KEY = os.getenv('ANTHROPIC_API_KEY', '')
DB_PATH       = 'data/jackspeak.db'
AUDIO_DIR     = 'data/recordings'
os.makedirs(AUDIO_DIR, exist_ok=True)

CATEGORIES = ['hungry', 'greeting', 'distressed', 'bonding', 'hunting']
CATEGORY_LABELS = {
    'hungry':    'Hungry / Wants Something',
    'greeting':  'Greeting / Happy You\'re Here',
    'distressed':'Distressed / Anxious / Scared',
    'bonding':   'Contentment / Bonding',
    'hunting':   'Hunting / Prey Mode',
}

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute('''CREATE TABLE IF NOT EXISTS recordings (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        filename  TEXT NOT NULL,
        audio_ext TEXT DEFAULT 'webm',
        description TEXT,
        category  TEXT,
        confidence TEXT,
        reasoning TEXT,
        complete  INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    con.commit()
    con.close()

init_db()

def classify(description):
    if not ANTHROPIC_KEY or not description.strip():
        return None, None, None
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = f"""You are an expert in cat behavior and feline vocalization science.

A cat owner recorded their Maine Coon named Jack making a sound. Here is the owner's description of the context and sound:

"{description}"

Classify this into EXACTLY ONE of these 5 categories:
- hungry: demand vocalization, wants food, water, to go outside, or any resource
- greeting: social vocalization, happy the owner is home, positive interaction initiated by cat
- distressed: anxiety, fear, pain, loneliness, something is wrong
- bonding: contentment, closeness, trust, affection, relaxed connection with owner
- hunting: prey-directed, chirping at birds/bugs, excited by movement, predator mode

Respond with ONLY valid JSON, no markdown:
{{"category": "<one of the 5>", "confidence": "<high|medium|low>", "reasoning": "<one sentence explaining why>"}}"""

    try:
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{'role': 'user', 'content': prompt}]
        )
        data = json.loads(msg.content[0].text.strip())
        cat  = data.get('category', '').lower()
        if cat not in CATEGORIES:
            cat = 'distressed'
        return cat, data.get('confidence', 'medium'), data.get('reasoning', '')
    except Exception as e:
        return None, None, str(e)

@app.route('/')
def index():
    return render_template('record.html')

@app.route('/review')
def review():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        'SELECT * FROM recordings ORDER BY created_at DESC'
    ).fetchall()
    con.close()
    return render_template('review.html', recordings=rows, labels=CATEGORY_LABELS)

@app.route('/api/upload', methods=['POST'])
def upload():
    audio = request.files.get('audio')
    description = (request.form.get('description') or '').strip()

    if not audio:
        return jsonify({'error': 'no audio'}), 400

    ext = 'webm'
    ct = audio.content_type or ''
    if 'mp4' in ct or 'mp4a' in ct: ext = 'mp4'
    elif 'ogg' in ct: ext = 'ogg'
    elif 'wav' in ct: ext = 'wav'

    fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}"
    audio.save(os.path.join(AUDIO_DIR, fname))

    category = confidence = reasoning = None
    complete = 0

    if description:
        complete = 1
        category, confidence, reasoning = classify(description)

    con = sqlite3.connect(DB_PATH)
    cur = con.execute(
        'INSERT INTO recordings (filename, audio_ext, description, category, confidence, reasoning, complete) VALUES (?,?,?,?,?,?,?)',
        (fname, ext, description, category, confidence, reasoning, complete)
    )
    rec_id = cur.lastrowid
    con.commit()
    con.close()

    return jsonify({
        'id': rec_id,
        'category': category,
        'label': CATEGORY_LABELS.get(category, 'Unknown') if category else None,
        'confidence': confidence,
        'reasoning': reasoning,
        'complete': bool(complete)
    })

@app.route('/api/describe/<int:rec_id>', methods=['POST'])
def describe(rec_id):
    description = (request.json or {}).get('description', '').strip()
    if not description:
        return jsonify({'error': 'empty description'}), 400

    category, confidence, reasoning = classify(description)

    con = sqlite3.connect(DB_PATH)
    con.execute(
        'UPDATE recordings SET description=?, category=?, confidence=?, reasoning=?, complete=1 WHERE id=?',
        (description, category, confidence, reasoning, rec_id)
    )
    con.commit()
    con.close()

    return jsonify({
        'category': category,
        'label': CATEGORY_LABELS.get(category, 'Unknown') if category else None,
        'confidence': confidence,
        'reasoning': reasoning
    })

@app.route('/data/recordings/<path:filename>')
def serve_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)

@app.route('/api/recordings')
def recordings():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute('SELECT * FROM recordings ORDER BY created_at DESC LIMIT 50').fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/stats')
def stats():
    con = sqlite3.connect(DB_PATH)
    total    = con.execute('SELECT COUNT(*) FROM recordings').fetchone()[0]
    complete = con.execute('SELECT COUNT(*) FROM recordings WHERE complete=1').fetchone()[0]
    by_cat   = con.execute(
        'SELECT category, COUNT(*) as n FROM recordings WHERE complete=1 GROUP BY category'
    ).fetchall()
    con.close()
    return jsonify({
        'total': total,
        'complete': complete,
        'incomplete': total - complete,
        'by_category': {r[0]: r[1] for r in by_cat}
    })

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5568, debug=False)
