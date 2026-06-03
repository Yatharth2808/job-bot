import os
import re
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

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
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=20
    )

    salary = response.choices[0].message.content.strip()
    numbers = re.findall(r'\d+', salary.replace(',', ''))
    for num in numbers:
        if 40000 <= int(num) <= 200000:
            return num
    return "75000"

def get_answer(question, options=None, job_title=None, location=None):
    q_lower = question.lower()

    # Hard overrides — never let the AI answer these incorrectly
    # Sponsorship: I-485 Pending does NOT mean sponsorship is required
    if any(k in q_lower for k in ('sponsor', 'visa sponsor', 'h-1b', 'h1b', 'require visa')):
        answer = 'No'
        if options:
            for opt in options:
                if 'no' in opt.lower():
                    return opt
        return answer

    # Work authorization: always authorized
    if any(k in q_lower for k in ('authorized to work', 'legally authorized', 'eligible to work')):
        answer = 'Yes'
        if options:
            for opt in options:
                if 'yes' in opt.lower():
                    return opt
        return answer

    # Handle salary questions smartly
    salary_keywords = ['salary', 'compensation', 'pay', 'wage', 'expected salary', 'desired salary']
    if any(keyword in q_lower for keyword in salary_keywords):
        if job_title and location:
            salary = get_smart_salary(job_title, location)
            print(f"Smart salary for {job_title} in {location}: ${salary}")
            return salary

    options_text = ""
    if options:
        options_text = f"\nAvailable options to choose from:\n{chr(10).join(options)}"

    prompt = f"""
You are filling out a job application for Yatharth Gautam.
Here is his complete profile:

{PROFILE}

The application is asking this question:
"{question}"
{options_text}

Rules:
1. Answer HONESTLY based on his profile
2. Keep answer SHORT - one word or one sentence max
3. If it's a Yes/No question → answer Yes or No only
4. If options are provided → pick the BEST matching option exactly as written
5. Work authorization → ALWAYS "Yes" — he is authorized to work in the US
6. Visa sponsorship → ALWAYS "No" — he does NOT require sponsorship (I-485 Pending = work authorized, no sponsorship needed)
7. For location questions about specific cities he's not in → answer No but willing to relocate
8. For technology experience → use his years from profile
9. Never make up experience he doesn't have

Return ONLY the answer, nothing else. No explanation.
"""

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if '429' in str(e) and attempt < 2:
                wait = 8 * (attempt + 1)
                print(f"    Groq rate limit — waiting {wait}s (attempt {attempt+1}/3)…")
                import time as _t; _t.sleep(wait)
                continue
            print(f"    Groq error: {e}")
            # Fallback: Yes for positive questions, No for negative ones
            q_l = question.lower()
            if options:
                return options[0]
            if any(w in q_l for w in ('sponsor', 'require visa', 'criminal')):
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
    print(f"NYC Data Analyst: ${get_smart_salary('Data Analyst', 'New York')}")
    print(f"Texas Python Developer: ${get_smart_salary('Python Developer', 'Texas')}")
    print(f"Remote ML Engineer: ${get_smart_salary('ML Engineer', 'Remote')}")
    print(f"Seattle Data Scientist: ${get_smart_salary('Data Scientist', 'Seattle')}")