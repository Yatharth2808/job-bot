import os
import re
import time
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Clients — Ollama (primary, local, no rate limits) + Groq (fallback)
# ---------------------------------------------------------------------------

try:
    import ollama as _ollama
    import urllib.request as _ur
    OLLAMA_MODEL = "llama3"
    # Check service is reachable without loading the model (avoids slow first-run timeout)
    _ur.urlopen("http://localhost:11434/api/tags", timeout=3).read()
    OLLAMA_AVAILABLE = True
    print("✓ Ollama (llama3) is available — using local AI, no rate limits")
except Exception:
    OLLAMA_AVAILABLE = False
    print("⚠ Ollama not available — falling back to Groq")

try:
    from groq import Groq
    _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    GROQ_AVAILABLE = True
except Exception:
    GROQ_AVAILABLE = False


PROFILE = {
    "full_name": os.getenv("FULL_NAME"),
    "email": os.getenv("EMAIL"),
    "phone": os.getenv("PHONE"),
    "city": os.getenv("CURRENT_CITY"),
    "state": os.getenv("CURRENT_STATE"),
    "country": os.getenv("CURRENT_COUNTRY"),
    "willing_to_relocate": os.getenv("WILLING_TO_RELOCATE"),
    "authorized_to_work": os.getenv("AUTHORIZED_TO_WORK"),
    "require_sponsorship": os.getenv("REQUIRE_SPONSORSHIP"),
    "visa_status": os.getenv("VISA_STATUS"),
    "years_professional": os.getenv("YEARS_PROFESSIONAL"),
    "years_parttime": os.getenv("YEARS_PARTTIME"),
    "years_python": os.getenv("YEARS_PYTHON"),
    "years_java": os.getenv("YEARS_JAVA"),
    "years_javascript": os.getenv("YEARS_JAVASCRIPT"),
    "years_react": os.getenv("YEARS_REACT"),
    "years_sql": os.getenv("YEARS_SQL"),
    "years_firebase": os.getenv("YEARS_FIREBASE"),
    "years_data_analysis": os.getenv("YEARS_DATA_ANALYSIS"),
    "years_machine_learning": os.getenv("YEARS_MACHINE_LEARNING"),
    "years_docker": os.getenv("YEARS_DOCKER"),
    "years_git": os.getenv("YEARS_GIT"),
    "highest_degree": os.getenv("HIGHEST_DEGREE"),
    "field_of_study": os.getenv("FIELD_OF_STUDY"),
    "university": os.getenv("UNIVERSITY"),
    "graduation_year": os.getenv("GRADUATION_YEAR"),
    "gpa": os.getenv("GPA"),
    "currently_pursuing": os.getenv("CURRENTLY_PURSUING"),
    "current_institution": os.getenv("CURRENT_INSTITUTION"),
    "onsite_available": os.getenv("ONSITE_AVAILABLE"),
    "remote_preferred": os.getenv("REMOTE_PREFERRED"),
    "hybrid_available": os.getenv("HYBRID_AVAILABLE"),
    "current_employer": os.getenv("CURRENT_EMPLOYER"),
    "current_title": os.getenv("CURRENT_TITLE"),
    "employment_type": os.getenv("EMPLOYMENT_TYPE"),
    "work_start_date": os.getenv("WORK_START_DATE"),
    "work_description": os.getenv("WORK_DESCRIPTION"),
    "veteran_status": os.getenv("VETERAN_STATUS"),
    "disability_status": os.getenv("DISABILITY_STATUS"),
    "gender": os.getenv("GENDER"),
    "ethnicity": os.getenv("ETHNICITY"),
}


# ---------------------------------------------------------------------------
# Internal LLM call — Ollama first, Groq fallback
# ---------------------------------------------------------------------------

def _call_llm(prompt, max_tokens=50):
    """Call Ollama (local) first; fall back to Groq on any failure."""
    if OLLAMA_AVAILABLE:
        try:
            resp = _ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"num_predict": max_tokens, "temperature": 0.1},
            )
            return resp["message"]["content"].strip()
        except Exception as e:
            print(f"    Ollama error: {e} — trying Groq fallback")

    if GROQ_AVAILABLE:
        for attempt in range(3):
            try:
                resp = _groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    wait = 8 * (attempt + 1)
                    print(f"    Groq rate limit — waiting {wait}s (attempt {attempt+1}/3)…")
                    time.sleep(wait)
                    continue
                print(f"    Groq error: {e}")
                break

    return None  # both failed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_smart_salary(job_title, location):
    prompt = f"""
What is the average entry level salary in USD for:
- Job Title: {job_title}
- Location: {location}
- Experience Level: Entry level (0-2 years)
- Use 2026 current market salary data

Rules:
1. Return ONLY a single number, no $ sign, no commas, no text
2. Subtract $5,000 from the average to be slightly below market
3. Round to nearest $5,000
4. SF/Bay Area minimum: $110,000
5. NYC minimum: $85,000
6. Seattle minimum: $95,000
7. Remote minimum: $80,000
8. Texas/Austin minimum: $70,000
9. Example response: 85000

Return ONLY one number. Nothing else.
"""
    result = _call_llm(prompt, max_tokens=20)
    if result:
        numbers = re.findall(r'\d+', result.replace(',', ''))
        for num in numbers:
            if 40000 <= int(num) <= 200000:
                return num
    return "70000"


def get_answer(question, options=None, job_title=None, location=None):
    q_lower = question.lower()

    # --- Hard overrides (never let the AI get these wrong) ---

    # Sponsorship: I-485 Pending = work authorized, NO sponsorship needed
    if any(k in q_lower for k in ('sponsor', 'visa sponsor', 'h-1b', 'h1b', 'require visa')):
        if options:
            for opt in options:
                if 'no' in opt.lower():
                    return opt
        return 'No'

    # Work authorization: always Yes
    if any(k in q_lower for k in ('authorized to work', 'legally authorized', 'eligible to work')):
        if options:
            for opt in options:
                if 'yes' in opt.lower():
                    return opt
        return 'Yes'

    # Salary
    if any(k in q_lower for k in ('salary', 'compensation', 'pay', 'wage', 'expected salary', 'desired salary')):
        if job_title and location:
            salary = get_smart_salary(job_title, location)
            print(f"    Smart salary for {job_title} in {location}: ${salary}")
            return salary

    # --- AI answer ---
    options_text = (
        f"\nAvailable options (pick EXACTLY one as written):\n" + "\n".join(options)
        if options else ""
    )

    prompt = f"""You are filling out a job application for Yatharth Gautam.
His profile: {PROFILE}

Question: "{question}"{options_text}

Rules:
1. Answer based on his profile — be honest
2. ONE word or ONE short phrase only — no explanation
3. Yes/No questions → only "Yes" or "No"
4. If options given → return the BEST option EXACTLY as written
5. Work authorization → always "Yes"
6. Visa sponsorship → always "No" (I-485 Pending = authorized, no sponsorship needed)
7. Location questions about cities he's not in → "No"
8. Tech years → use his profile values

Return ONLY the answer."""

    result = _call_llm(prompt, max_tokens=50)
    if result:
        return result

    # Both LLMs failed — safe static fallback
    if options:
        return options[0]
    if any(w in q_lower for w in ('sponsor', 'criminal', 'felony')):
        return 'No'
    return 'Yes'


def answer_dropdown(question_text, options, job_title=None, location=None):
    answer = get_answer(question_text, options, job_title, location)
    print(f"Q: {question_text[:60]}... → A: {answer}")
    return answer

def answer_radio(question_text, options, job_title=None, location=None):
    answer = get_answer(question_text, options, job_title, location)
    print(f"Q: {question_text[:60]}... → A: {answer}")
    return answer

def answer_text(question_text, job_title=None, location=None):
    answer = get_answer(question_text, job_title=job_title, location=location)
    print(f"Q: {question_text[:60]}... → A: {answer}")
    return answer


if __name__ == "__main__":
    print("Testing question handler...\n")
    print("=== Basic Questions ===")
    print(get_answer("Are you authorized to work in the United States?", ["Yes", "No"]))
    print(get_answer("Do you require visa sponsorship?", ["Yes", "No"]))
    print(get_answer("How many years of Python experience do you have?", ["0-1 years", "1-2 years", "2-3 years", "3+ years"]))
    print(get_answer("Are you comfortable working onsite?", ["Yes", "No"]))
    print(get_answer("Are you located in the San Francisco Bay Area?", ["Yes", "No"]))

    print("\n=== Smart Salary Tests ===")
    print(f"SF Software Engineer: ${get_smart_salary('Software Engineer', 'San Francisco')}")
    print(f"Texas Python Developer: ${get_smart_salary('Python Developer', 'Texas')}")
    print(f"Remote ML Engineer: ${get_smart_salary('ML Engineer', 'Remote')}")
