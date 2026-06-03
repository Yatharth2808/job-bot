"""
debug_form.py — dry-run inspector for the Easy Apply form.

Opens LinkedIn, finds the first Easy-Apply job for each title,
opens the modal, and dumps:
  • raw HTML of the modal
  • every question/field detected
  • what the AI would answer
  • every form element found by the broader selector

Does NOT click Next, Review, or Submit — discards the modal after inspection.
Run with:  venv/bin/python debug_form.py
"""

import os
import sys
import time
import json

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from ai_tools.question_handler import get_answer

load_dotenv()

JOB_TITLES = [
    "Entry Level Software Developer",
    "Entry Level Data Analyst",
]
JOBS_PER_TITLE = 2   # inspect this many jobs per title then stop


# ---------------------------------------------------------------------------

def login(page, context):
    cookies_file = 'data/linkedin_cookies.json'
    if os.path.exists(cookies_file):
        with open(cookies_file) as f:
            context.add_cookies(json.load(f))
        page.goto("https://www.linkedin.com/feed")
        time.sleep(3)
        if 'login' not in page.url and 'checkpoint' not in page.url:
            print("✓ Logged in via saved cookies")
            return
    page.goto("https://www.linkedin.com/login")
    input("Please log in manually then press ENTER…")
    with open(cookies_file, 'w') as f:
        json.dump(context.cookies(), f)


def dump_modal_dom(page):
    """Print the inner HTML of the Easy Apply modal (truncated)."""
    html = page.evaluate("""
        () => {
            const modal = document.querySelector(
                '.jobs-easy-apply-modal, [data-test-modal-id]'
            );
            return modal ? modal.innerHTML : '(modal not found)';
        }
    """)
    print("\n" + "="*70)
    print("MODAL DOM (first 4000 chars):")
    print("="*70)
    print(html[:4000])
    print("="*70 + "\n")


def dump_all_inputs(page):
    """List every input/select/textarea/role=combobox inside the modal."""
    fields = page.evaluate("""
        () => {
            const modal = document.querySelector(
                '.jobs-easy-apply-modal, [data-test-modal-id]'
            );
            if (!modal) return [];
            const out = [];
            modal.querySelectorAll(
                'input, select, textarea, [role="combobox"], [role="listbox"]'
            ).forEach(el => {
                const label_el = document.querySelector(
                    `label[for="${el.id}"]`
                );
                out.push({
                    tag: el.tagName,
                    type: el.type || el.getAttribute('role') || '',
                    id: el.id || '',
                    name: el.name || '',
                    value: el.value || '',
                    aria_label: el.getAttribute('aria-label') || '',
                    aria_required: el.getAttribute('aria-required') || '',
                    required: el.required || false,
                    label: label_el ? label_el.innerText.trim() : '',
                    visible: el.offsetParent !== null,
                    classes: el.className.slice(0, 80),
                });
            });
            return out;
        }
    """)
    print(f"\n{'='*70}")
    print(f"ALL INPUTS IN MODAL ({len(fields)} found):")
    print(f"{'='*70}")
    for f in fields:
        req = " [REQUIRED]" if f['required'] or f['aria_required'] == 'true' else ""
        vis = "" if f['visible'] else " [hidden]"
        label = f['label'] or f['aria_label'] or '—'
        print(
            f"  {f['tag']:<12} type={f['type']:<14} "
            f"label={label[:50]:<52} value={repr(f['value'])[:30]}{req}{vis}"
        )
    print()


def dump_form_elements(page):
    """Run the same selector the bot uses and show every question + simulated answer."""
    items = page.query_selector_all(
        '.jobs-easy-apply-form-element, '
        '[class*="fb-dash-form-element"], '
        '[class*="text-entity-list-form-component"]'
    )
    print(f"{'='*70}")
    print(f"FORM ELEMENTS MATCHED BY BOT SELECTOR ({len(items)} items):")
    print(f"{'='*70}")

    for i, item in enumerate(items):
        try:
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
            question_clean = question.replace('*', '').replace('(required)', '').strip()

            # Detect field type
            field_type = 'unknown'
            extra = ''
            if item.query_selector('input[type="text"], input[type="number"], textarea'):
                field_type = 'text/number/textarea'
            elif item.query_selector('input[type="email"]'):
                field_type = 'email'
            elif item.query_selector('select'):
                opts = [o.inner_text().strip() for o in item.query_selector_all('option')]
                field_type = 'select'
                extra = f"options={opts[:5]}"
            elif item.query_selector('[role="combobox"], input[aria-autocomplete]'):
                field_type = 'custom-combobox'
            elif item.query_selector('button[aria-haspopup="listbox"], button.artdeco-dropdown__trigger'):
                field_type = 'custom-dropdown-btn'
            elif item.query_selector_all('input[type="radio"]'):
                radios = item.query_selector_all('input[type="radio"]')
                opts = []
                for r in radios:
                    rid = r.get_attribute('id')
                    lbl = page.query_selector(f'label[for="{rid}"]') if rid else None
                    if lbl:
                        opts.append(lbl.inner_text().strip())
                field_type = 'radio'
                extra = f"options={opts}"
            elif item.query_selector_all('input[type="checkbox"]'):
                field_type = 'checkbox'

            # Simulate AI answer
            ai_answer = '—'
            if question_clean:
                try:
                    ai_answer = get_answer(question_clean, job_title="Software Developer",
                                          location="United States")
                except Exception as e:
                    ai_answer = f"ERROR: {e}"

            print(f"\n  [{i+1}] Q : {question_clean[:80] or '(no label found)'}")
            print(f"       raw: {question[:80]}")
            print(f"       type: {field_type}  {extra[:80]}")
            print(f"       AI  : {str(ai_answer)[:80]}")

        except Exception as e:
            print(f"\n  [{i+1}] ERROR reading item: {e}")

    print()


def discard(page):
    try:
        page.keyboard.press('Escape')
        time.sleep(1.5)
        page.wait_for_selector('button:has-text("Discard")', timeout=3000)
        page.click('button:has-text("Discard")')
        time.sleep(1)
    except Exception:
        pass


def inspect_job(page, card, idx):
    title_el = (
        card.query_selector('a.job-card-list__title') or
        card.query_selector('[class*="job-card-list__title"]')
    )
    title = title_el.inner_text().strip() if title_el else f'Card-{idx}'

    print(f"\n{'#'*70}")
    print(f"  JOB {idx}: {title}")
    print(f"{'#'*70}")

    try:
        card.evaluate("el => el.click()")
        time.sleep(3)
    except Exception as e:
        print(f"  Could not click card: {e}")
        return

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
        print("  No Easy Apply button — skipping this job")
        return

    easy_apply_btn.click()
    time.sleep(2)

    # Dump the modal DOM, all raw inputs, and the bot's form element view
    dump_modal_dom(page)
    dump_all_inputs(page)
    dump_form_elements(page)

    discard(page)
    time.sleep(1)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        login(page, context)

        for job_title in JOB_TITLES:
            print(f"\n\n{'*'*70}")
            print(f"  SEARCHING: {job_title}")
            print(f"{'*'*70}")

            url = (
                f"https://www.linkedin.com/jobs/search/"
                f"?keywords={job_title.replace(' ', '%20')}"
                f"&location=United%20States&f_AL=true&f_E=1%2C2"
            )
            page.goto(url)
            time.sleep(5)
            page.evaluate("window.scrollTo(0, 500)")
            time.sleep(2)

            cards = page.query_selector_all('[data-job-id]')
            print(f"  Found {len(cards)} job cards")

            inspected = 0
            for idx, card in enumerate(cards):
                if inspected >= JOBS_PER_TITLE:
                    break
                inspect_job(page, card, idx + 1)
                inspected += 1
                time.sleep(1)

        browser.close()
    print("\n\nDebug run complete.")


if __name__ == '__main__':
    main()
