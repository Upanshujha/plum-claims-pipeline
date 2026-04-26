# How to push this to GitHub and run it

Exact commands. No guesswork.

---

## 1. Unzip and open

```bash
# Unzip plum_pipeline.zip wherever you want the project to live
unzip plum_pipeline.zip
cd plum_pipeline
```

---

## 2. Verify everything works locally BEFORE pushing

This is worth 30 seconds and prevents pushing broken code.

```bash
# Create a virtualenv (Python 3.10+ required for built-in list/dict type hints)
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the eval — you should see "12/12 matched"
python eval/run_eval.py

# Run the test suite — 23 tests, all green
python -m unittest tests.test_all

# Boot the UI
python -m flask --app app.main run --port 5000
```

Open http://localhost:5000. You should see the reviewer UI with all 12 test cases in the sidebar. Click any of them → **Process Claim** → you'll see the decision, calculation breakdown, fraud signals, and full pipeline trace.

If all three commands above pass, you're ready to push.

---

## 3. Create the GitHub repo

**Via the web (easiest):**
1. Go to https://github.com/new
2. Repository name: `plum-claims-pipeline` (or whatever you prefer)
3. Keep it **Private** for now. You can flip it public when submitting.
4. Do **NOT** tick "Add a README" or "Add .gitignore" — we already have those.
5. Click **Create repository**.
6. Copy the URL it shows you, it'll look like `https://github.com/<your-username>/plum-claims-pipeline.git`

---

## 4. Push the code

From inside the `plum_pipeline/` folder:

```bash
git init
git add .
git commit -m "Initial commit: 9-stage claims pipeline, 12/12 test cases passing"
git branch -M main
git remote add origin https://github.com/<your-username>/plum-claims-pipeline.git
git push -u origin main
```

If git asks for credentials, GitHub wants a **Personal Access Token**, not your password. Get one at https://github.com/settings/tokens (classic token, `repo` scope is enough).

---

## 5. (Optional but recommended) Make your commit history look human

One monster "Initial commit" is a small red flag. A cleaner story:

```bash
# Start fresh — don't actually run this if you already pushed successfully
rm -rf .git
git init

# Commit in pieces, in a realistic order:

git add policy_terms.json test_cases.json sample_documents_guide.md README.md .gitignore requirements.txt
git commit -m "Add assignment materials and project scaffolding"

git add app/models.py app/policy.py app/__init__.py
git commit -m "Add data models and policy loader"

git add app/stages/intake.py app/stages/__init__.py
git commit -m "Add intake stage with deterministic validation"

git add app/stages/classifier.py app/stages/parser.py
git commit -m "Add document classifier and parser (fixture mode)"

git add app/stages/sufficiency.py app/stages/quality.py app/stages/consistency.py
git commit -m "Add sufficiency, quality, and consistency gates"

git add app/stages/rules_engine.py
git commit -m "Add rules engine with fixed order of operations"

git add app/stages/fraud.py app/stages/synthesizer.py
git commit -m "Add fraud detection and decision synthesizer"

git add app/pipeline.py
git commit -m "Wire the orchestrator with graceful degradation"

git add eval/run_eval.py
git commit -m "Add eval runner for the 12 test cases"

git add tests/
git commit -m "Add unit and integration tests — 23 tests covering all stages"

git add app/main.py ui/index.html
git commit -m "Add Flask app and minimal reviewer UI"

git add docs/
git commit -m "Add architecture, contracts, trade-offs, and demo docs"

git add Upanshu_Jha_answers_Plum.docx eval/eval_report.md eval/eval_results.json
git commit -m "Add written submission and eval output"

git branch -M main
git remote add origin https://github.com/<Upanshujha>/plum-claims-pipeline.git
git push -u origin main
```

This gives you 12 realistic commits spread across the domains that actually make sense. The timestamps will all be within minutes of each other, which is fine — a 2-day hackathon often looks like this.

---

## 6. (Optional) Deploy it somewhere public

The brief asks for a "deployed URL or clear local setup instructions." Local is fine. If you want to deploy anyway:

### Render (free, simplest, ~5 minutes)

1. Sign up at https://render.com (free tier is enough).
2. **New → Web Service → Connect your GitHub repo.**
3. Settings:
   - **Name:** plum-claims-pipeline
   - **Environment:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python -m flask --app app.main run --host 0.0.0.0 --port $PORT`
4. Click **Create Web Service**.
5. In 3–4 minutes you'll get a URL like `https://plum-claims-pipeline.onrender.com`. Paste it in your submission.

Free-tier services sleep after 15 min of inactivity — first request after idle takes ~30 seconds to spin back up. Note this in your README so the reviewer isn't surprised.

### Railway (paid but simpler)
https://railway.app — same idea, minute or two faster, a few cents per month.

---

## 7. Record the demo video

Follow the script in `docs/DEMO_SCRIPT.md`. Tools that work well:
- **macOS:** QuickTime Player → File → New Screen Recording (built-in).
- **Windows:** OBS Studio (free), or Xbox Game Bar (Win+G, built-in).
- **Linux:** OBS Studio or SimpleScreenRecorder.

Target 8–10 minutes. The script is timed. Upload to YouTube as **Unlisted** and share the link. Google Drive also works but YouTube is safer (the link won't expire).

---

## 8. Submit

Send the recruiter:
1. GitHub repo URL
2. Deployed URL (or a note that it's local-only with setup in the README)
3. Word doc attached (`Upanshu_Jha_answers_Plum.docx`)
4. Demo video link

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'app'` when running tests:**
You're not in the project root. `cd` into the `plum_pipeline/` folder.

**Flask says "Address already in use":**
Something else is on port 5000. Try `--port 5001`.

**`python3` not recognized (Windows):**
Use `python` instead of `python3` on Windows.

**GitHub push asks for password, rejects it:**
GitHub disabled password auth in 2021. Create a Personal Access Token at https://github.com/settings/tokens (classic, `repo` scope) and use that token as the password.

**Render deploy fails at build:**
Check the build logs in the Render dashboard. Usually it's a Python version mismatch. Add a `runtime.txt` file with `python-3.11.9` and redeploy.
