import time
from datetime import datetime, timedelta, date
import locale
import os  # For reading environment variables (GitHub Secrets)
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
PAGE2_URL_FRAGMENT = "CleanBookingDE.xhtml"
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

# --- Telegram Notification Function ---
def send_telegram_notification(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Telegram Bot Token or Chat ID is not configured as a GitHub Secret.")
        return False
    
    # Basic MarkdownV2 escaping for Telegram
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

# --- Slot Checking Function ---
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
    end_date_window = start_date_window + timedelta(days=13) # 14-day window

    for label_loc in slot_labels:
        slot_text = label_loc.text_content(timeout=5000).strip()
        if not slot_text: continue
        try:
            slot_datetime_obj = datetime.strptime(slot_text, "%A, %d %B %Y %I:%M %p")
            if start_date_window <= slot_datetime_obj.date() <= end_date_window:
                suitable_slots.append(slot_text)
        except ValueError:
            pass # Ignore parsing errors for simplicity
    
    if suitable_slots:
        print(f"Found {len(suitable_slots)} suitable slots for {location_name}.")
    else:
        print(f"No suitable slots in the next 14 days for {location_name}.")
    return suitable_slots

# --- Main Bot Logic ---
def run_bot():
    print(f"Bot run started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check if critical secrets are loaded
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, USER_DL_NUMBER, USER_CONTACT_NAME, USER_CONTACT_PHONE]):
        print("CRITICAL ERROR: One or more required secrets (Telegram info, User Details) are missing. Set them in GitHub repository secrets.")
        send_telegram_notification("Driving Test Bot CRITICAL ERROR: Required secrets are not configured in GitHub Actions.")
        return

    try:
        locale.setlocale(locale.LC_TIME, 'en_AU.UTF-8') # For date parsing
    except locale.Error:
        print("Warning: Australian locale not available, using default.")

    any_slot_found_overall = False
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch(headless=True) # Headless is essential for GitHub Actions
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36")
            page = context.new_page()

            # Navigate through initial pages
            page.goto(START_URL, timeout=60000)
            page.locator(f"id={CONTINUE_BUTTON_PAGE1_ID}").click()
            page.wait_for_url(f"**/{PAGE2_URL_FRAGMENT}**", timeout=30000)
            page.locator(f"id={DL_NUMBER_INPUT_ID}").fill(USER_DL_NUMBER)
            page.locator(f"id={CONTACT_NAME_INPUT_ID}").fill(USER_CONTACT_NAME)
            page.locator(f"id={CONTACT_PHONE_INPUT_ID}").fill(USER_CONTACT_PHONE)
            page.locator(f"#{TEST_TYPE_DROPDOWN_ID.replace(':', '\\\\:')} .ui-selectonemenu-trigger").click()
            page.locator(f"id={TEST_TYPE_OPTION_CAR_ID}").click()
            page.wait_for_timeout(200)
            page.locator(f"id={CONTINUE_BUTTON_PAGE2_ID}").click()
            page.wait_for_url(f"**/{PAGE3_URL_FRAGMENT}**", timeout=30000)
            page.locator(f"id={CONTINUE_BUTTON_PAGE3_ID}").click()
            page.wait_for_url(f"**/{PAGE4_URL_FRAGMENT}**", timeout=30000)
            print("Initial navigation successful.")

            for i, location in enumerate(LOCATIONS_TO_CHECK):
                print(f"Processing location: {location['name']}")
                if not PAGE4_URL_FRAGMENT in page.url:
                     page.wait_for_url(f"**/{PAGE4_URL_FRAGMENT}**", timeout=30000) # Ensure on location page

                page.locator(f"id={REGION_DROPDOWN_ID}").locator(".ui-selectonemenu-trigger").click()
                page.locator(f"id={location['id']}").click()
                page.wait_for_timeout(500)
                page.locator(f"id={CONTINUE_BUTTON_PAGE4_ID}").click()
                page.wait_for_url(f"**/{PAGE5_URL_FRAGMENT}**", timeout=45000)
                
                slots = check_slots_on_page5(page, location['name'])
                if slots:
                    any_slot_found_overall = True
                    message = f"*Driving Test Slots Found: {location['name']}*\n"
                    for slot in slots:
                        escaped_slot = slot # Basic escape done in send_telegram_notification
                        for char_esc in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
                             escaped_slot = escaped_slot.replace(char_esc, '\\' + char_esc)
                        message += f"  • _{escaped_slot}_\n" # Italicize slots
                    message += "\nBook now\\!"
                    send_telegram_notification(message)
                
                if i < len(LOCATIONS_TO_CHECK) - 1: # If not the last location
                    page.locator(f"id={CHANGE_LOCATION_BUTTON_PAGE5_ID}").click()
                    page.wait_for_url(f"**/{PAGE4_URL_FRAGMENT}**", timeout=30000)
            
            if not any_slot_found_overall:
                print("No suitable slots found in any locations during this run.")
                # Optionally send a "no slots" summary, or stay silent
                # send_telegram_notification("Driving Test Bot: No new slots found in any locations this check.")


        except Exception as e:
            error_message = f"BOT ERROR: {type(e).__name__} - {e}."
            if 'page' in locals() and page:
                error_message += f" Last URL: {page.url}"
                # Screenshot is not easily accessible in default GH Actions, so skip for simplicity
            print(error_message)
            send_telegram_notification(error_message) # Notify error
        finally:
            if browser:
                browser.close()
    print(f"Bot run finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

if __name__ == "__main__":
    run_bot()
