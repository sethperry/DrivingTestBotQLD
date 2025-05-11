import time
from datetime import datetime, timedelta, date
import locale
import os
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --- These values will be set by GitHub Secrets ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USER_DL_NUMBER = os.getenv("USER_DL_NUMBER")
USER_CONTACT_NAME = os.getenv("USER_CONTACT_NAME")
USER_CONTACT_PHONE = os.getenv("USER_CONTACT_PHONE")

# --- Constants for the Bot ---
START_URL = "https://www.service.transport.qld.gov.au/SBSExternal/public/WelcomeDrivingTest.xhtml"
CONTINUE_BUTTON_PAGE1_ID = "j_id_60:aboutThisServiceForm:continueButton"

# Terms and Conditions Page
TERMS_PAGE_URL_FRAGMENT = "TermsAndConditions.xhtml"
# No checkbox mentioned by user, so we can set this to None or a non-matching string to skip it.
TERMS_AGREE_CHECKBOX_SELECTOR = None # Set to None as no checkbox was identified for T&C
# Exact ID for the "Accept" button on the T&C page
TERMS_CONTINUE_BUTTON_SELECTOR = "id=termsAndConditions:TermsAndConditionsForm:acceptButton"

PAGE2_URL_FRAGMENT = "CleanBookingDE.xhtml" # The page after T&C
DL_NUMBER_INPUT_ID = "CleanBookingDEForm:dlNumber"
CONTACT_NAME_INPUT_ID = "CleanBookingDEForm:contactName"
CONTACT_PHONE_INPUT_ID = "CleanBookingDEForm:contactPhone"
TEST_TYPE_DROPDOWN_ID = "CleanBookingDEForm:productType"
TEST_TYPE_OPTION_CAR_ID = "CleanBookingDEForm:productType_1"
CONTINUE_BUTTON_PAGE2_ID = "CleanBookingDEForm:actionFieldList:confirmButtonField:confirmButton"
PAGE3_URL_FRAGMENT = "LicenceDetailsConfirmation.xhtml"
CONTINUE_BUTTON_PAGE3_ID = "BookingConfirmationForm:actionFieldList:confirmButtonField:confirmButton"
PAGE4_URL_FRAGMENT = "LocationSelection.xhtml"
REGION_DROPDOWN_ID = "BookingSearchForm:region"
CONTINUE_BUTTON_PAGE4_ID = "BookingSearchForm:actionFieldList:confirmButtonField:confirmButton"
PAGE5_URL_FRAGMENT = "SlotSelection.xhtml"
SLOT_LABEL_SELECTOR = "label[for^='slotSelectionForm:slotTable:']"
SLOT_TABLE_ID = "slotSelectionForm:slotTable"
CHANGE_LOCATION_BUTTON_PAGE5_ID = "slotSelectionForm:actionFieldList:j_id_6o:j_id_6p"

LOCATIONS_TO_CHECK = [
    {"name": "SEQ BRISBANE NORTHSIDE", "id": "BookingSearchForm:region_12"},
    {"name": "SEQ BRISBANE SOUTHSIDE", "id": "BookingSearchForm:region_13"},
]

def send_telegram_notification(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Telegram Bot Token or Chat ID is not configured as a GitHub Secret.")
        return False
    md_reserved = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    escaped_message = message
    for char in md_reserved:
        escaped_message = escaped_message.replace(char, '\\' + char)
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': escaped_message, 'parse_mode': 'MarkdownV2'}
    try:
        response = requests.post(api_url, data=payload, timeout=10)
        response.raise_for_status()
        print("Telegram notification sent successfully.")
        return True
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to send Telegram notification: {e}")
        return False

def check_slots_on_page5(page, location_name):
    print(f"--- Checking slots for: {location_name} ---")
    suitable_slots = []
    try:
        page.locator(f"id={SLOT_TABLE_ID}").wait_for(state="visible", timeout=15000)
    except PlaywrightTimeoutError:
        print(f"Slot table not found for {location_name}.")
        return suitable_slots
    slot_labels = page.locator(SLOT_LABEL_SELECTOR).all()
    if not slot_labels:
        print(f"No slot labels found for {location_name}.")
        return suitable_slots
    current_check_date = datetime.now().date()
    start_date_window = current_check_date
    end_date_window = start_date_window + timedelta(days=13)
    for label_loc in slot_labels:
        slot_text = label_loc.text_content(timeout=5000).strip()
        if not slot_text: continue
        try:
            slot_datetime_obj = datetime.strptime(slot_text, "%A, %d %B %Y %I:%M %p")
            if start_date_window <= slot_datetime_obj.date() <= end_date_window:
                suitable_slots.append(slot_text)
        except ValueError:
            pass
    if suitable_slots:
        print(f"Found {len(suitable_slots)} suitable slots for {location_name}.")
    else:
        print(f"No suitable slots in the next 14 days for {location_name}.")
    return suitable_slots

def run_bot():
    print(f"Bot run started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, USER_DL_NUMBER, USER_CONTACT_NAME, USER_CONTACT_PHONE]):
        critical_error_msg = "Driving Test Bot CRITICAL ERROR: Required secrets (Telegram/User Details) are not fully configured in GitHub Actions."
        print(critical_error_msg)
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID: send_telegram_notification(critical_error_msg)
        return
    try:
        locale.setlocale(locale.LC_TIME, 'en_AU.UTF-8')
    except locale.Error:
        print("Warning: Australian locale 'en_AU.UTF-8' not available.")

    any_slot_found_overall = False
    browser = None
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36")
            page = context.new_page()

            # Page 1: Welcome Page
            page.goto(START_URL, timeout=60000)
            page.locator(f"id={CONTINUE_BUTTON_PAGE1_ID}").click()

            # === Handle Terms and Conditions Page ===
            print("Looking for Terms and Conditions page...")
            page.wait_for_url(f"**/{TERMS_PAGE_URL_FRAGMENT}**", timeout=30000) 
            print(f"On Terms and Conditions page. URL: {page.url}")

            # Checkbox interaction is now skipped if TERMS_AGREE_CHECKBOX_SELECTOR is None
            if TERMS_AGREE_CHECKBOX_SELECTOR:
                try:
                    agree_checkbox_locator = page.locator(TERMS_AGREEE_CHECKBOX_SELECTOR).first # Note: Typo in original, corrected here if used
                    if agree_checkbox_locator.is_visible(timeout=5000):
                        if not agree_checkbox_locator.is_checked():
                            print("Clicking 'I agree' checkbox on T&C page...")
                            agree_checkbox_locator.check()
                        else:
                            print("'I agree' checkbox was already checked.")
                    else:
                        print("Configured 'I agree' checkbox not visible. Skipping.")
                except PlaywrightTimeoutError:
                    print("Configured 'I agree' checkbox not visible in time. Skipping.")
                except Exception as e_check:
                    print(f"Could not interact with T&C checkbox (selector: '{TERMS_AGREE_CHECKBOX_SELECTOR}'): {e_check}. Proceeding.")
            else:
                print("No 'I agree' checkbox selector defined for T&C page, skipping checkbox step.")

            # Click the "Accept" button on the T&C page using the exact ID you provided
            terms_accept_button_locator = page.locator(TERMS_CONTINUE_BUTTON_SELECTOR) # Uses the updated exact ID
            terms_accept_button_locator.wait_for(state="enabled", timeout=10000)
            print(f"Clicking 'Accept' button on T&C page (selector: '{TERMS_CONTINUE_BUTTON_SELECTOR}')...")
            terms_accept_button_locator.click()
            # === End of T&C Page Handling ===

            # Now, wait for Page 2 (CleanBookingDE.xhtml)
            page.wait_for_url(f"**/{PAGE2_URL_FRAGMENT}**", timeout=30000)
            print(f"Successfully navigated past T&C. On Page 2 (Details Entry). URL: {page.url}")

            # Page 2 Actions
            page.locator(f"id={DL_NUMBER_INPUT_ID}").fill(USER_DL_NUMBER)
            page.locator(f"id={CONTACT_NAME_INPUT_ID}").fill(USER_CONTACT_NAME)
            page.locator(f"id={CONTACT_PHONE_INPUT_ID}").fill(USER_CONTACT_PHONE)
            escaped_test_type_dropdown_id = TEST_TYPE_DROPDOWN_ID.replace(':', '\\:')
            test_type_dropdown_trigger_selector = f"#{escaped_test_type_dropdown_id} .ui-selectonemenu-trigger"
            page.locator(test_type_dropdown_trigger_selector).click()
            page.locator(f"id={TEST_TYPE_OPTION_CAR_ID}").click()
            page.wait_for_timeout(200)
            page.locator(f"id={CONTINUE_BUTTON_PAGE2_ID}").click()

            # Page 3 Actions
            page.wait_for_url(f"**/{PAGE3_URL_FRAGMENT}**", timeout=30000)
            page.locator(f"id={CONTINUE_BUTTON_PAGE3_ID}").click()
            
            # Page 4 Actions (start of loop)
            page.wait_for_url(f"**/{PAGE4_URL_FRAGMENT}**", timeout=30000)
            print("Initial navigation to Location Selection page successful.")

            for i, location in enumerate(LOCATIONS_TO_CHECK):
                current_location_name = location['name']
                current_location_id = location['id']
                print(f"--- Processing location: {current_location_name} ---")
                if not PAGE4_URL_FRAGMENT in page.url:
                     page.wait_for_url(f"**/{PAGE4_URL_FRAGMENT}**", timeout=30000)
                page.locator(f"id={REGION_DROPDOWN_ID}").locator(".ui-selectonemenu-trigger").click()
                page.locator(f"id={current_location_id}").click()
                page.wait_for_timeout(500)
                page.locator(f"id={CONTINUE_BUTTON_PAGE4_ID}").click()
                page.wait_for_url(f"**/{PAGE5_URL_FRAGMENT}**", timeout=45000)
                
                slots_found = check_slots_on_page5(page, current_location_name)
                if slots_found:
                    any_slot_found_overall = True
                    message_parts = [f"*Driving Test Slots Found: {current_location_name}*"]
                    for slot in slots_found:
                        escaped_slot = slot
                        for char_esc in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
                             escaped_slot = escaped_slot.replace(char_esc, '\\' + char_esc)
                        message_parts.append(f"  • _{escaped_slot}_")
                    message_parts.append("\nBook now\\!")
                    send_telegram_notification("\n".join(message_parts))
                
                if i < len(LOCATIONS_TO_CHECK) - 1:
                    print(f"Changing location from {current_location_name}...")
                    page.locator(f"id={CHANGE_LOCATION_BUTTON_PAGE5_ID}").click()
                    page.wait_for_url(f"**/{PAGE4_URL_FRAGMENT}**", timeout=30000)
            
            if not any_slot_found_overall:
                print("No suitable slots found in any of the specified locations during this run.")

        except PlaywrightTimeoutError as pte:
            error_message = f"BOT TIMEOUT ERROR: {pte}."
            if 'page' in locals() and page and page.url: error_message += f" Last URL: {page.url}"
            print(error_message)
            send_telegram_notification(error_message)
        except Exception as e:
            tb_lineno = e.__traceback__.tb_lineno if e.__traceback__ else 'N/A'
            error_message = f"BOT UNEXPECTED ERROR: {type(e).__name__} - {e} (Line: {tb_lineno})."
            if 'page' in locals() and page and page.url: error_message += f" Last URL: {page.url}"
            print(error_message)
            send_telegram_notification(error_message)
        finally:
            if browser:
                browser.close()
    print(f"Bot run finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

if __name__ == "__main__":
    run_bot()
