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
# Custom dropdown helpers
# ---------------------------------------------------------------------------

def _collect_listbox_options(page):
    """Return all currently visible (role=option) elements from anywhere on the page."""
    for selector in [
        '[role="option"]',
        '[role="listbox"] li',
        '.basic-typeahead__triggered-content [data-view-name]',
        '.artdeco-dropdown__content li',
        '.artdeco-dropdown__content [role="option"]',
    ]:
        els = page.query_selector_all(selector)
        options = []
        for el in els:
            try:
                if el.is_visible():
                    text = el.inner_text().strip()
                    if text and text.lower() not in ('', 'select an option', 'please select'):
                        options.append((text, el))
            except Exception:
                continue
        if options:
            return options
    return []


def _click_best_option(options, answer):
    """Click the option whose text best matches answer; fall back to the first option."""
    answer_lower = answer.lower()
    for opt_text, opt_el in options:
        if answer_lower in opt_text.lower() or opt_text.lower() in answer_lower:
            try:
                opt_el.click()
                return True
            except Exception:
                continue
    try:
        options[0][1].click()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Form question handler
# ---------------------------------------------------------------------------

def handle_form_questions(page, job_title, location):
    """Fill every visible form element on the current Easy Apply step using AI."""
    # [data-test-form-element] is only on the outermost wrapper, so it avoids
    # the nested-duplicate problem caused by partial class matching.
    question_items = page.query_selector_all(
        '.jobs-easy-apply-form-element, '
        '[data-test-form-element]'
    )

    for item in question_items:
        try:
            # Try multiple label selectors; fall back to aria-label on the input
            label_el = item.query_selector(
                'label, legend, span.t-bold, span[class*="t-bold"], '
                '[data-test-form-builder-id] > span'
            )
            if label_el:
                question = label_el.inner_text().strip()
            else:
                any_input = item.query_selector(
                    'input, select, textarea, [role="combobox"]'
                )
                question = (
                    (any_input.get_attribute('aria-label') or '').strip()
                    if any_input else ''
                )

            # Strip required markers so the AI sees a clean question
            question = question.replace('*', '').replace('(required)', '').strip()
            if not question:
                continue

            print(f"    Q: {question[:80]}")

            # --- known-field fast-path (no AI call needed) ---
            q_lower = question.lower()
            _full_name = os.getenv("FULL_NAME", "")
            _name_parts = _full_name.split()

            # 1. Contact / personal text fields
            _text_map = {
                'first name':  _name_parts[0] if _name_parts else '',
                'last name':   _name_parts[-1] if len(_name_parts) > 1 else '',
                'email':       os.getenv("EMAIL", ""),
                'phone':       os.getenv("PHONE", ""),
                'mobile':      os.getenv("PHONE", ""),
                'linkedin':    os.getenv("LINKEDIN_URL", ""),
                'github':      os.getenv("GITHUB_URL", ""),
                'portfolio':   os.getenv("PORTFOLIO_URL", ""),
                'website':     os.getenv("PORTFOLIO_URL", ""),
                'gpa':         os.getenv("GPA", ""),
                'salary':      os.getenv("SALARY_EXPECTATION", "70000"),
            }
            _handled = False
            for keyword, value in _text_map.items():
                if keyword in q_lower and value:
                    inp = item.query_selector('input, textarea')
                    if inp:
                        try:
                            if not inp.input_value():
                                inp.fill(value)
                                print(f"    A (profile/{keyword}): {value[:60]}")
                                time.sleep(0.2)
                        except Exception:
                            pass
                    _handled = True
                    break

            # 2. Work history text fields
            if not _handled:
                _work_map = {
                    'your title':   os.getenv("CURRENT_TITLE", ""),
                    'job title':    os.getenv("CURRENT_TITLE", ""),
                    'company':      os.getenv("CURRENT_EMPLOYER", ""),
                    'employer':     os.getenv("CURRENT_EMPLOYER", ""),
                    'description':  os.getenv("WORK_DESCRIPTION", ""),
                }
                for keyword, value in _work_map.items():
                    if keyword in q_lower and value:
                        inp = item.query_selector('input, textarea')
                        if inp:
                            try:
                                if not inp.input_value():
                                    inp.fill(value)
                                    print(f"    A (work/{keyword}): {value[:60]}")
                                    time.sleep(0.2)
                            except Exception:
                                pass
                        _handled = True
                        break

            # 3. Yes/No work-auth questions — answer directly from profile, no AI
            if not _handled:
                _yn_map = [
                    (['authorized to work', 'authorized to be employed', 'legally authorized'],  os.getenv("AUTHORIZED_TO_WORK", "Yes")),
                    (['sponsorship', 'visa sponsor', 'require sponsor'],                          os.getenv("REQUIRE_SPONSORSHIP", "No")),
                    (['commut', 'comfortable travel', 'willing to travel'],                       'Yes'),
                    (['relocat'],                                                                  os.getenv("WILLING_TO_RELOCATE", "Yes")),
                    (['remote', 'work from home', 'work remotely'],                               'Yes'),
                    (['hybrid'],                                                                   os.getenv("HYBRID_AVAILABLE", "Yes")),
                    (['onsite', 'on-site', 'in office', 'in-office'],                             os.getenv("ONSITE_AVAILABLE", "Yes")),
                    (['veteran'],                                                                  os.getenv("VETERAN_STATUS", "No").strip()),
                    (['disability', 'disabled'],                                                   os.getenv("DISABILITY_STATUS", "No").strip()),
                    (['background check', 'drug test', 'drug screen'],                            'Yes'),
                    (['18 years', 'at least 18', 'over 18'],                                      'Yes'),
                ]
                for keywords, yn_answer in _yn_map:
                    if any(kw in q_lower for kw in keywords):
                        # Try radio first
                        radios = item.query_selector_all('input[type="radio"]')
                        if radios:
                            for r in radios:
                                rid = r.get_attribute('id')
                                lbl = page.query_selector(f'label[for="{rid}"]') if rid else None
                                if lbl and yn_answer.lower() in lbl.inner_text().lower():
                                    r.evaluate("el => el.click()")
                                    print(f"    A (yn-radio/{yn_answer}): {question[:50]}")
                                    time.sleep(0.2)
                                    _handled = True
                                    break
                            if not _handled and radios:
                                # fallback: click Yes (first) or No based on answer
                                idx = 0 if yn_answer.lower() == 'yes' else 1
                                radios[min(idx, len(radios)-1)].evaluate("el => el.click()")
                                print(f"    A (yn-radio-fallback/{yn_answer}): {question[:50]}")
                                _handled = True
                        if not _handled:
                            # Try select
                            sel = item.query_selector('select')
                            if sel:
                                try:
                                    sel.select_option(label=yn_answer)
                                    print(f"    A (yn-select/{yn_answer}): {question[:50]}")
                                    _handled = True
                                except Exception:
                                    try:
                                        sel.select_option(index=1)
                                        _handled = True
                                    except Exception:
                                        pass
                        if _handled:
                            break

            # 4. "Years of experience with X" — map to env vars, no AI needed
            if not _handled and 'year' in q_lower and ('experience' in q_lower or 'work' in q_lower):
                _tech_map = {
                    'python':           os.getenv("YEARS_PYTHON", "3"),
                    'java ':            os.getenv("YEARS_JAVA", "4"),
                    'javascript':       os.getenv("YEARS_JAVASCRIPT", "2"),
                    'react':            os.getenv("YEARS_REACT", "1"),
                    'sql':              os.getenv("YEARS_SQL", "2"),
                    'firebase':         os.getenv("YEARS_FIREBASE", "2"),
                    'data analysis':    os.getenv("YEARS_DATA_ANALYSIS", "1"),
                    'machine learning': os.getenv("YEARS_MACHINE_LEARNING", "1"),
                    'docker':           os.getenv("YEARS_DOCKER", "1"),
                    'git':              os.getenv("YEARS_GIT", "4"),
                    'css':              os.getenv("YEARS_CSS", "2"),
                    'html':             os.getenv("YEARS_HTML", "2"),
                    'c++':              os.getenv("YEARS_CPP", "2"),
                    'database':         os.getenv("YEARS_SQL", "2"),
                    'open-source':      '1',
                    'open source':      '1',
                    'software':         os.getenv("YEARS_PROFESSIONAL", "0"),
                    'construction':     '0',
                    'commissioning':    '0',
                    'manufacturing':    '0',
                    'aerospace':        '0',
                }
                for tech, years in _tech_map.items():
                    if tech in q_lower:
                        inp = item.query_selector('input[type="number"], input[type="text"]')
                        if inp:
                            try:
                                if not inp.input_value():
                                    inp.fill(years)
                                    print(f"    A (years/{tech}): {years}")
                                    time.sleep(0.2)
                                    _handled = True
                            except Exception:
                                pass
                        if _handled:
                            break
                if not _handled:
                    # Generic "years of experience" with unknown tech → answer 0
                    inp = item.query_selector('input[type="number"], input[type="text"]')
                    if inp:
                        try:
                            if not inp.input_value():
                                inp.fill('0')
                                print(f"    A (years/generic=0): {question[:50]}")
                                time.sleep(0.2)
                                _handled = True
                        except Exception:
                            pass

            # Location / city — combobox typeahead: type city then pick first suggestion
            if any(k in q_lower for k in ('city', 'location', 'address')):
                city_val = os.getenv("CURRENT_CITY", "") + ", " + os.getenv("CURRENT_STATE", "")
                cb = item.query_selector('[role="combobox"], input[aria-autocomplete]')
                if cb:
                    try:
                        current = cb.input_value()
                        if not current:
                            cb.click()
                            time.sleep(0.3)
                            cb.fill('')
                            cb.type(os.getenv("CURRENT_CITY", "El Paso"), delay=80)
                            time.sleep(1.5)
                            try:
                                page.wait_for_selector('[role="option"]', timeout=4000)
                                options = page.query_selector_all('[role="option"]')
                                if options:
                                    options[0].click()
                                    print(f"    A (location combobox): {city_val}")
                                    time.sleep(0.5)
                            except PlaywrightTimeoutError:
                                cb.fill(city_val)
                                print(f"    A (location fill): {city_val}")
                    except Exception as e:
                        print(f"    location fill error: {e}")
                else:
                    inp = item.query_selector('input')
                    if inp:
                        try:
                            if not inp.input_value():
                                inp.fill(city_val)
                                print(f"    A (location fill): {city_val}")
                        except Exception:
                            pass

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
                # If already has a non-placeholder value, leave it alone
                cur_val = select.input_value()
                cur_label = ''
                try:
                    cur_label = select.evaluate(
                        "el => el.options[el.selectedIndex]?.text || ''"
                    ).strip().lower()
                except Exception:
                    pass
                if cur_val and cur_label not in ('', 'select an option', 'please select'):
                    print(f"    A (select already set): {cur_label[:60]}")
                    continue

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

            # --- LinkedIn custom dropdown (combobox / artdeco-dropdown / listbox) ---
            # Three escalating attempts; options are rendered outside item in the DOM.
            custom_trigger = item.query_selector(
                '[role="combobox"], '
                'input[aria-autocomplete], '
                'button[aria-haspopup="listbox"], '
                'button.artdeco-dropdown__trigger'
            )
            if custom_trigger:
                handled = False

                # Attempt 1: click trigger → wait for options → click best match
                try:
                    custom_trigger.click()
                    time.sleep(1)
                    try:
                        page.wait_for_selector('[role="option"]', timeout=3000)
                    except PlaywrightTimeoutError:
                        pass
                    options = _collect_listbox_options(page)
                    if options:
                        answer = get_answer(
                            question,
                            options=[t for t, _ in options],
                            job_title=job_title,
                            location=location,
                        )
                        _click_best_option(options, answer)
                        print(f"    A (dropdown-click): {answer[:60]}")
                        time.sleep(0.5)
                        handled = True
                except Exception as e:
                    print(f"    dropdown-click failed: {e}")

                # Attempt 2: type partial answer to trigger autocomplete, then click
                if not handled:
                    combobox_input = item.query_selector(
                        '[role="combobox"], input[aria-autocomplete]'
                    )
                    if combobox_input:
                        try:
                            answer = get_answer(
                                question, job_title=job_title, location=location
                            )
                            combobox_input.click()
                            time.sleep(0.4)
                            combobox_input.fill('')
                            combobox_input.type(answer[:15], delay=80)
                            time.sleep(1)
                            try:
                                page.wait_for_selector('[role="option"]', timeout=3000)
                            except PlaywrightTimeoutError:
                                pass
                            options = _collect_listbox_options(page)
                            if options:
                                _click_best_option(options, answer)
                                print(f"    A (dropdown-type): {answer[:60]}")
                                time.sleep(0.5)
                                handled = True
                        except Exception as e:
                            print(f"    dropdown-type failed: {e}")

                # Attempt 3: JS native value setter (React-compatible) + hidden select
                if not handled:
                    try:
                        answer = get_answer(
                            question, job_title=job_title, location=location
                        )
                        result_js = item.evaluate(
                            """(el, ans) => {
                                // Combobox: use React-compatible native setter
                                const cb = el.querySelector('[role="combobox"], input[aria-autocomplete]');
                                if (cb) {
                                    const setter = Object.getOwnPropertyDescriptor(
                                        HTMLInputElement.prototype, 'value').set;
                                    setter.call(cb, ans);
                                    ['input','change'].forEach(ev =>
                                        cb.dispatchEvent(new Event(ev, {bubbles:true})));
                                    return 'combobox-js';
                                }
                                // Hidden <select> backing the custom component
                                const sel = el.querySelector('select');
                                if (sel) {
                                    const ansL = ans.toLowerCase();
                                    for (const opt of sel.options) {
                                        if (opt.text.toLowerCase().includes(ansL.slice(0,8))) {
                                            sel.value = opt.value;
                                            sel.dispatchEvent(new Event('change', {bubbles:true}));
                                            return 'hidden-select';
                                        }
                                    }
                                    if (sel.options.length > 1) {
                                        sel.value = sel.options[1].value;
                                        sel.dispatchEvent(new Event('change', {bubbles:true}));
                                        return 'hidden-select-fallback';
                                    }
                                }
                                return null;
                            }""",
                            answer,
                        )
                        if result_js:
                            print(f"    A (JS/{result_js}): {answer[:60]}")
                            handled = True
                    except Exception as e:
                        print(f"    JS attempt failed: {e}")

                if not handled:
                    # Last resort: force-click the first visible option via JS
                    forced = page.evaluate("""
                        () => {
                            const opts = document.querySelectorAll('[role="option"]');
                            for (const o of opts) {
                                if (o.offsetParent !== null) { o.click(); return 'option'; }
                            }
                            return null;
                        }
                    """)
                    if not forced:
                        # No open listbox — try to JS-select first option of a hidden select
                        forced = item.evaluate("""
                            (el) => {
                                const sel = el.querySelector('select');
                                if (sel && sel.options.length > 1) {
                                    sel.value = sel.options[1].value;
                                    sel.dispatchEvent(new Event('change', {bubbles:true}));
                                    return 'select';
                                }
                                return null;
                            }
                        """)
                    if forced:
                        print(f"    A (forced-first/{forced}): {question[:60]}")
                    else:
                        page.keyboard.press('Escape')
                        time.sleep(0.3)
                        print(f"    ⚠️  Dropdown unfillable (continuing anyway): {question[:60]}")

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

    # --- Required-field safety net ---
    # Second pass: any required input still empty after the main loop gets a
    # safe generic answer so validation cannot block the Next/Submit button.
    try:
        for field in page.query_selector_all(
            'input[required], select[required], textarea[required], '
            '[aria-required="true"]'
        ):
            if not field.is_visible():
                continue
            try:
                val = field.input_value()
            except Exception:
                continue
            if val:
                continue

            tag = field.evaluate("el => el.tagName.toLowerCase()")
            field_type = (field.get_attribute('type') or 'text').lower()
            fid = field.get_attribute('id') or ''
            lbl = page.query_selector(f'label[for="{fid}"]') if fid else None
            label_text = (
                lbl.inner_text().strip() if lbl
                else field.get_attribute('aria-label') or 'field'
            ).replace('*', '').strip()

            if tag == 'select':
                try:
                    field.select_option(index=1)
                    print(f"    ⚡ safety-net select: {label_text[:50]}")
                except Exception:
                    pass
            elif field_type == 'number':
                field.fill('1')
                print(f"    ⚡ safety-net number=1: {label_text[:50]}")
            else:
                answer = get_answer(label_text, job_title=job_title, location=location)
                try:
                    field.fill(str(answer))
                    print(f"    ⚡ safety-net text: {label_text[:50]} = {str(answer)[:40]}")
                except Exception:
                    pass
            time.sleep(0.2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Validation error inspector
# ---------------------------------------------------------------------------

def check_and_print_errors(page):
    """
    Scan the current form step for validation errors and unanswered required fields.
    Prints a detailed report so we can see exactly what the bot is missing.
    Returns a list of error strings (empty list = clean).
    """
    errors = []

    # Explicit error messages LinkedIn renders
    for sel in [
        '.artdeco-inline-feedback--error',
        '[data-test-form-element-error-message]',
        '[class*="error-message"]',
        '[class*="inline-feedback"]',
    ]:
        try:
            for el in page.query_selector_all(sel):
                if el.is_visible():
                    text = el.inner_text().strip()
                    if text:
                        errors.append(f"error: {text}")
        except Exception:
            continue

    # Fields marked aria-invalid="true"
    try:
        for field in page.query_selector_all('[aria-invalid="true"]'):
            fid = field.get_attribute('id')
            lbl = page.query_selector(f'label[for="{fid}"]') if fid else None
            label_text = lbl.inner_text().strip() if lbl else field.get_attribute('aria-label') or 'unknown'
            errors.append(f"invalid field: {label_text}")
    except Exception:
        pass

    # Required fields that are still empty
    try:
        for field in page.query_selector_all(
            'input[required], select[required], textarea[required], '
            '[aria-required="true"]'
        ):
            if not field.is_visible():
                continue
            val = ''
            try:
                val = field.input_value()
            except Exception:
                pass
            if not val:
                fid = field.get_attribute('id')
                lbl = page.query_selector(f'label[for="{fid}"]') if fid else None
                label_text = (
                    lbl.inner_text().strip() if lbl
                    else field.get_attribute('aria-label') or field.get_attribute('name') or 'unnamed'
                )
                errors.append(f"empty required: {label_text}")
    except Exception:
        pass

    if errors:
        print(f"  ⚠️  Form issues ({len(errors)}):")
        for e in errors:
            print(f"      • {e}")
    else:
        print("  ✓  No validation errors detected")

    return errors


# ---------------------------------------------------------------------------
# Blocker detection (CAPTCHA / mandatory file upload)
# ---------------------------------------------------------------------------

def has_blocker(page):
    """Return True only if there is a CAPTCHA or a required file-upload field."""
    for sel in [
        'iframe[src*="recaptcha"]', 'iframe[src*="captcha"]',
        '[class*="captcha"]', '#recaptcha',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                print("  🚫 CAPTCHA detected")
                return True
        except Exception:
            continue
    try:
        for finput in page.query_selector_all('input[type="file"][required]'):
            if finput.is_visible():
                print("  🚫 Required file upload (cannot handle)")
                return True
    except Exception:
        pass
    return False


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
            last_error_sig = None
            stuck_count = 0

            for step in range(MAX_FORM_STEPS):
                print(f"  Step {step + 1}…")
                time.sleep(1.5)

                handle_form_questions(page, title, location)
                errors = check_and_print_errors(page)
                time.sleep(0.5)

                # Detect stuck loop: same errors 3 steps in a row → give up on this job
                err_sig = tuple(sorted(errors))
                if err_sig and err_sig == last_error_sig:
                    stuck_count += 1
                    if stuck_count >= 3:
                        print(f"  Stuck on same errors for {stuck_count} steps — discarding")
                        break
                else:
                    stuck_count = 0
                last_error_sig = err_sig

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
                    if has_blocker(page):
                        print("  Aborting: unresolvable blocker (CAPTCHA / file upload)")
                        break
                    # No button yet but no hard blocker — wait and retry this step
                    print("  No button found — waiting and retrying…")
                    time.sleep(2)

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

            try:
                count = apply_to_jobs_on_search_page(
                    page,
                    job_title,
                    max_to_apply - total_applied,
                    applied_jobs,
                )
                total_applied += count
            except Exception as e:
                if 'closed' in str(e).lower() or 'target' in str(e).lower():
                    print(f"\n⚠️  Browser was closed — stopping gracefully.")
                    break
                print(f"Error on '{job_title}': {e}")
                continue
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
