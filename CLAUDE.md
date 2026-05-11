# jackspeak — Re-Entry File
*Claude: read this before touching anything.*

---

## What This Is
Cat vocalization interpreter — understand what Jack (and any cat) is saying.
Records audio, classifies with Claude Haiku, builds a per-cat behavioral baseline over time.

## Re-Entry Phrase
> "Re-entry: jackspeak"

## Live URL
https://jackspeak-production.up.railway.app

## Stack
- Python + Flask, port 5568 locally / $PORT on Railway
- SQLite at data/jackspeak.db
- Claude Haiku for classification
- Dark theme, Inter font, CSS variables
- Logo at /static/logo.png

## File Structure
```
jackspeak/
├── app.py                      # All routes + DB + classify + concern flags
├── templates/
│   ├── record.html             # Main recording UI + Cat Clues bubble system
│   ├── cats.html               # Cat management (add/list)
│   ├── cat_profile.html        # Cat journal, concerns, common/unusual summary
│   └── review.html             # All recordings, filter, inline classify
├── static/
├── data/
│   ├── jackspeak.db            # SQLite DB (gitignored)
│   └── recordings/             # Audio files (gitignored)
├── Procfile                    # gunicorn for Railway
├── requirements.txt
├── Makefile
├── .env                        # ANTHROPIC_API_KEY + SECRET_KEY (gitignored)
└── .env.example
```

## How to Run Locally
```bash
cd ~/jackspeak && make run
```

## GitHub
- Repo: papjamzzz/jackspeak
- Push: `git add -A && git commit -m "msg" && git push`
- Railway auto-deploys on push (linked to main branch)

## DB Schema
```sql
cats(id, name, age_years, breed, indoor_outdoor, health_notes, vocal_notes, created_at)

recordings(id, cat_id, filename, audio_ext, description,
           category, detail_tags, global_context,
           confidence, reasoning, user_feedback, complete, created_at)
```

## Categories (updated from v1)
- request, social, stress, discomfort, unusual

## What's Done
- [x] Project scaffold
- [x] Audio recording + waveform
- [x] Claude Haiku classification (5 categories)
- [x] Cat profiles (cats table, profile page, edit)
- [x] Cat Clues bubble tag system (category → detail tags + global context)
- [x] Feedback loop (right/close/wrong/unsure per recording)
- [x] Concern flag engine (pattern-based health alerts)
- [x] Journal timeline per cat (grouped by day)
- [x] Common / Unusual summaries on cat profile
- [x] Railway deployment live

## What's Next
- [ ] Per-cat baseline comparison ("unusual for Luna but normal range for most cats")
- [ ] Weekly digest / trend summary
- [ ] Push notifications for repeated concern flags
- [ ] Export journal as PDF for vet visits

---

## Last Session
Built full V2: cat profiles, bubble tag UI, journal timeline, concern flag engine,
Railway deployment. Live at jackspeak-production.up.railway.app.
*Updated: 2026-05-10*
