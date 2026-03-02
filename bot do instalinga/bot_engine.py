import random
import time
import threading
import os
from playwright.sync_api import sync_playwright

class InstalingBot:
    def __init__(self, log_queue, browser_type="Google Chrome", login=None, password=None):
        self.log_queue = log_queue
        self.browser_type = browser_type
        self.login = login
        self.password = password
        self.running = False
        self.last_answer = None

    def log(self, message):
        self.log_queue.put(message)

    def stop(self):
        self.running = False

    def handle_overlays(self, page):
        """Handle consent screens and other blocking overlays."""
        try:
            consent_dismissed = False
            # 1. Google Funding Choices (RODO/Cookies)
            try:
                # Use evaluate to find and click to avoid Playwright actionability hangs
                consent_clicked = page.evaluate("""() => {
                    // Try different common selectors for consent buttons
                    const selectors = ['.fc-cta-consent', '.fc-button', 'button'];
                    for (const selector of selectors) {
                        const btns = Array.from(document.querySelectorAll(selector));
                        const acceptBtn = btns.find(btn => {
                            const txt = btn.innerText.toLowerCase();
                            return txt.includes('zgadzam') || txt.includes('akcept') || txt.includes('przejd');
                        });
                        if (acceptBtn) {
                            acceptBtn.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                if consent_clicked:
                    self.log("Consent overlay dismissed via JS evaluation.")
                    time.sleep(1)
                    consent_dismissed = True
            except Exception as e:
                self.log(f"Error checking consent (Global): {e}")

            if not consent_dismissed:
                # Fallback to the iframe method
                try:
                    consent_iframe = page.query_selector("iframe.fc-consent-root")
                    if consent_iframe:
                        frame = consent_iframe.content_frame()
                        if frame:
                            iframe_clicked = frame.evaluate("""() => {
                                const btn = document.querySelector('.fc-cta-consent');
                                if (btn) {
                                    btn.click();
                                    return true;
                                }
                                return false;
                            }""")
                            if iframe_clicked:
                                self.log("Consent overlay dismissed (Iframe)...")
                                time.sleep(1)
                                consent_dismissed = True
                except Exception as e:
                    self.log(f"Error checking consent (Iframe): {e}")
            
            # 2. "Ważne informacje!" / "Sesja przerwana" (Session Start/Continue)
            selectors = [
                "div#start_session_button .btn-start-session", 
                "div#continue_session_button .btn-start-session",
                ".btn-start-session"
            ]
            for selector in selectors:
                try:
                    clicked = page.evaluate(f"""() => {{
                        const btn = document.querySelector('{selector}');
                        if (btn && btn.offsetParent !== null) {{
                            btn.click();
                            return true;
                        }}
                        return false;
                    }}""")
                    if clicked:
                        self.log(f"Session button clicked ({selector})")
                        time.sleep(2)
                        return
                except Exception as e:
                    pass
        except Exception as e:
            self.log(f"Critical error in handle_overlays: {e}")

    def run(self):
        self.running = True
        with sync_playwright() as p:
            # Browser selection logic
            launch_kwargs = {
                "headless": False,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--window-position=0,0"
                ]
            }
            
            if self.browser_type == "Google Chrome":
                launch_kwargs["channel"] = "chrome"
                self.log("Launching Google Chrome...")
            elif self.browser_type == "DuckDuckGo":
                self.log("Launching DuckDuckGo engine (Chromium)...")
            
            try:
                browser = p.chromium.launch(**launch_kwargs)
            except Exception as e:
                self.log(f"Failed to launch using channel/path: {e}")
                self.log("Attempting fallback launch...")
                browser = p.chromium.launch(headless=False)

            context = browser.new_context()
            page = context.new_page()

            # Network interception
            def handle_response(response):
                if "generate_next_word.php" in response.url:
                    try:
                        text = response.text()
                        import json
                        data = json.loads(text)
                        self.last_answer = data.get("4") or data.get("1")
                        self.log(f"Answer Intercepted: {self.last_answer}")
                    except Exception as e:
                        pass

            page.on("response", handle_response)
            
            # Ensure we are on the login page
            current_url = page.url
            if "instaling.pl/login" not in current_url and "page=login" not in current_url:
                self.log("Not on login page. Navigating to Instaling login page...")
                page.goto("https://instaling.pl/login", timeout=30000)
                page.wait_for_load_state("networkidle")
            
            # Wait a moment for any popups to initialize
            time.sleep(2)

            # Automatic Login (only if on login page)
            if "/login" in page.url or "page=login" in page.url:
                try:
                    self.log("Detected login page. Checking for overlays...")
                    self.handle_overlays(page)
                    
                    # User requested 5 second wait after RODO
                    self.log("Waiting 5 seconds before entering credentials...")
                    time.sleep(5)
                    
                    self.log("Checking if login fields are visible...")
                    try:
                        page.wait_for_selector("#log_email", timeout=15000)
                        self.log("Login fields found! Starting to type...")
                    except Exception as e:
                        self.log(f"Login field #log_email not found: {e}. Retrying overlay check...")
                        self.handle_overlays(page)
                        page.wait_for_selector("#log_email", timeout=10000)
                    
                    # Using type with delay instead of fill for more reliability
                    try:
                        email_input = page.locator("#log_email")
                        email_input.click()
                        email_input.press("Control+A")
                        email_input.press("Backspace")
                        page.type("#log_email", self.login, delay=100)
                        self.log("Email typed.")
                        
                        pass_input = page.locator("#log_password")
                        pass_input.click()
                        pass_input.press("Control+A")
                        pass_input.press("Backspace")
                        page.type("#log_password", self.password, delay=100)
                        self.log("Password typed.")
                    except Exception as e:
                        self.log(f"Standard typing failed ({e}), trying JS fallback...")
                        page.evaluate("""(creds) => {
                            document.querySelector('#log_email').value = creds.login;
                            document.querySelector('#log_password').value = creds.password;
                        }""", {"login": self.login, "password": self.password})
                        self.log("Credentials set via JS fallback.")
                    
                    time.sleep(1)
                    page.click("button.btn-primary.w-100")
                    self.log("Login button clicked.")
                    page.wait_for_load_state("networkidle")
                except Exception as e:
                    self.log(f"Auto-login error details: {e}")
                    # Take a diagnostic screenshot if it fails
                    try:
                        page.screenshot(path="login_error_diagnostic.png")
                        self.log("Saved login_error_diagnostic.png")
                    except:
                        pass

            
            while self.running:
                try:
                    self.handle_overlays(page)

                    # Check for end of session "Return" button
                    try:
                        return_clicked = page.evaluate("""() => {
                            const btns = Array.from(document.querySelectorAll('a, button, .btn'));
                            const returnBtn = btns.find(b => {
                                const txt = b.innerText.toLowerCase();
                                return txt.includes('powrót') || txt.includes('stronę główną') || txt.includes('powrot');
                            });
                            if (returnBtn && returnBtn.offsetParent !== null) {
                                returnBtn.click();
                                return true;
                            }
                            return false;
                        }""")
                        if return_clicked:
                            self.log("Session finished! Clicking return to start a new loop...")
                            time.sleep(3)
                            continue
                    except Exception:
                        pass

                    if "/app/session/app.php" in page.url:
                        # Check for "Znam" / "Nie znam" new word screen
                        try:
                            znam_btn = page.query_selector("div#know_new")
                            if znam_btn and znam_btn.is_visible():
                                self.log("New word detected! Clicked 'Znam'.")
                                time.sleep(1)
                                znam_btn.click()
                                time.sleep(1)
                                continue
                        except Exception:
                            pass
                        
                        # Check for Premium Upsell "Pomiń" button
                        try:
                            pomin_clicked = page.evaluate("""() => {
                                const btns = Array.from(document.querySelectorAll('div, button, a'));
                                const pominBtn = btns.find(b => {
                                    const txt = b.innerText.trim();
                                    return txt === 'Pomiń';
                                });
                                if (pominBtn && pominBtn.offsetParent !== null) {
                                    pominBtn.click();
                                    return true;
                                }
                                return false;
                            }""")
                            if pomin_clicked:
                                self.log("Premium notification detected! Clicked 'Pomiń'.")
                                time.sleep(1)
                                continue
                        except Exception:
                            pass
                        
                        next_btn = page.query_selector("#nextword")
                        if next_btn and next_btn.is_visible():
                            time.sleep(random.uniform(1, 2))
                            next_btn.click()
                            continue

                        answer_input = page.query_selector("#answer")
                        if answer_input and self.last_answer and answer_input.is_visible() and not answer_input.is_disabled():
                            think_time = random.uniform(2.0, 4.0)
                            self.log(f"Thinking for {think_time:.1f}s...")
                            time.sleep(think_time)
                            
                            # Intentional mistake logic (approx 10% chance)
                            display_word = self.last_answer
                            if random.random() < 0.10:
                                self.log("Simulating a slight mistake for stealth...")
                                if len(display_word) > 3:
                                    # Swap two adjacent characters or skip one
                                    idx = random.randint(0, len(display_word) - 2)
                                    word_list = list(display_word)
                                    word_list[idx], word_list[idx+1] = word_list[idx+1], word_list[idx]
                                    display_word = "".join(word_list)
                                else:
                                    # Just add a random char at the end
                                    display_word += random.choice("asdfghjkl")

                            self.log(f"Typing: {display_word}")
                            for char in display_word:
                                page.keyboard.type(char)
                                time.sleep(random.uniform(0.1, 0.25))
                            
                            time.sleep(random.uniform(0.8, 1.5))
                            page.click("#check")
                            self.last_answer = None
                    
                    time.sleep(1)
                except Exception as e:
                    time.sleep(2)
            
            browser.close()
            self.log("Browser closed.")
