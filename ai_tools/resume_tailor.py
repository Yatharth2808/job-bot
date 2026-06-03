import os
import csv
from groq import Groq
from PyPDF2 import PdfReader
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def read_resume(pdf_path):
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    return text

def tailor_resume(job_title, company, job_description, resume_text, portfolio_url):
    prompt = f"""
You are an expert resume writer. Your job is to tailor a resume for a specific job posting.

CANDIDATE PORTFOLIO: {portfolio_url}

ORIGINAL RESUME:
{resume_text}

JOB TITLE: {job_title}
COMPANY: {company}

JOB DESCRIPTION:
{job_description[:2000]}

Your task:
1. Rewrite the resume SUMMARY to match this specific job
2. Highlight the most relevant SKILLS for this job
3. Reorder projects to show most relevant ones first
4. Keep all facts truthful - do not invent experience

Return the output in this exact format:

SUMMARY:
[tailored summary here]

KEY SKILLS:
[relevant skills here]

TALKING POINTS:
[3 bullet points on why this candidate is a good fit]

COVER LETTER:
[short 3 paragraph cover letter]
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500
    )

    return response.choices[0].message.content

def process_jobs(jobs_csv, resume_path, portfolio_url, output_csv='data/tailored_jobs.csv'):
    resume_text = read_resume(resume_path)
    print(f"Resume loaded successfully!")

    results = []

    with open(jobs_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        jobs = list(reader)

    print(f"Processing {len(jobs)} jobs...")

    for i, job in enumerate(jobs[:10]):  # start with first 10 jobs
        print(f"Tailoring resume for job {i+1}/10: {job.get('title')} at {job.get('company')}...")

        try:
            tailored = tailor_resume(
                job_title=job.get('title', ''),
                company=job.get('company', ''),
                job_description=job.get('description', ''),
                resume_text=resume_text,
                portfolio_url=portfolio_url
            )

            results.append({
                'job_title': job.get('title', ''),
                'company': job.get('company', ''),
                'location': job.get('location', ''),
                'job_url': job.get('job_url', ''),
                'tailored_content': tailored
            })

        except Exception as e:
            print(f"Error processing job {i+1}: {e}")
            continue

    # Save results
    os.makedirs('data', exist_ok=True)
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['job_title', 'company', 'location', 'job_url', 'tailored_content'])
        writer.writeheader()
        writer.writerows(results)

    print(f"Done! Tailored {len(results)} resumes saved to {output_csv}")

if __name__ == "__main__":
    process_jobs(
        jobs_csv='data/jobs.csv',
        resume_path=os.getenv('RESUME_PATH'),
        portfolio_url=os.getenv('PORTFOLIO_URL')
    )