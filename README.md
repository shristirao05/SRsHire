# SRsHire - AI Resume Screening System

Screens a folder of resume PDFs against a job role using AI and shortlists the best matches.

## What it does
- Converts scanned PDFs into searchable text (OCR)
- Reads each resume and scores it against the job role using an AI model
- Saves shortlisted resumes as CandidateName_XX%.pdf
- Creates one report explaining why other candidates were not selected

## Built with
Python, Flask, Groq API, Tesseract OCR, ocrmypdf, pdfminer, ReportLab, HTML/CSS/JavaScript

## How to run
1. Install Python, Tesseract OCR and Poppler
2. Run: pip install -r requirements.txt
3. Create a file named .env and add: GROQ_API_KEY=your_key_here
4. Check the paths inside config.py
5. Run: python app.py
6. Your browser opens at http://127.0.0.1:5000
