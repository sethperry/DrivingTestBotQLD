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

# Terms and Conditions Page
TERMS_PAGE_URL_FRAGMENT = "TermsAndConditions.xhtml"
TERMS_AGREE_CHECKBOX_SELECTOR = None # Set to None as no checkbox was identified for T&C
TERMS_CONTINUE_BUTTON_SELECTOR = "id=termsAndConditions:TermsAndConditionsForm:acceptButton" # Exact ID from you

PAGE2_URL_FRAGMENT = "CleanBookingDE.xhtml" # The page after T&C
DL_NUMBER_INPUT_ID = "CleanBookingDEForm:dlNumber"
CONTACT_NAME_INPUT_ID = "CleanBookingDEForm:contactName"
CONTACT_PHONE_INPUT_ID = "CleanBookingDEForm:contactPhone"
TEST_TYPE_DROPDOWN_ID = "CleanBookingDEForm:productType" # Main ID for the dropdown component
TEST_TYPE_OPTION_CAR_ID = "CleanBookingDEForm:productType_1"
CONTINUE_BUTTON_PAGE2_ID = "CleanBookingDEForm:actionFieldList:confirmButtonField:confirmButton"
PAGE3_URL_FRAGMENT = "LicenceDetailsConfirmation.xhtml"
CONTINUE_BUTTON_PAGE3_ID = "BookingConfirmationForm:actionFieldList:confirmButtonField:confirmButton"
PAGE4_URL_FRAGMENT = "LocationSelection.xhtml"
REGION_DROPDOWN_ID = "BookingSearchForm:region" # Main ID for the region dropdown component
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
    
    # MarkdownV2 requires specific characters to be escaped.
    # Characters: _ * [ ] ( ) ~ ` > # + - = | { } . !
    md_reserved = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    escaped_message = message
    for char in md_reserved:
        escaped_message = escaped_message.replace(char, '\\' + char)

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': escaped_message, 'parse_mode': 'MarkdownV2'}
    
    try:
        response = requests.post(api_url, data=payload, timeout=10) # 10-second timeout
        response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
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
        # Wait for the table that contains slots to be visible
        page.locator(f"id={SLOT_TABLE_ID}").wait_for(state="visible", timeout=15000)
    except PlaywrightTimeoutError:
        print(f"Slot table not found for {location_name}.")
        return suitable_slots # Return empty list

    slot_labels = page.locator(SLOT_LABEL_SELECTOR).all()
    if not slot_labels:
        print(f"No slot labels found for {location_name}.")
        return suitable_slots

    current_check_date = datetime.now().date()
    start_date_window = current_check_date
    # Check for slots from today up to 13 days in the future (total 14 days)
    end_date_window = start_date_window + timedelta(days=13) 

    for label_loc in slot_labels:
        slot_text = label_loc.text_content(timeout=5000).strip()
        if not slot_text: continue # Skip empty labels
        try:
            # Example slot_text: "Wednesday, 25 June 2025 1:55 PM"
            slot_datetime_obj = datetime.strptime(slot_text, "%A, %d %B %Y %I:%M %p")
            if start_date_window <= slot_datetime_obj.date() <= end_date_window:
                suitable_slots.append(slot_text)
        except ValueError:
            # Silently ignore if a label's text doesn't match the expected date format
            pass 
    
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
        critical_error_msg = "Driving Test Bot CRITICAL ERROR: Required secrets (Telegram info, User Details) are not fully configured in GitHub Actions."
        print(critical_error_msg)
        # Try to send a Telegram notification about this critical configuration error
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID: # Only if token/chat_id themselves are set
             send_telegram_notification(critical_error_msg)
        return # Stop execution

    try:
        # Attempt to set locale for date parsing (e.g., "Wednesday", "June")
        locale.setlocale(locale.LC_TIME, 'en_AU.UTF-8')
    except locale.Error:
        print("Warning: Australian locale 'en_AU.UTF-8' not available, using system default for date parsing.")

    any_slot_found_overall = False # To track if we should send a "no slots found at all" message
    browser = None # Initialize browser to None for robust finally block
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True) # Headless is essential for GitHub Actions
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36"
            )
            page = context.new_page()

            # --- Page 1: Welcome Page ---
            page.goto(START_URL, timeout=60000) # Allow 60s for initial load
            page.locator(f"id={CONTINUE_BUTTON_PAGE1_ID}").click()

            # === Handle Terms and Conditions Page ===
            print("Looking for Terms and Conditions page...")
            page.wait_for_url(f"**/{TERMS_PAGE_URL_FRAGMENT}**", timeout=30000, wait_until='domcontentloaded') 
            print(f"On Terms and Conditions page (DOM content loaded). URL: {page.url}")

            # Checkbox interaction is skipped as TERMS_AGREE_CHECKBOX_SELECTOR is None
            if TERMS_AGREE_CHECKBOX_SELECTOR:
                try:
                    agree_checkbox_locator = page.locator(TERMS_AGREE_CHECKBOX_SELECTOR).first
                    if agree_checkbox_locator.is_visible(timeout=5000): # Check if visible before interacting
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

            # --- Page 2: Details Entry ---
            page.wait_for_url(f"**/{PAGE2_URL_FRAGMENT}**", timeout=30000) 
            print(f"Successfully navigated past T&C. On Page 2 (Details Entry). URL: {page.url}")

            page.locator(f"id={DL_NUMBER_INPUT_ID}").fill(USER_DL_NUMBER)
            page.locator(f"id={CONTACT_NAME_INPUT_ID}").fill(USER_CONTACT_NAME)
            page.locator(f"id={CONTACT_PHONE_INPUT_ID}").fill(USER_CONTACT_PHONE)
            
            # Corrected selector for Test Type Dropdown (f-string fix)
            escaped_test_type_dropdown_id = TEST_TYPE_DROPDOWN_ID.replace(':', '\\:') 
            test_type_dropdown_trigger_selector = f"#{escaped_test_type_dropdown_id} .ui-selectonemenu-trigger"
            page.locator(test_type_dropdown_trigger_selector).click()
            
            page.locator(f"id={TEST_TYPE_OPTION_CAR_ID}").click()
            page.wait_for_timeout(200) # Brief pause for JS if any
            page.locator(f"id={CONTINUE_BUTTON_PAGE2_ID}").click()

            # --- Page 3: Confirmation ---
            page.wait_for_url(f"**/{PAGE3_URL_FRAGMENT}**", timeout=30000)
            page.locator(f"id={CONTINUE_BUTTON_PAGE3_ID}").click()
            
            # --- Page 4: Location Selection (Start of Loop) ---
            page.wait_for_url(f"**/{PAGE4_URL_FRAGMENT}**", timeout=30000)
            print("Initial navigation to Location Selection page successful.")

            for i, location in enumerate(LOCATIONS_TO_CHECK):
                current_location_name = location['name']
                current_location_id = location['id']
                print(f"--- Processing location: {current_location_name} ---")

                # Ensure we are on the Location Selection page (Page 4)
                if not PAGE4_URL_FRAGMENT in page.url:
                     print(f"Not on location selection page, attempting to wait for it. Current URL: {page.url}")
                     page.wait_for_url(f"**/{PAGE4_URL_FRAGMENT}**", timeout=30000)

                # Select region
                page.locator(f"id={REGION_DROPDOWN_ID}").locator(".ui-selectonemenu-trigger").click()
                page.locator(f"id={current_location_id}").click() # Click the specific region option
                page.wait_for_timeout(500) # Allow selection to register
                page.locator(f"id={CONTINUE_BUTTON_PAGE4_ID}").click()
                
                # Wait for Page 5 (Slot Selection)
                page.wait_for_url(f"**/{PAGE5_URL_FRAGMENT}**", timeout=45000) # Allow more time for slots page to load
                
                slots_found_this_location = check_slots_on_page5(page, current_location_name)
                
                if slots_found_this_location:
                    any_slot_found_overall = True
                    # Construct message for Telegram - Markdown applied here, send_telegram_notification will escape it.
                    message_parts = [f"*{current_location_name}* - Slots Found:"] # Location name bold
                    for slot in slots_found_this_location:
                        message_parts.append(f"  • _{slot}_") # Slot details italicized
                    message_parts.append("\nBook now!") # No need to manually escape '!' here
                    notification_message = "\n".join(message_parts)
                    send_telegram_notification(notification_message)
                
                # If not the last location, click "Change location selection" to go back to Page 4
                if i < len(LOCATIONS_TO_CHECK) - 1:
                    print(f"Changing location from {current_location_name}...")
                    page.locator(f"id={CHANGE_LOCATION_BUTTON_PAGE5_ID}").click()
                    page.wait_for_url(f"**/{PAGE4_URL_FRAGMENT}**", timeout=30000) # Wait to return to location page
            
            if not any_slot_found_overall:
                print("No suitable slots found in any of the specified locations during this run.")
                # Optionally, send a "no slots found overall" message if you want one daily, for example.
                # send_telegram_notification("Driving Test Bot: No new slots found in any locations during this check.")

        except PlaywrightTimeoutError as pte:
            error_message = f"BOT TIMEOUT ERROR: {pte}."
            if 'page' in locals() and page and page.url: error_message += f" Last URL: {page.url}"
            print(error_message)
            send_telegram_notification(error_message)
        except Exception as e:
            # Get line number for better debugging
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
