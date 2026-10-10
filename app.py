"""
SRsHire — AI Resume Screening System
--------------------------------------
Built by: Shristi Rao
--------------------------------------
Pipeline:
  1. Scan input folder → count PDFs
  2. Validate job role using LLM (typo correction + relevance check)
  3. For each PDF:
     a. Convert non-searchable PDF → searchable PDF (ocrmypdf)
     b. Extract text (pdfminer)
     c. Send to LLM → get candidate name + match % + reason
  4. Save shortlisted candidates as CandidateName_XX%.pdf
  5. Save Leftover_Candidates.pdf or No_Result_Found.pdf
"""

import os
import tempfile
import re
import time
import shutil
import threading
import traceback
import uuid
from datetime import datetime

from flask import Flask, request, jsonify, render_template
import ocrmypdf
from groq import Groq
from pdfminer.high_level import extract_text

import config

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

JOBS = {}
JOBS_LOCK = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(job_id, message):
    with JOBS_LOCK:
        JOBS[job_id]["log"].append(message)


def get_pdf_files(folder_path):
    """Return list of PDF paths, skipping any SRsHire output files."""
    files = []
    skip_suffixes = ("_searchable.pdf",)
    skip_names = ("No_Result_Found.pdf", "Leftover_Candidates.pdf")
    for f in sorted(os.listdir(folder_path)):
        if not f.lower().endswith(".pdf"):
            continue
        if any(f.endswith(s) for s in skip_suffixes):
            continue
        if f in skip_names:
            continue
        files.append(os.path.join(folder_path, f))
    return files


def groq_client():
    return Groq(api_key=config.GROQ_API_KEY)


# ── Step 0: Validate job role ─────────────────────────────────────────────────

def validate_job_role(raw_role):
    """
    Ask LLM to:
    1. Correct typos and return the clean job role name.
    2. If completely unrecognizable, return INVALID.
    Returns (corrected_role_or_None, is_valid, message)
    """
    client = groq_client()
    prompt = f"""
A user typed this job role for hiring: "{raw_role}"

Your tasks:
1. If this is a real job role (even with typos/spelling mistakes), correct ONLY the spelling
   and return the FULL corrected job role name. You must preserve every word/concept in the
   original input — never drop, shorten, or simplify it to a single word or skill name.
   Examples:
   - "data anlsyt" → "Data Analyst"
   - "sofware engineeer" → "Software Engineer"
   - "hr managar" → "HR Manager"
   - "data administrtr" → "Data Administrator"
   - "python ai engiener" → "Python AI Engineer"
   - "ai python engieenr" → "AI Python Engineer"
   - "sr backend devloper" → "Senior Backend Developer"

   Do NOT reduce a multi-word title to just one of its words.

2. If this input is completely unrecognizable as any real job role (random letters, gibberish,
   irrelevant words), return exactly: INVALID

Return ONLY the corrected job role OR the word INVALID. No explanation, no extra words.
"""
    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=300,              # was 50 — too small for a reasoning model
        reasoning_effort="low",      # this is a simple task, don't let it "think" long
    )
    result = response.choices[0].message.content.strip()

    # Reasoning models can still return empty content if reasoning ate the whole
    # budget — treat that as invalid rather than silently accepting "".
    if not result or result.upper() == "INVALID":
        return None, False, "Your job role could not be understood. Please rewrite it clearly."
    return result, True, f"Job role understood as: {result}"
# ── Step 1: OCR conversion ────────────────────────────────────────────────────

def convert_to_searchable(pdf_path, job_id, temp_dir):
    """Convert non-searchable PDF to searchable, saved in a temp folder (not the input folder)."""
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    searchable_path = os.path.join(temp_dir, base + "_searchable.pdf")
    log(job_id, f"    Converting to searchable PDF...")
    try:
        ocrmypdf.ocr(
            pdf_path,
            searchable_path,
            language="eng",
            deskew=True,
            force_ocr=True,
            progress_bar=False,
            tesseract_cmd=config.TESSERACT_PATH,
        )
        log(job_id, f"    Searchable PDF created.")
        return searchable_path
    except Exception as e:
        log(job_id, f"    OCR failed, trying direct text extraction: {e}")
        return pdf_path


# ── Step 2: Text extraction ───────────────────────────────────────────────────

def extract_resume_text(pdf_path, job_id):
    """Extract text from PDF (searchable or otherwise)."""
    log(job_id, f"    Extracting text...")
    text = extract_text(pdf_path)
    return (text or "").strip()


# ── Step 3: LLM resume analysis ──────────────────────────────────────────────

def analyze_resume(text, job_role, compulsory_skills, filename, job_id):
    """
    Send resume text to LLM.
    Returns dict: {name, percentage, reason, is_relevant}
    """
    client = groq_client()

    skills_line = ""
    if compulsory_skills and compulsory_skills.strip():
        skills_line = f"\nCompulsory skills the candidate MUST have: {compulsory_skills.strip()}"

    prompt = f"""
You are a strict but fair HR screening expert.

Job Role to hire for: {job_role}{skills_line}

Resume Content:
{text[:8000]}

Your tasks:
1. Extract the candidate's full name from the resume. If not found, use the filename: {filename}

2. Assess how relevant this resume is for the job role "{job_role}".
   Be STRICT and HONEST about the match percentage:
   - Only give high % (80-100%) if skills strongly match the job role
   - Give medium % (40-79%) if there is genuine partial match
   - Give low % (20-39%) if there is minimal but real relevance
   - Mark as IRRELEVANT if the resume has NO connection to this job role whatsoever
   
   IMPORTANT RULES:
   - Do NOT inflate percentages. A resume with only basic Excel skills is NOT 60% match for a Data Scientist role.
   - If compulsory skills are listed and the candidate is missing them, reduce the percentage significantly.
   - Non-ATS-friendly resumes should NOT be penalized if the actual skills match.
   - Judge the actual skills and experience, not the formatting.

3. Give ONE short reason (1-2 sentences) for your assessment.

Respond in EXACTLY this format (nothing else):
NAME: [candidate full name]
PERCENTAGE: [number only, e.g. 75] OR IRRELEVANT
REASON: [one short reason]
"""

    log(job_id, f"    Analyzing with LLM...")
    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a strict HR screening expert. Be honest and accurate in your assessments. Never inflate match percentages."
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=500,           # was 200 — too small for a reasoning model
        reasoning_effort="low",   # this task doesn't need deep reasoning
    )

    raw = response.choices[0].message.content.strip()

    # Parse response
    name = filename.replace(".pdf", "")
    percentage = None
    reason = "Reason unavailable — AI response was incomplete."
    is_relevant = False

    for line in raw.split("\n"):
        line = line.strip()
        if line.upper().startswith("NAME:"):
            name = line.split(":", 1)[1].strip()
        elif line.upper().startswith("PERCENTAGE:"):
            val = line.split(":", 1)[1].strip()
            if val.upper() == "IRRELEVANT":
                is_relevant = False
                percentage = 0
            else:
                try:
                    percentage = int(re.search(r'\d+', val).group())
                    is_relevant = percentage >= config.MIN_MATCH_PERCENTAGE
                except:
                    is_relevant = False
                    percentage = 0
        elif line.upper().startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()

    return {
        "name": name,
        "percentage": percentage or 0,
        "reason": reason,
        "is_relevant": is_relevant,
    }


# ── Step 4: Save output PDFs ──────────────────────────────────────────────────

def save_candidate_pdf(original_pdf, candidate_name, percentage, output_folder):
    """Copy resume PDF to output folder with new name: CandidateName_XX%.pdf"""
    os.makedirs(output_folder, exist_ok=True)
    safe_name = re.sub(r'[<>:"/\\|?*]', '', candidate_name).strip()
    output_filename = f"{safe_name}_{percentage}%.pdf"
    output_path = os.path.join(output_folder, output_filename)
    shutil.copy2(original_pdf, output_path)
    return output_path


def save_result_pdf(title, content_lines, output_folder, filename):
    """Save a formatted PDF (No Result Found or Leftover Candidates)."""
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch

    os.makedirs(output_folder, exist_ok=True)
    output_path = os.path.join(output_folder, filename)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("T", parent=styles["Heading1"], fontSize=16, spaceAfter=8, textColor="darkblue")
    sub_style = ParagraphStyle("S", parent=styles["Normal"], fontSize=10, spaceAfter=4, textColor="gray", italics=True)
    body_style = ParagraphStyle("B", parent=styles["Normal"], fontSize=10, leading=16, spaceAfter=6)

    story = []
    story.append(Paragraph(title, title_style))
    story.append(Paragraph(f"Generated by SRsHire | {datetime.now().strftime('%d-%m-%Y %H:%M')}", sub_style))
    story.append(Spacer(1, 0.2 * inch))

    for line in content_lines:
        if line.strip():
            story.append(Paragraph(line.strip(), body_style))
        else:
            story.append(Spacer(1, 0.1 * inch))

    doc.build(story)
    return output_path


# ── Main job runner ───────────────────────────────────────────────────────────

def run_job(job_id, input_folder, output_folder, job_role, compulsory_skills):
    temp_dir = tempfile.mkdtemp(prefix="srshire_ocr_")          # <-- NEW
    try:
        # Validate job role first
        log(job_id, f"Validating job role: '{job_role}'...")
        corrected_role, is_valid, message = validate_job_role(job_role)

        if not is_valid:
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "invalid_role"
                JOBS[job_id]["error"] = message
            return

        log(job_id, f"Job role confirmed: {corrected_role}")

        with JOBS_LOCK:
            JOBS[job_id]["corrected_role"] = corrected_role

        # Get PDF files
        pdf_files = get_pdf_files(input_folder)
        total = len(pdf_files)

        if total == 0:
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = "No PDF files found in the input folder."
            return

        with JOBS_LOCK:
            JOBS[job_id]["total"] = total

        log(job_id, f"Found {total} PDF file(s). Starting screening...")

        shortlisted = []  # {name, percentage, reason, output_path}
        rejected = []     # {name, reason}

        for idx, pdf_path in enumerate(pdf_files, 1):
            filename = os.path.basename(pdf_path)

            with JOBS_LOCK:
                JOBS[job_id]["current"] = idx
                JOBS[job_id]["current_file"] = filename

            log(job_id, f"")
            log(job_id, f"[{idx}/{total}] Processing: {filename}")

            try:
                # Convert to searchable
                searchable_path = convert_to_searchable(pdf_path, job_id, temp_dir)   # <-- CHANGED (added temp_dir)

                # Extract text
                text = extract_resume_text(searchable_path, job_id)

                if not text or len(text.strip()) < 50:
                    log(job_id, f"    Could not extract enough text. Skipping.")
                    rejected.append({
                        "name": filename.replace(".pdf", ""),
                        "reason": "Could not extract readable text from this resume PDF."
                    })
                    continue

                # Analyze with LLM
                result = analyze_resume(
                    text, corrected_role, compulsory_skills, filename, job_id
                )

                name = result["name"]
                pct = result["percentage"]
                reason = result["reason"]
                relevant = result["is_relevant"]

                if relevant:
                    out_path = save_candidate_pdf(pdf_path, name, pct, output_folder)
                    shortlisted.append({
                        "name": name,
                        "percentage": pct,
                        "reason": reason,
                        "output_path": out_path,
                    })
                    log(job_id, f"    ✔ Shortlisted: {name} — {pct}%")
                else:
                    rejected.append({"name": name, "reason": reason})
                    log(job_id, f"    ✘ Not shortlisted: {name} — {reason}")

            except Exception as e:
                log(job_id, f"    ERROR processing {filename}: {e}")
                rejected.append({
                    "name": filename.replace(".pdf", ""),
                    "reason": f"Processing error: {str(e)}"
                })

            if idx < total:
                time.sleep(1.2)

        # ── Save output PDFs ──────────────────────────────────────────────────

        log(job_id, "")
        log(job_id, "Saving output files...")

        if len(shortlisted) == 0:
            # No one shortlisted → No_Result_Found.pdf
            lines = [
                f"Job Role: {corrected_role}",
                f"Total Resumes Screened: {total}",
                f"Shortlisted: 0",
                "",
                "Reasons why no candidate was selected:",
                "",
            ]
            for r in rejected:
                lines.append(f"{r['name']}: {r['reason']}")

            save_result_pdf(
                "No Result Found",
                lines,
                output_folder,
                "No_Result_Found.pdf"
            )
            log(job_id, "No candidates shortlisted. Saved: No_Result_Found.pdf")

        else:
            # Sort shortlisted by percentage descending
            shortlisted.sort(key=lambda x: x["percentage"], reverse=True)

            # Save leftover PDF if there are rejected candidates
            if rejected:
                lines = [
                    f"Job Role: {corrected_role}",
                    f"Total Resumes Screened: {total}",
                    f"Shortlisted: {len(shortlisted)} | Not Selected: {len(rejected)}",
                    "",
                    "Reason why these candidates were not selected:",
                    "",
                ]
                for r in rejected:
                    lines.append(f"{r['name']}: {r['reason']}")

                save_result_pdf(
                    "Leftover Candidates",
                    lines,
                    output_folder,
                    "Leftover_Candidates.pdf"
                )
                log(job_id, f"Saved: Leftover_Candidates.pdf ({len(rejected)} candidates)")

        log(job_id, "")
        log(job_id, f"✔ All done! Shortlisted: {len(shortlisted)} | Not selected: {len(rejected)}")

        with JOBS_LOCK:
            JOBS[job_id]["status"] = "done"
            JOBS[job_id]["shortlisted"] = shortlisted
            JOBS[job_id]["rejected"] = rejected

    except Exception as e:
        traceback.print_exc()
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(e)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)                	


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/browse-folder")
def browse_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory()
        root.destroy()
        return jsonify({"path": folder or ""})
    except Exception as e:
        return jsonify({"error": str(e), "path": ""}), 500


@app.route("/api/validate-role", methods=["POST"])
def validate_role():
    """Validate job role — called before processing starts."""
    data = request.get_json(force=True)
    raw_role = (data.get("job_role") or "").strip()
    if not raw_role:
        return jsonify({"valid": False, "message": "Job role cannot be empty."})
    corrected, valid, message = validate_job_role(raw_role)
    return jsonify({"valid": valid, "corrected_role": corrected, "message": message})


@app.route("/api/scan-folder", methods=["POST"])
def scan_folder():
    """Count PDF files in the input folder."""
    data = request.get_json(force=True)
    folder = (data.get("folder_path") or "").strip()
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": "Folder not found.", "count": 0})
    files = get_pdf_files(folder)
    return jsonify({"count": len(files), "files": [os.path.basename(f) for f in files]})


@app.route("/api/process", methods=["POST"])
def process():
    data = request.get_json(force=True)
    input_folder = (data.get("input_folder") or "").strip()
    output_folder = (data.get("output_folder") or "").strip()
    job_role = (data.get("job_role") or "").strip()
    compulsory_skills = (data.get("compulsory_skills") or "").strip()

    if not input_folder or not os.path.isdir(input_folder):
        return jsonify({"error": "Input folder does not exist."}), 400
    if not output_folder:
        return jsonify({"error": "Output folder path is required."}), 400
    if not job_role:
        return jsonify({"error": "Job role is required."}), 400

    job_id = str(uuid.uuid4())
    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "running",
            "log": [],
            "total": 0,
            "current": 0,
            "current_file": "",
            "corrected_role": "",
            "shortlisted": [],
            "rejected": [],
            "error": None,
        }

    thread = threading.Thread(
        target=run_job,
        args=(job_id, input_folder, output_folder, job_role, compulsory_skills),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job."}), 404
        return jsonify(dict(job))


if __name__ == "__main__":
    if not config.GROQ_API_KEY or "PASTE_YOUR" in config.GROQ_API_KEY:
        print("\n❌ Please set your GROQ_API_KEY in config.py\n")
    elif not os.path.isfile(config.TESSERACT_PATH):
        print(f"\n❌ Tesseract not found at: {config.TESSERACT_PATH}\n")
    else:
        import webbrowser
        import threading as _t

        def _open():
            time.sleep(1.2)
            webbrowser.open("http://127.0.0.1:5000")

        _t.Thread(target=_open, daemon=True).start()
        print("\nStarting SRsHire — AI Resume Screening System...")
        print("Opening browser automatically...\n")
        app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
