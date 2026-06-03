import os
import sys
import time
import csv
import json
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_tools.question_handler import get_answer, get_smart_salary

load_dotenv()

def check_daily_limit(limit=15):
    today = time.strftime('%Y-%m-%d')
    daily_count = 0
    
    if os.path.exists('data/applied_jobs.csv'):
        with open('data/applied_jobs.csv', 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('date') == today:
                    daily_count += 1
    
    remaining = limit - daily_count
    print(f"Today's applications: {daily_count}/{limit}")
    
    if daily_count >= limit:
        print("Daily limit reached! Come back tomorrow.")
        return 0
    
    print(f"Remaining applications today: {remaining}")
    return remaining

def login_linkedin(page, context):
    cookies_file = 'data/linkedin_cookies.json'
    
    if os.path.exists(cookies_file):
        print("Loading saved LinkedIn session...")
        with open(cookies_file, 'r') as f:
            cookies = json.load(f)
        context.add_cookies(cookies)
        page.goto("https://www.linkedin.com/feed")
        time.sleep(3)
        print("Logged in using saved session!")
        return
    
    print("Please log in to LinkedIn manually in the browser window...")
    page.goto("https://www.linkedin.com/login")
    input("Press ENTER here after you have logged in successfully...")
    
    cookies = context.cookies()
    os.makedirs('data', exist_ok=True)
    with open(cookies_file, 'w') as f:
        json.dump(cookies, f)
    print("Session saved! Won't need to login again.")

def search_jobs(page, job_title, location="United States"):
    print(f"Searching for: {job_title}...")
    url = f"https://www.linkedin.com/jobs/search/?keywords={job_title.replace(' ', '%20')}&location={location.replace(' ', '%20')}&f_AL=true&f_E=1%2C2"
    page.goto(url)
    time.sleep(5)
    page.evaluate("window.scrollTo(0, 500)")
    time.sleep(2)

def handle_form_questions(page, job_title, location):
    question_items = page.query_selector_all('.jobs-easy-apply-form-element')
    for item in question_items:
        try:
            label = item.query_selector('label, legend, span.t-bold')
            if not label:
                continue
            question = label.inner_text().strip()
            if not question:
                continue
            
            print(f"Found question: {question[:60]}...")
                
            # Handle text inputs
            text_input = item.query_selector('input[type="text"], input[type="number"], textarea')
            if text_input:
                current = text_input.input_value()
                if not current:
                    answer = get_answer(question, job_title=job_title, location=location)
                    text_input.fill(str(answer))
                    print(f"Answered: {str(answer)[:50]}")
                    time.sleep(0.5)
                continue
            
            # Handle select dropdowns
            select = item.query_selector('select')
            if select:
                options = []
                for opt in select.query_selector_all('option'):
                    text = opt.inner_text().strip()
                    if text and text != 'Select an option':
                        options.append(text)
                if options:
                    answer = get_answer(question, options=options, job_title=job_title, location=location)
                    try:
                        select.select_option(label=answer)
                    except:
                        select.select_option(index=1)
                    print(f"Selected: {answer[:50]}")
                    time.sleep(0.5)
                continue
            
            # Handle radio buttons
            radios = item.query_selector_all('input[type="radio"]')
            if radios:
                options = []
                for radio in radios:
                    lbl = page.query_selector(f'label[for="{radio.get_attribute("id")}"]')
                    if lbl:
                        options.append(lbl.inner_text().strip())
                if options:
                    answer = get_answer(question, options=options, job_title=job_title, location=location)
                    clicked = False
                    for radio in radios:
                        lbl = page.query_selector(f'label[for="{radio.get_attribute("id")}"]')
                        if lbl and answer.lower() in lbl.inner_text().lower():
                            radio.evaluate("el => el.click()")
                            print(f"Selected radio: {answer[:50]}")
                            time.sleep(0.5)
                            clicked = True
                            break
                    if not clicked:
                        radios[0].evaluate("el => el.click()")
                        print(f"Selected first radio option")
                continue
                
        except Exception as e:
            continue

def close_any_modal(page):
    try:
        page.keyboard.press('Escape')
        time.sleep(1)
    except:
        pass
    
    page.evaluate("""
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            const text = btn.textContent.trim();
            if (text === 'Discard') {
                btn.click();
                break;
            }
        }
    """)
    time.sleep(1)

def save_applied_job(job):
    os.makedirs('data', exist_ok=True)
    file_exists = os.path.exists('data/applied_jobs.csv')
    with open('data/applied_jobs.csv', 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['title', 'company', 'status', 'date'])
        if not file_exists:
            writer.writeheader()
        writer.writerow(job)

def load_applied_jobs():
    applied = set()
    if os.path.exists('data/applied_jobs.csv'):
        with open('data/applied_jobs.csv', 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                applied.add(f"{row['title']}_{row['company']}")
    return applied

def apply_to_jobs_on_search_page(page, job_title, max_to_apply, applied_jobs):
    search_jobs(page, job_title)
    time.sleep(3)
    applied_count = 0
    
    job_cards = page.query_selector_all('[data-job-id]')
    print(f"Found {len(job_cards)} jobs for {job_title}")
    
    for card in job_cards:
        if applied_count >= max_to_apply:
            break
            
        try:
            # Force close any open modal first
            close_any_modal(page)
            try:
                page.wait_for_selector('#artdeco-modal-outlet:empty', timeout=3000)
            except:
                pass
            time.sleep(1)
            
            # Get title and company
            title_el = (
                card.query_selector('a.job-card-list__title') or
                card.query_selector('[class*="job-card-list__title"]')
            )
            company_el = (
                card.query_selector('.job-card-container__primary-description') or
                card.query_selector('[class*="primary-description"]')
            )
            
            title = title_el.inner_text().strip() if title_el else 'Unknown'
            company = company_el.inner_text().strip() if company_el else 'Unknown'
            
            # Skip if already applied
            job_key = f"{title}_{company}"
            if job_key in applied_jobs:
                print(f"Already applied to {title} - skipping")
                continue
            
            print(f"\nTrying: {title} at {company}")
            
            # Click card to open job details in right panel
            try:
                card.evaluate("el => el.click()")
                time.sleep(3)
            except:
                continue
            
            # Click Easy Apply button in right panel
            easy_apply_btn = page.query_selector('button.jobs-apply-button')
            if not easy_apply_btn:
                print(f"No Easy Apply for {title} - skipping")
                continue
            
            easy_apply_btn.click()
            time.sleep(2)
            
            # Get location
            location_el = page.query_selector('.job-details-jobs-unified-top-card__primary-description')
            location = location_el.inner_text() if location_el else "United States"
            
            # Fill phone
            phone_field = page.query_selector('input[id*="phoneNumber"]')
            if phone_field:
                phone_field.fill(os.getenv("PHONE", ""))
            
            # Go through form steps
            for step in range(10):
                print(f"Form step {step + 1}...")
                
                # Answer all questions on current page
                handle_form_questions(page, title, location)
                time.sleep(1)
                
                # Use JavaScript to find and click buttons
                result = page.evaluate("""
                    () => {
                        const buttons = document.querySelectorAll('button');
                        for (const btn of buttons) {
                            const text = btn.textContent.trim();
                            if (text === 'Submit application') {
                                btn.click();
                                return 'submitted';
                            }
                        }
                        for (const btn of buttons) {
                            const text = btn.textContent.trim();
                            if (text === 'Review') {
                                btn.click();
                                return 'review';
                            }
                        }
                        for (const btn of buttons) {
                            const text = btn.textContent.trim();
                            if (text === 'Next') {
                                btn.click();
                                return 'next';
                            }
                        }
                        return 'none';
                    }
                """)
                
                print(f"Button clicked: {result}")
                time.sleep(2)
                
                if result == 'review':
                    # After review try to submit
                    time.sleep(1)
                    submitted = page.evaluate("""
                        () => {
                            const buttons = document.querySelectorAll('button');
                            for (const btn of buttons) {
                                if (btn.textContent.trim() === 'Submit application') {
                                    btn.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                    """)
                    if submitted:
                        print(f"✅ Applied to {title} at {company}")
                        applied_count += 1
                        applied_jobs.add(job_key)
                        save_applied_job({
                            'title': title,
                            'company': company,
                            'status': 'applied',
                            'date': time.strftime('%Y-%m-%d')
                        })
                        time.sleep(2)
                        break

                elif result == 'submitted':
                    print(f"✅ Applied to {title} at {company}")
                    applied_count += 1
                    applied_jobs.add(job_key)
                    save_applied_job({
                        'title': title,
                        'company': company,
                        'status': 'applied',
                        'date': time.strftime('%Y-%m-%d')
                    })
                    time.sleep(2)
                    break

                elif result == 'none':
                    print(f"No button found - closing and moving on")
                    close_any_modal(page)
                    break
                    
        except Exception as e:
            print(f"Error: {e}")
            close_any_modal(page)
            continue
    
    return applied_count

def run_apply(job_titles, max_applications=15):
    remaining = check_daily_limit(limit=15)
    if remaining == 0:
        return
    
    applied_jobs = load_applied_jobs()
    total_applied = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        login_linkedin(page, context)

        for job_title in job_titles:
            if total_applied >= remaining:
                break
            
            count = apply_to_jobs_on_search_page(
                page,
                job_title,
                remaining - total_applied,
                applied_jobs
            )
            total_applied += count
            time.sleep(3)

        browser.close()

    print(f"\nDone! Applied to {total_applied} jobs today!")
    print("Check data/applied_jobs.csv for the full list")

if __name__ == "__main__":
    JOB_TITLES = [
        "Entry Level Software Developer",
        "Entry Level Data Analyst",
        "Junior Python Developer",
        "Entry Level AI Engineer",
        "Data Science Analyst"
    ]

    run_apply(JOB_TITLES, max_applications=15)