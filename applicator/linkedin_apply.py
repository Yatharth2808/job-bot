import os
import sys
import time
import csv
import json
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_tools.question_handler import get_answer, get_smart_salary

load_dotenv()

DAILY_LIMIT = 15
MAX_FORM_STEPS = 15


# ---------------------------------------------------------------------------
# Daily limit & persistence
# ---------------------------------------------------------------------------

def check_daily_limit(limit=DAILY_LIMIT):
    today = time.strftime('%Y-%m-%d')
    daily_count = 0

    if os.path.exists('data/applied_jobs.csv'):
        with open('data/applied_jobs.csv', 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('date') == today:
                    daily_count += 1

    print(f"Today's applications: {daily_count}/{limit}")
    if daily_count >= limit:
        print("Daily limit reached! Come back tomorrow.")
        return 0

    remaining = limit - daily_count
    print(f"Remaining applications today: {remaining}")
    return remaining


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


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login_linkedin(page, context):
    cookies_file = 'data/linkedin_cookies.json'

    if os.path.exists(cookies_file):
        print("Loading saved LinkedIn session...")
        with open(cookies_file, 'r') as f:
            cookies = json.load(f)
        context.add_cookies(cookies)
        page.goto("https://www.linkedin.com/feed")
        time.sleep(3)

        if 'login' in page.url or 'checkpoint' in page.url:
            print("Session expired — please log in manually...")
            page.goto("https://www.linkedin.com/login")
            input("Press ENTER after you have logged in successfully...")
            cookies = context.cookies()
            with open(cookies_file, 'w') as f:
                json.dump(cookies, f)
            print("Session saved!")
        else:
            print("Logged in using saved session!")
        return

    print("Please log in to LinkedIn manually in the browser window...")
    page.goto("https://www.linkedin.com/login")
    input("Press ENTER after you have logged in successfully...")

    cookies = context.cookies()
    os.makedirs('data', exist_ok=True)
    with open(cookies_file, 'w') as f:
        json.dump(cookies, f)
    print("Session saved! Won't need to login again.")


# ---------------------------------------------------------------------------
# Job search
# ---------------------------------------------------------------------------

def search_jobs(page, job_title, location="United States"):
    print(f"\nSearching for: {job_title}...")
    encoded_title = job_title.replace(' ', '%20')
    encoded_loc = location.replace(' ', '%20')
    # f_AL=true → Easy Apply only; f_E=1,2 → Entry/Associate level
    url = (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={encoded_title}&location={encoded_loc}&f_AL=true&f_E=1%2C2"
    )
    page.goto(url)
    time.sleep(5)
    page.evaluate("window.scrollTo(0, 500)")
    time.sleep(2)


# ---------------------------------------------------------------------------
# Company name extraction
# ---------------------------------------------------------------------------

def get_company_from_card(card):
    """Try multiple selectors to pull the company name out of a job list card."""
    selectors = [
        '.job-card-container__primary-description',
        '[class*="primary-description"]',
        '.artdeco-entity-lockup__subtitle',
        '[class*="entity-lockup__subtitle"]',
        '.job-card-container__company-name',
        '[class*="company-name"]',
        '.job-card-list__company-name',
    ]
    for sel in selectors:
        try:
            el = card.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if text:
                    return text
        except Exception:
            continue
    return None


def get_company_from_detail_panel(page):
    """Try to read company name from the right-side job detail panel."""
    selectors = [
        '.job-details-jobs-unified-top-card__company-name a',
        '.jobs-unified-top-card__company-name a',
        '.job-details-jobs-unified-top-card__company-name',
        '.jobs-unified-top-card__company-name',
        '[class*="top-card__company-name"]',
        'a[data-tracking-control-name*="company"]',
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if text:
                    return text
        except Exception:
            continue
    return 'Unknown'


# ---------------------------------------------------------------------------
# Modal management
# ---------------------------------------------------------------------------

def close_success_modal(page):
    """Click 'Done' on the post-submission success modal."""
    for selector in [
        'button:has-text("Done")',
        'button[aria-label="Dismiss"]',
        'button[aria-label="Close"]',
    ]:
        try:
            page.wait_for_selector(selector, timeout=5000)
            page.click(selector)
            time.sleep(1)
            return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    # JS fallback
    try:
        page.evaluate("""
            const candidates = ['Done', 'Dismiss', 'Close'];
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                if (candidates.includes(btn.textContent.trim())) {
                    btn.click();
                    break;
                }
            }
        """)
        time.sleep(1)
    except Exception:
        pass


def discard_and_close(page):
    """
    Discard an in-progress Easy Apply application.
    LinkedIn flow: Escape → 'Discard application?' dialog → click 'Discard'.
    """
    try:
        page.keyboard.press('Escape')
        time.sleep(1.5)
    except Exception:
        pass

    # Wait for the discard confirmation dialog
    for selector in [
        'button:has-text("Discard")',
        'button[data-control-name="discard_application_confirm_btn"]',
    ]:
        try:
            page.wait_for_selector(selector, timeout=3000)
            page.click(selector)
            time.sleep(1)
            return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    # JS fallback
    try:
        page.evaluate("""
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                if (btn.textContent.trim() === 'Discard') {
                    btn.click();
                    break;
                }
            }
        """)
        time.sleep(1)
    except Exception:
        pass


def wait_for_modal_gone(page, timeout_ms=5000):
    """Block until the Easy Apply modal is out of the DOM/hidden."""
    for selector in [
        '.jobs-easy-apply-modal',
        '[data-test-modal-id="easy-apply-modal"]',
    ]:
        try:
            page.wait_for_selector(selector, state='hidden', timeout=timeout_ms)
            return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    time.sleep(1)


# ---------------------------------------------------------------------------
# Form question handler
# ---------------------------------------------------------------------------

def handle_form_questions(page, job_title, location):
    """Fill every visible form element on the current Easy Apply step using AI."""
    question_items = page.query_selector_all('.jobs-easy-apply-form-element')

    for item in question_items:
        try:
            label_el = item.query_selector('label, legend, span.t-bold')
            if not label_el:
                continue
            question = label_el.inner_text().strip()
            if not question:
                continue

            print(f"    Q: {question[:80]}")

            # --- text / number / textarea ---
            text_input = item.query_selector(
                'input[type="text"], input[type="number"], textarea'
            )
            if text_input:
                if not text_input.input_value():
                    answer = get_answer(question, job_title=job_title, location=location)
                    text_input.fill(str(answer))
                    print(f"    A: {str(answer)[:60]}")
                    time.sleep(0.3)
                continue

            # --- email ---
            email_input = item.query_selector('input[type="email"]')
            if email_input:
                if not email_input.input_value():
                    email_input.fill(os.getenv("EMAIL", ""))
                continue

            # --- select dropdown ---
            select = item.query_selector('select')
            if select:
                options = []
                for opt in select.query_selector_all('option'):
                    text = opt.inner_text().strip()
                    if text and text.lower() not in (
                        'select an option', 'please select', '--', ''
                    ):
                        options.append(text)
                if options:
                    answer = get_answer(
                        question, options=options, job_title=job_title, location=location
                    )
                    try:
                        select.select_option(label=answer)
                    except Exception:
                        try:
                            select.select_option(index=1)
                        except Exception:
                            pass
                    print(f"    A: {answer[:60]}")
                    time.sleep(0.3)
                continue

            # --- radio buttons ---
            radios = item.query_selector_all('input[type="radio"]')
            if radios:
                options = []
                radio_map = {}
                for radio in radios:
                    rid = radio.get_attribute("id")
                    lbl = page.query_selector(f'label[for="{rid}"]') if rid else None
                    if lbl:
                        text = lbl.inner_text().strip()
                        options.append(text)
                        radio_map[text.lower()] = radio

                if options:
                    answer = get_answer(
                        question, options=options, job_title=job_title, location=location
                    )
                    answer_lower = answer.lower()
                    clicked = False
                    for opt_text, radio in radio_map.items():
                        if answer_lower in opt_text or opt_text in answer_lower:
                            radio.evaluate("el => el.click()")
                            print(f"    A (radio): {opt_text[:60]}")
                            time.sleep(0.3)
                            clicked = True
                            break
                    if not clicked:
                        radios[0].evaluate("el => el.click()")
                        print(f"    A (radio fallback): first option")
                continue

            # --- checkboxes ---
            checkboxes = item.query_selector_all('input[type="checkbox"]')
            if checkboxes:
                for cb in checkboxes:
                    cid = cb.get_attribute("id")
                    lbl = page.query_selector(f'label[for="{cid}"]') if cid else None
                    cb_text = lbl.inner_text().strip() if lbl else ''
                    q = f"{question}: {cb_text}" if cb_text else question
                    answer = get_answer(
                        q, options=["Yes", "No"], job_title=job_title, location=location
                    )
                    if answer.lower() == 'yes' and not cb.is_checked():
                        cb.evaluate("el => el.click()")
                        time.sleep(0.2)
                continue

        except Exception:
            continue


# ---------------------------------------------------------------------------
# Form navigation
# ---------------------------------------------------------------------------

def click_progression_button(page):
    """
    Find and click the right form progression button.
    Priority: Submit application > Review > Next
    Returns: 'submitted' | 'review' | 'next' | 'none'
    """
    # Submit application
    for selector in [
        'button[aria-label="Submit application"]',
        'button:has-text("Submit application")',
    ]:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible() and btn.is_enabled():
                btn.click()
                return 'submitted'
        except Exception:
            continue

    # Review
    for selector in [
        'button[aria-label="Review your application"]',
        'button:has-text("Review")',
    ]:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible() and btn.is_enabled():
                btn.click()
                return 'review'
        except Exception:
            continue

    # Next
    for selector in [
        'button[aria-label="Continue to next step"]',
        'button:has-text("Next")',
    ]:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible() and btn.is_enabled():
                btn.click()
                return 'next'
        except Exception:
            continue

    return 'none'


# ---------------------------------------------------------------------------
# Main apply loop
# ---------------------------------------------------------------------------

def apply_to_jobs_on_search_page(page, job_title, max_to_apply, applied_jobs):
    search_jobs(page, job_title)
    time.sleep(3)
    applied_count = 0

    job_cards = page.query_selector_all('[data-job-id]')
    print(f"Found {len(job_cards)} job cards for '{job_title}'")

    for idx, card in enumerate(job_cards):
        if applied_count >= max_to_apply:
            break

        application_open = False

        try:
            # Make sure no modal is blocking before we start
            discard_and_close(page)
            wait_for_modal_gone(page, timeout_ms=3000)
            time.sleep(0.5)

            # --- extract title ---
            title_el = (
                card.query_selector('a.job-card-list__title') or
                card.query_selector('[class*="job-card-list__title"]') or
                card.query_selector('.job-card-container__link') or
                card.query_selector('a[class*="job-card"]')
            )
            title = title_el.inner_text().strip() if title_el else 'Unknown'
            if title == 'Unknown':
                print(f"Card {idx + 1}: cannot read title — skipping")
                continue

            # --- extract company from card ---
            company = get_company_from_card(card) or 'Unknown'

            # --- skip duplicates ---
            job_key = f"{title}_{company}"
            if job_key in applied_jobs:
                print(f"Already applied: {title} — skipping")
                continue

            print(f"\n[{idx + 1}] {title} @ {company}")

            # --- click card to load detail panel ---
            try:
                card.evaluate("el => el.click()")
                time.sleep(3)
            except Exception as e:
                print(f"  Click failed: {e}")
                continue

            # --- try to enrich company name from detail panel ---
            if company == 'Unknown':
                company = get_company_from_detail_panel(page)
                # Update the key with the real company now
                job_key = f"{title}_{company}"
                if job_key in applied_jobs:
                    print(f"Already applied (post-click): {title} — skipping")
                    continue

            # --- find Easy Apply button ---
            easy_apply_btn = None
            for sel in [
                'button.jobs-apply-button',
                'button[aria-label*="Easy Apply"]',
                'button:has-text("Easy Apply")',
            ]:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        easy_apply_btn = btn
                        break
                except Exception:
                    continue

            if not easy_apply_btn:
                print("  No Easy Apply button — skipping")
                continue

            easy_apply_btn.click()
            time.sleep(2)
            application_open = True

            # --- get job location from detail panel ---
            location_el = page.query_selector(
                '.job-details-jobs-unified-top-card__primary-description'
            )
            location = location_el.inner_text().strip() if location_el else "United States"

            # --- pre-fill phone number if field is present ---
            phone_field = page.query_selector('input[id*="phoneNumber"]')
            if phone_field and not phone_field.input_value():
                phone_field.fill(os.getenv("PHONE", ""))
                time.sleep(0.3)

            # --- multi-step form loop ---
            applied = False

            for step in range(MAX_FORM_STEPS):
                print(f"  Step {step + 1}…")
                time.sleep(1.5)

                handle_form_questions(page, title, location)
                time.sleep(0.5)

                result = click_progression_button(page)
                print(f"  → {result}")

                if result == 'submitted':
                    time.sleep(2)
                    close_success_modal(page)
                    wait_for_modal_gone(page)
                    print(f"  ✅ Applied: {title} at {company}")
                    applied_count += 1
                    applied_jobs.add(job_key)
                    save_applied_job({
                        'title': title,
                        'company': company,
                        'status': 'applied',
                        'date': time.strftime('%Y-%m-%d'),
                    })
                    application_open = False
                    applied = True
                    break

                elif result == 'review':
                    # LinkedIn transitions to a review screen; wait for Submit to appear.
                    print("  Waiting for Submit button on review screen…")
                    try:
                        page.wait_for_selector(
                            'button:has-text("Submit application")', timeout=6000
                        )
                        page.click('button:has-text("Submit application")')
                        time.sleep(2)
                        close_success_modal(page)
                        wait_for_modal_gone(page)
                        print(f"  ✅ Applied: {title} at {company}")
                        applied_count += 1
                        applied_jobs.add(job_key)
                        save_applied_job({
                            'title': title,
                            'company': company,
                            'status': 'applied',
                            'date': time.strftime('%Y-%m-%d'),
                        })
                        application_open = False
                        applied = True
                        break
                    except PlaywrightTimeoutError:
                        # Submit didn't appear — the form may have more steps; keep going
                        print("  Submit not yet visible — continuing form steps")
                        continue

                elif result == 'none':
                    print("  No navigation button found — aborting")
                    break

                # result == 'next': just continue to the next step

            if not applied and application_open:
                print(f"  Could not finish application for '{title}' — discarding")
                discard_and_close(page)
                wait_for_modal_gone(page)

        except Exception as e:
            print(f"  Unexpected error on card {idx + 1}: {e}")
            if application_open:
                try:
                    discard_and_close(page)
                    wait_for_modal_gone(page)
                except Exception:
                    pass
            continue

    return applied_count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_apply(job_titles, max_applications=DAILY_LIMIT):
    remaining = check_daily_limit(limit=DAILY_LIMIT)
    if remaining == 0:
        return

    max_to_apply = min(remaining, max_applications)
    applied_jobs = load_applied_jobs()
    total_applied = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        login_linkedin(page, context)

        for job_title in job_titles:
            if total_applied >= max_to_apply:
                break

            count = apply_to_jobs_on_search_page(
                page,
                job_title,
                max_to_apply - total_applied,
                applied_jobs,
            )
            total_applied += count
            time.sleep(3)

        browser.close()

    print(f"\nDone! Applied to {total_applied} jobs today.")
    print("Check data/applied_jobs.csv for the full list.")


if __name__ == "__main__":
    JOB_TITLES = [
        "Entry Level Software Developer",
        "Entry Level Data Analyst",
        "Junior Python Developer",
        "Entry Level AI Engineer",
        "Data Science Analyst",
    ]

    run_apply(JOB_TITLES, max_applications=15)
