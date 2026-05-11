import os, sqlite3, json, uuid
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from flask import Flask, render_template, jsonify, request, send_from_directory, redirect, url_for
from dotenv import load_dotenv
import anthropic

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'jackspeak-secret')

ANTHROPIC_KEY = os.getenv('ANTHROPIC_API_KEY', '')
DB_PATH   = 'data/jackspeak.db'
AUDIO_DIR = 'data/recordings'
PHOTO_DIR = 'data/photos'
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)

# ── Audio classification taxonomy ────────────────────────────────────────────

CATEGORIES = ['request', 'social', 'stress', 'discomfort', 'unusual']

CATEGORY_LABELS = {
    'request':    'Request / Wants Something',
    'social':     'Social / Communication',
    'stress':     'Stress / Anxiety',
    'discomfort': 'Discomfort / Health Concern',
    'unusual':    'Unusual / Unknown',
}

DETAIL_TAGS = {
    'request':    ['hungry', 'wants treats', 'wants water', 'wants attention', 'wants play',
                   'wants door opened', 'wants outside', 'wants lap', 'wants to be followed'],
    'social':     ['greeting', 'checking in', 'talking back', 'following owner',
                   'trilling', 'chirping', 'affectionate', 'normal chit-chat'],
    'stress':     ['scared', 'hiding', 'overstimulated', 'loud noise', 'new person',
                   'new pet', 'car ride', 'vet stress', 'doorbell', 'owner leaving'],
    'discomfort': ['pain concern', 'litter box concern', 'crying near litter', 'straining',
                   'limping', 'restlessness', 'not eating', 'vomiting', 'weak meow',
                   'unusual yowl', 'urgent concern'],
    'unusual':    ['new sound', 'night yowling', 'repeated meow', 'long yowl', 'low moan',
                   'high pitch', 'more vocal than usual', 'less vocal than usual',
                   'different than normal', 'not sure'],
}

GLOBAL_CONTEXT = [
    'morning', 'afternoon', 'night',
    'before food', 'after food',
    'near food bowl', 'near water bowl', 'near litter box',
    'near door', 'near window',
    'owner leaving', 'owner returning',
    'other pet nearby', 'new person', 'loud noise',
    'normal for this cat', 'unusual for this cat',
    'not sure', 'worth watching',
]

# ── Photo / visual observation taxonomy ──────────────────────────────────────

PHOTO_CATEGORIES = ['face', 'posture', 'movement', 'body_condition', 'environment']

PHOTO_CATEGORY_LABELS = {
    'face':           'Face / Expression',
    'posture':        'Posture / Body Language',
    'movement':       'Movement / Activity',
    'body_condition': 'Body Condition',
    'environment':    'Environment / Location',
}

PHOTO_DETAIL_TAGS = {
    'face': ['ears forward', 'ears sideways', 'ears flat', 'big pupils', 'squinting',
             'slow blink', 'wide eyes', 'whiskers forward', 'whiskers back',
             'tense face', 'relaxed face'],
    'posture': ['tail up', 'tail low', 'tail tucked', 'tail puffed', 'tail twitching',
                'crouched', 'arched back', 'loafing', 'stretched out', 'curled up', 'tense body'],
    'movement': ['pacing', 'restless', 'limping', 'jumping less', 'moving slowly',
                 'hiding', 'following owner', 'playful', 'lethargic',
                 'cannot get comfortable', 'avoiding contact'],
    'body_condition': ['overgrooming', 'not grooming', 'matted fur', 'hair loss',
                       'scratching', 'licking one spot', 'drooling', 'eye discharge',
                       'nose discharge', 'swelling', 'weight change', 'injury concern'],
    'environment': ['near food bowl', 'near water bowl', 'near litter box', 'at door',
                    'at window', 'under bed', 'new object', 'other pet nearby',
                    'loud room', 'owner leaving', 'owner returning', 'storm', 'vacuum', 'car ride'],
}

# ── Owner rating ─────────────────────────────────────────────────────────────

OWNER_RATINGS = ['normal', 'a_little_unusual', 'very_unusual', 'not_sure']

OWNER_RATING_LABELS = {
    'normal':          'Normal for them',
    'a_little_unusual':'A little unusual',
    'very_unusual':    'Very unusual',
    'not_sure':        'Not sure',
}

# ── Concern rules ─────────────────────────────────────────────────────────────

CONCERN_RULES = [
    (['litter box concern', 'crying near litter', 'straining', 'near litter box'],
     48, 3,
     'Repeated litter box signals in the last 48 hours. Worth monitoring closely — if this continues, consider a vet check.'),
    (['night yowling', 'unusual yowl', 'long yowl'],
     72, 3,
     'Increased unusual or nighttime yowling. This can signal pain, cognitive changes, or anxiety. Worth watching.'),
    (['not eating'],
     24, 1,
     'Not eating was flagged. If this continues past 24 hours, contact your vet.'),
    (['pain concern', 'urgent concern'],
     48, 1,
     'A pain or urgent concern was flagged. If your cat seems distressed or struggling — contact a vet.'),
    (['weak meow'],
     48, 2,
     'Weak meow flagged more than once. Worth monitoring alongside other changes.'),
    (['hiding', 'overstimulated'],
     24, 3,
     'Repeated hiding or stress signals in 24 hours. Cats withdraw when unwell or very anxious.'),
    (['limping', 'injury concern'],
     72, 1,
     'Limping or injury concern was flagged. A vet exam is recommended if this persists.'),
    (['vomiting'],
     24, 2,
     'Multiple vomiting events flagged in 24 hours. Contact your vet if this continues.'),
]

# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = get_db()
    con.execute('''CREATE TABLE IF NOT EXISTS cats (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        name           TEXT NOT NULL,
        age_years      REAL,
        breed          TEXT,
        indoor_outdoor TEXT DEFAULT 'indoor',
        health_notes   TEXT,
        vocal_notes    TEXT,
        created_at     TEXT DEFAULT (datetime('now'))
    )''')
    con.execute('''CREATE TABLE IF NOT EXISTS recordings (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        cat_id         INTEGER REFERENCES cats(id),
        filename       TEXT,
        audio_ext      TEXT DEFAULT 'webm',
        photo_path     TEXT,
        description    TEXT,
        category       TEXT,
        detail_tags    TEXT DEFAULT '[]',
        global_context TEXT DEFAULT '[]',
        photo_category TEXT,
        photo_tags     TEXT DEFAULT '[]',
        confidence     TEXT,
        reasoning      TEXT,
        user_feedback  TEXT,
        owner_rating   TEXT,
        owner_note     TEXT,
        complete       INTEGER DEFAULT 0,
        created_at     TEXT DEFAULT (datetime('now'))
    )''')
    cols = [r[1] for r in con.execute("PRAGMA table_info(recordings)").fetchall()]
    for col, defn in [
        ('cat_id',         'INTEGER'),
        ('photo_path',     'TEXT'),
        ('detail_tags',    "TEXT DEFAULT '[]'"),
        ('global_context', "TEXT DEFAULT '[]'"),
        ('photo_category', 'TEXT'),
        ('photo_tags',     "TEXT DEFAULT '[]'"),
        ('user_feedback',  'TEXT'),
        ('owner_rating',   'TEXT'),
        ('owner_note',     'TEXT'),
    ]:
        if col not in cols:
            con.execute(f'ALTER TABLE recordings ADD COLUMN {col} {defn}')
    con.commit()
    con.close()

init_db()


def classify(description, cat_name='your cat'):
    if not ANTHROPIC_KEY or not description.strip():
        return None, None, None
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = f"""You are a feline behavior expert helping an owner keep a behavioral journal for their cat named {cat_name}.

The owner described what their cat was doing:

"{description}"

Classify into EXACTLY ONE of these 5 categories:
- request: wants food, water, attention, play, door, outside, lap
- social: greeting, affection, trilling, normal positive communication
- stress: anxiety, fear, new person/pet/noise, car ride, vet stress
- discomfort: pain signals, litter concern, weak meow, not eating, vomiting, limping
- unusual: owner notices something different, hard to place, new or changed pattern

Be honest. If unsure, choose unusual with low confidence. This is a journal entry — accuracy matters more than confidence.

Respond with ONLY valid JSON, no markdown:
{{"category": "<one of the 5>", "confidence": "<high|medium|low>", "reasoning": "<one plain sentence — honest best guess with why. Do not say 'your cat wants X' — say 'this sounds like X based on the description'>"}}"""
    try:
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{'role': 'user', 'content': prompt}]
        )
        data = json.loads(msg.content[0].text.strip())
        cat  = data.get('category', '').lower()
        if cat not in CATEGORIES:
            cat = 'unusual'
        return cat, data.get('confidence', 'medium'), data.get('reasoning', '')
    except Exception as e:
        return None, None, str(e)


def parse_tags(row, field):
    try:
        return json.loads(row[field] or '[]')
    except Exception:
        return []


def enrich(rows):
    result = []
    for r in rows:
        d = dict(r)
        d['detail_tags']    = parse_tags(r, 'detail_tags')
        d['global_context'] = parse_tags(r, 'global_context')
        d['photo_tags']     = parse_tags(r, 'photo_tags')
        result.append(d)
    return result


def get_concern_flags(cat_id):
    flags = []
    for patterns, window_h, threshold, message in CONCERN_RULES:
        cutoff = (datetime.now() - timedelta(hours=window_h)).strftime('%Y-%m-%d %H:%M:%S')
        con = get_db()
        rows = con.execute(
            'SELECT detail_tags, global_context, photo_tags FROM recordings WHERE cat_id=? AND created_at>?',
            (cat_id, cutoff)
        ).fetchall()
        con.close()
        count = 0
        for r in rows:
            tags = (parse_tags(r, 'detail_tags') + parse_tags(r, 'global_context') +
                    parse_tags(r, 'photo_tags'))
            if any(p in tags for p in patterns):
                count += 1
        if count >= threshold:
            flags.append(message)
    return flags


def pattern_summary(cat_id, days=7):
    """Return a dict of pattern counts for the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    con = get_db()
    rows = con.execute(
        'SELECT detail_tags, global_context, photo_tags, owner_rating, category, created_at FROM recordings WHERE cat_id=? AND created_at>?',
        (cat_id, cutoff)
    ).fetchall()
    con.close()

    patterns = {
        'total': len(rows),
        'unusual_flagged': 0,
        'very_unusual': 0,
        'night_vocalizations': 0,
        'litter_events': 0,
        'food_events': 0,
        'discomfort_events': 0,
        'by_category': Counter(),
    }

    litter_tags = {'litter box concern', 'crying near litter', 'straining', 'near litter box'}
    food_tags   = {'hungry', 'before food', 'after food', 'near food bowl', 'near water bowl', 'not eating'}

    for r in rows:
        all_tags = (parse_tags(r, 'detail_tags') + parse_tags(r, 'global_context') +
                    parse_tags(r, 'photo_tags'))
        if 'unusual for this cat' in all_tags or r['owner_rating'] in ('a_little_unusual', 'very_unusual'):
            patterns['unusual_flagged'] += 1
        if r['owner_rating'] == 'very_unusual':
            patterns['very_unusual'] += 1
        if 'night' in all_tags or 'night yowling' in all_tags:
            patterns['night_vocalizations'] += 1
        if litter_tags & set(all_tags):
            patterns['litter_events'] += 1
        if food_tags & set(all_tags):
            patterns['food_events'] += 1
        if r['category'] == 'discomfort':
            patterns['discomfort_events'] += 1
        if r['category']:
            patterns['by_category'][r['category']] += 1

    return patterns


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    con = get_db()
    cats = [dict(c) for c in con.execute('SELECT id, name FROM cats ORDER BY name').fetchall()]
    con.close()
    return render_template('record.html', cats=cats,
                           detail_tags=DETAIL_TAGS, global_context=GLOBAL_CONTEXT,
                           category_labels=CATEGORY_LABELS, categories=CATEGORIES,
                           photo_categories=PHOTO_CATEGORIES,
                           photo_category_labels=PHOTO_CATEGORY_LABELS,
                           photo_detail_tags=PHOTO_DETAIL_TAGS,
                           owner_ratings=OWNER_RATINGS,
                           owner_rating_labels=OWNER_RATING_LABELS)


@app.route('/cats')
def cats_page():
    con = get_db()
    cats = con.execute('''
        SELECT c.*, COUNT(r.id) as rec_count
        FROM cats c LEFT JOIN recordings r ON r.cat_id=c.id
        GROUP BY c.id ORDER BY c.name
    ''').fetchall()
    con.close()
    return render_template('cats.html', cats=[dict(c) for c in cats])


@app.route('/cats/<int:cat_id>')
def cat_profile(cat_id):
    con = get_db()
    cat = con.execute('SELECT * FROM cats WHERE id=?', (cat_id,)).fetchone()
    if not cat:
        return redirect(url_for('cats_page'))
    rows = con.execute(
        'SELECT * FROM recordings WHERE cat_id=? ORDER BY created_at DESC LIMIT 100',
        (cat_id,)
    ).fetchall()
    con.close()

    recordings = enrich(rows)

    all_tags = []
    for r in recordings:
        all_tags += r['detail_tags'] + r['global_context'] + r['photo_tags']
    common_tags = [t for t, _ in Counter(all_tags).most_common(10)]

    cutoff_7d = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    unusual_tags = []
    for r in recordings:
        if r['created_at'] >= cutoff_7d and (
            'unusual for this cat' in r['global_context'] or
            r.get('owner_rating') in ('a_little_unusual', 'very_unusual')
        ):
            unusual_tags += r['detail_tags'] + r['photo_tags']
            unusual_tags += [t for t in r['global_context']
                             if t not in ('unusual for this cat', 'normal for this cat')]
    unusual_recent = list(dict.fromkeys(unusual_tags))[:8]

    journal = defaultdict(list)
    for r in recordings:
        journal[r['created_at'][:10]].append(r)
    journal = dict(sorted(journal.items(), reverse=True))

    patterns = pattern_summary(cat_id, days=7)

    return render_template('cat_profile.html',
        cat=dict(cat),
        journal=journal,
        common_tags=common_tags,
        unusual_recent=unusual_recent,
        concerns=get_concern_flags(cat_id),
        category_labels=CATEGORY_LABELS,
        rating_labels=OWNER_RATING_LABELS,
        total_recordings=len(recordings),
        patterns=patterns,
    )


@app.route('/cats/<int:cat_id>/report')
def vet_report(cat_id):
    con = get_db()
    cat = con.execute('SELECT * FROM cats WHERE id=?', (cat_id,)).fetchone()
    if not cat:
        return redirect(url_for('cats_page'))
    rows = con.execute(
        'SELECT * FROM recordings WHERE cat_id=? ORDER BY created_at ASC',
        (cat_id,)
    ).fetchall()
    con.close()

    recordings = enrich(rows)

    period_start = recordings[0]['created_at'][:10] if recordings else None
    period_end   = recordings[-1]['created_at'][:10] if recordings else None

    by_cat = Counter(r['category'] for r in recordings if r['category'])

    litter_tags = {'litter box concern', 'crying near litter', 'straining',
                   'near litter box', 'litter box concern'}
    food_tags   = {'hungry', 'before food', 'after food', 'near food bowl',
                   'near water bowl', 'not eating'}
    behav_tags  = {'hiding', 'limping', 'pacing', 'restless', 'lethargic',
                   'overgrooming', 'not grooming', 'injury concern', 'avoiding contact'}

    litter_events = [r for r in recordings
                     if litter_tags & set(r['detail_tags'] + r['global_context'] + r['photo_tags'])]
    food_events   = [r for r in recordings
                     if food_tags & set(r['detail_tags'] + r['global_context'] + r['photo_tags'])]
    behav_events  = [r for r in recordings
                     if behav_tags & set(r['detail_tags'] + r['global_context'] + r['photo_tags'])]

    unusual_events = [r for r in recordings
                      if r.get('owner_rating') in ('very_unusual', 'a_little_unusual') or
                         'unusual for this cat' in r['global_context']]

    # Time-of-day breakdown
    by_time = Counter()
    for r in recordings:
        if r.get('created_at'):
            h = int(r['created_at'][11:13])
            if 5 <= h < 12:   by_time['morning'] += 1
            elif 12 <= h < 18: by_time['afternoon'] += 1
            elif 18 <= h < 22: by_time['evening'] += 1
            else:              by_time['night'] += 1

    concerns = get_concern_flags(cat_id)

    # Suggested vet questions
    vet_questions = []
    if litter_events:
        vet_questions.append("Have you noticed any changes that might indicate a litter box or urinary issue?")
    if any('not eating' in r['detail_tags'] + r['global_context'] for r in recordings):
        vet_questions.append("We noticed appetite changes — is the current diet and feeding routine appropriate?")
    if any('limping' in r['detail_tags'] + r['photo_tags'] for r in recordings):
        vet_questions.append("We observed possible limping or movement difficulty — should this be examined?")
    if any(r.get('owner_rating') == 'very_unusual' for r in recordings):
        vet_questions.append("Several behaviors were flagged as 'very unusual' — please review the timeline.")
    if any('night yowling' in r['detail_tags'] or 'long yowl' in r['detail_tags'] for r in recordings):
        vet_questions.append("There was increased nighttime or unusual yowling — could this signal pain or cognitive changes?")
    if any('weak meow' in r['detail_tags'] for r in recordings):
        vet_questions.append("We noticed a weaker-than-normal meow at times — is this worth evaluating?")
    if concerns:
        vet_questions.append("The app flagged some behavioral patterns. Are any of these medically relevant?")
    if not vet_questions:
        vet_questions.append("Are there any routine health checks appropriate for their age and breed?")

    # Recent 14-day journal for the report
    cutoff_14 = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d %H:%M:%S')
    recent = [r for r in reversed(recordings) if r['created_at'] >= cutoff_14]
    recent_journal = defaultdict(list)
    for r in recent:
        recent_journal[r['created_at'][:10]].append(r)
    recent_journal = dict(sorted(recent_journal.items(), reverse=True))

    return render_template('vet_report.html',
        cat=dict(cat),
        period_start=period_start,
        period_end=period_end,
        total=len(recordings),
        by_cat=dict(by_cat),
        unusual_events=unusual_events,
        litter_events=litter_events,
        food_events=food_events,
        behav_events=behav_events,
        by_time=dict(by_time),
        concerns=concerns,
        vet_questions=vet_questions,
        recent_journal=recent_journal,
        category_labels=CATEGORY_LABELS,
        rating_labels=OWNER_RATING_LABELS,
        generated=datetime.now().strftime('%B %d, %Y'),
    )


@app.route('/review')
def review():
    con = get_db()
    rows = con.execute('''
        SELECT r.*, c.name as cat_name
        FROM recordings r LEFT JOIN cats c ON c.id=r.cat_id
        ORDER BY r.created_at DESC
    ''').fetchall()
    con.close()
    return render_template('review.html', recordings=enrich(rows),
                           labels=CATEGORY_LABELS, rating_labels=OWNER_RATING_LABELS)


@app.route('/data/recordings/<path:filename>')
def serve_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)


@app.route('/data/photos/<path:filename>')
def serve_photo(filename):
    return send_from_directory(PHOTO_DIR, filename)


# ─── API ─────────────────────────────────────────────────────────────────────

@app.route('/api/cats', methods=['GET'])
def api_cats():
    con = get_db()
    cats = [dict(c) for c in con.execute('SELECT * FROM cats ORDER BY name').fetchall()]
    con.close()
    return jsonify(cats)


@app.route('/api/cats', methods=['POST'])
def api_create_cat():
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    con = get_db()
    cur = con.execute(
        'INSERT INTO cats (name, age_years, breed, indoor_outdoor, health_notes, vocal_notes) VALUES (?,?,?,?,?,?)',
        (name,
         data.get('age_years') or None,
         (data.get('breed') or '').strip() or None,
         data.get('indoor_outdoor', 'indoor'),
         (data.get('health_notes') or '').strip() or None,
         (data.get('vocal_notes') or '').strip() or None)
    )
    cat_id = cur.lastrowid
    con.commit()
    cat = dict(con.execute('SELECT * FROM cats WHERE id=?', (cat_id,)).fetchone())
    con.close()
    return jsonify(cat)


@app.route('/api/cats/<int:cat_id>', methods=['POST'])
def api_update_cat(cat_id):
    data = request.json or {}
    con = get_db()
    con.execute(
        'UPDATE cats SET name=?, age_years=?, breed=?, indoor_outdoor=?, health_notes=?, vocal_notes=? WHERE id=?',
        ((data.get('name') or '').strip(),
         data.get('age_years') or None,
         (data.get('breed') or '').strip() or None,
         data.get('indoor_outdoor', 'indoor'),
         (data.get('health_notes') or '').strip() or None,
         (data.get('vocal_notes') or '').strip() or None,
         cat_id)
    )
    con.commit()
    cat = dict(con.execute('SELECT * FROM cats WHERE id=?', (cat_id,)).fetchone())
    con.close()
    return jsonify(cat)


@app.route('/api/cats/<int:cat_id>', methods=['DELETE'])
def api_delete_cat(cat_id):
    con = get_db()
    con.execute('DELETE FROM recordings WHERE cat_id=?', (cat_id,))
    con.execute('DELETE FROM cats WHERE id=?', (cat_id,))
    con.commit()
    con.close()
    return jsonify({'ok': True})


@app.route('/api/upload', methods=['POST'])
def upload():
    audio = request.files.get('audio')
    description = (request.form.get('description') or '').strip()
    cat_id = None
    try:
        cat_id = int(request.form.get('cat_id') or 0) or None
    except ValueError:
        pass

    fname = None
    if audio:
        ext = 'webm'
        ct = audio.content_type or ''
        if 'mp4' in ct or 'mp4a' in ct: ext = 'mp4'
        elif 'ogg' in ct: ext = 'ogg'
        elif 'wav' in ct: ext = 'wav'
        fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}"
        audio.save(os.path.join(AUDIO_DIR, fname))

    cat_name = 'your cat'
    if cat_id:
        con = get_db()
        row = con.execute('SELECT name FROM cats WHERE id=?', (cat_id,)).fetchone()
        con.close()
        if row:
            cat_name = row['name']

    category = confidence = reasoning = None
    complete = 0
    if description:
        complete = 1
        category, confidence, reasoning = classify(description, cat_name)

    con = get_db()
    cur = con.execute(
        'INSERT INTO recordings (cat_id, filename, description, category, confidence, reasoning, complete) VALUES (?,?,?,?,?,?,?)',
        (cat_id, fname, description or None, category, confidence, reasoning, complete)
    )
    rec_id = cur.lastrowid
    con.commit()
    con.close()

    return jsonify({
        'id': rec_id,
        'category': category,
        'label': CATEGORY_LABELS.get(category) if category else None,
        'confidence': confidence,
        'reasoning': reasoning,
        'complete': bool(complete),
    })


@app.route('/api/event/<int:rec_id>/photo', methods=['POST'])
def upload_photo(rec_id):
    photo = request.files.get('photo')
    if not photo:
        return jsonify({'error': 'no photo'}), 400

    raw_name = photo.filename or ''
    ext = raw_name.rsplit('.', 1)[-1].lower() if '.' in raw_name else 'jpg'
    if ext not in ('jpg', 'jpeg', 'png', 'gif', 'heic', 'mp4', 'mov', 'webm'):
        ext = 'jpg'
    fname = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}"
    photo.save(os.path.join(PHOTO_DIR, fname))

    photo_category = (request.form.get('photo_category') or '').strip() or None
    try:
        photo_tags = json.loads(request.form.get('photo_tags', '[]'))
    except Exception:
        photo_tags = []

    con = get_db()
    con.execute(
        'UPDATE recordings SET photo_path=?, photo_category=?, photo_tags=? WHERE id=?',
        (fname, photo_category, json.dumps(photo_tags), rec_id)
    )
    con.commit()
    con.close()

    return jsonify({'ok': True, 'photo_path': fname})


@app.route('/api/describe/<int:rec_id>', methods=['POST'])
def describe(rec_id):
    description = (request.json or {}).get('description', '').strip()
    if not description:
        return jsonify({'error': 'empty description'}), 400

    con = get_db()
    rec = con.execute('SELECT cat_id FROM recordings WHERE id=?', (rec_id,)).fetchone()
    cat_name = 'your cat'
    if rec and rec['cat_id']:
        row = con.execute('SELECT name FROM cats WHERE id=?', (rec['cat_id'],)).fetchone()
        if row:
            cat_name = row['name']
    con.close()

    category, confidence, reasoning = classify(description, cat_name)

    con = get_db()
    con.execute(
        'UPDATE recordings SET description=?, category=?, confidence=?, reasoning=?, complete=1 WHERE id=?',
        (description, category, confidence, reasoning, rec_id)
    )
    con.commit()
    con.close()

    return jsonify({
        'category': category,
        'label': CATEGORY_LABELS.get(category) if category else None,
        'confidence': confidence,
        'reasoning': reasoning,
    })


@app.route('/api/event/<int:rec_id>/tags', methods=['POST'])
def save_tags(rec_id):
    data = request.json or {}
    category       = data.get('category', '')
    detail_tags    = data.get('detail_tags', [])
    global_context = data.get('global_context', [])
    owner_rating   = data.get('owner_rating', '')
    owner_note     = (data.get('owner_note') or '').strip()

    con = get_db()
    fields = {
        'detail_tags':    json.dumps(detail_tags),
        'global_context': json.dumps(global_context),
        'complete':       1,
    }
    if category and category in CATEGORIES:
        fields['category'] = category
    if owner_rating and owner_rating in OWNER_RATINGS:
        fields['owner_rating'] = owner_rating
    if owner_note:
        fields['owner_note'] = owner_note

    set_clause = ', '.join(f'{k}=?' for k in fields)
    con.execute(f'UPDATE recordings SET {set_clause} WHERE id=?',
                list(fields.values()) + [rec_id])
    con.commit()
    rec = con.execute('SELECT cat_id FROM recordings WHERE id=?', (rec_id,)).fetchone()
    con.close()

    concerns = get_concern_flags(rec['cat_id']) if rec and rec['cat_id'] else []
    return jsonify({'ok': True, 'concerns': concerns})


@app.route('/api/event/<int:rec_id>/feedback', methods=['POST'])
def save_feedback(rec_id):
    feedback = (request.json or {}).get('feedback', '').strip()
    if feedback not in ('right', 'close', 'wrong', 'unsure'):
        return jsonify({'error': 'invalid feedback'}), 400
    con = get_db()
    con.execute('UPDATE recordings SET user_feedback=? WHERE id=?', (feedback, rec_id))
    con.commit()
    con.close()
    return jsonify({'ok': True})


@app.route('/api/cat/<int:cat_id>/concerns')
def cat_concerns(cat_id):
    return jsonify(get_concern_flags(cat_id))


@app.route('/api/recordings')
def api_recordings():
    con = get_db()
    rows = con.execute('''
        SELECT r.*, c.name as cat_name
        FROM recordings r LEFT JOIN cats c ON c.id=r.cat_id
        ORDER BY r.created_at DESC LIMIT 50
    ''').fetchall()
    con.close()
    return jsonify(enrich(rows))


@app.route('/api/stats')
def stats():
    con = get_db()
    total     = con.execute('SELECT COUNT(*) FROM recordings').fetchone()[0]
    complete  = con.execute('SELECT COUNT(*) FROM recordings WHERE complete=1').fetchone()[0]
    by_cat    = con.execute(
        'SELECT category, COUNT(*) as n FROM recordings WHERE complete=1 GROUP BY category'
    ).fetchall()
    cat_count = con.execute('SELECT COUNT(*) FROM cats').fetchone()[0]
    con.close()
    return jsonify({
        'total': total, 'complete': complete,
        'incomplete': total - complete, 'cats': cat_count,
        'by_category': {r[0]: r[1] for r in by_cat},
    })


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5568))
    app.run(host='0.0.0.0', port=port, debug=False)
