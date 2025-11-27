import requests
import time
import uuid
import json
import urllib.parse
import os

class TgtgClient:
    BASE_URL = "https://api.toogoodtogo.com/api/"
    DATADOME_URL = "https://api-sdk.datadome.co/sdk/"
    APP_VERSION = "25.9.0"
    USER_AGENT = f"TGTG/{APP_VERSION} Dalvik/2.1.0 (Linux; U; Android 14; Pixel 7 Pro Build/UQ1A.240105.004)"
    TOKENS_FILE = "tgtg_tokens.json"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Language": "en-US",
            "Accept-Encoding": "gzip",
            "User-Agent": self.USER_AGENT
        })
        self.access_token = None
        self.refresh_token = None
        self.user_id = None
        self.datadome_cookie = None

    def save_tokens(self):
        data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "user_id": self.user_id,
            "datadome_cookie": self.datadome_cookie
        }
        try:
            with open(self.TOKENS_FILE, "w") as f:
                json.dump(data, f)
            print("Tokens saved locally.")
        except Exception as e:
            print(f"Error saving tokens: {e}")

    def load_tokens(self):
        if not os.path.exists(self.TOKENS_FILE):
            return False
            
        try:
            with open(self.TOKENS_FILE, "r") as f:
                data = json.load(f)
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                self.user_id = data.get("user_id")
                self.datadome_cookie = data.get("datadome_cookie")
                
                if self.datadome_cookie:
                    self.session.cookies.set("datadome", self.datadome_cookie, domain=".toogoodtogo.com")
                
                return True
        except Exception as e:
            print(f"Error loading tokens: {e}")
            return False

    def _get_headers(self, auth=False):
        headers = {
            "x-correlation-id": str(uuid.uuid4())
        }
        if auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.datadome_cookie:
            headers["Cookie"] = f"datadome={self.datadome_cookie}"
        return headers

    def _get_datadome_cookie(self, original_url):
        print("Fetching DataDome cookie...")
        try:
            time.sleep(1)
            cid = str(uuid.uuid4()).replace("-", "")
            request_url_encoded = urllib.parse.quote(original_url)
            timestamp = int(time.time() * 1000)
            events = [{"id": 1, "message": "response validation", "source": "sdk", "date": timestamp}]
            
            data = {
                "cid": cid,
                "ddk": "1D42C2CA6131C526E09F294FE96F94",
                "request": request_url_encoded,
                "ua": self.USER_AGENT,
                "events": json.dumps(events),
                "inte": "android-java-okhttp",
                "ddv": "3.0.4",
                "ddvc": self.APP_VERSION,
                "os": "Android",
                "osr": "14",
                "osn": "UPSIDE_DOWN_CAKE",
                "osv": "34",
                "screen_x": "1440",
                "screen_y": "3120",
                "screen_d": "3.5",
                "camera": '{"auth":"true", "info":"{\\"front\\":\\"2000x1500\\",\\"back\\":\\"5472x3648\\"}"}',
                "mdl": "Pixel 7 Pro",
                "prd": "Pixel 7 Pro",
                "mnf": "Google",
                "dev": "cheetah",
                "hrd": "GS201",
                "fgp": "google/cheetah/cheetah:14/UQ1A.240105.004/10814564:user/release-keys",
                "tgs": "release-keys",
                "d_ifv": str(uuid.uuid4()).replace("-", "")
            }
            
            headers = {
                "User-Agent": "okhttp/5.1.0"
            }
            
            response = requests.post(self.DATADOME_URL, data=data, headers=headers)
            response.raise_for_status()
            resp_json = response.json()
            cookie_full = resp_json.get("cookie")
            
            if cookie_full:
                # cookie_full looks like "datadome=xyz; Max-Age=..."
                cookie_part = cookie_full.split(";")[0]
                key, value = cookie_part.split("=", 1)
                self.datadome_cookie = value
                
                # Set in session
                self.session.cookies.set(key, value, domain=".toogoodtogo.com")
                print("DataDome cookie acquired.")
                self.save_tokens() # Save cookie if we get a new one
                return True
            else:
                print("No cookie in DataDome response.")
                return False
                
        except Exception as e:
            print(f"Failed to fetch DataDome cookie: {e}")
            return False

    def _request(self, method, url, **kwargs):
        # Wrapper to handle 403 DataDome
        # Save original kwargs for retry
        original_kwargs = kwargs.copy()
        
        # Add delay to slow down requests
        time.sleep(3)
        
        headers = kwargs.pop("headers", {})
        auth_required = kwargs.pop("auth_required", False)
        
        headers.update(self._get_headers(auth=auth_required))
        
        print(f"DEBUG: Requesting {method} {url}")
        
        try:
            response = self.session.request(method, url, headers=headers, **kwargs)
            
            if response.status_code == 403:
                print(f"Received 403 Forbidden on {url}")
                print(f"Body preview: {response.text[:200]}...") 
                print("Attempting DataDome bypass...")
                
                # Wait before hitting DataDome API
                time.sleep(2)
                
                if self._get_datadome_cookie(url):
                    # Retry
                    print("Retrying request with new cookie...")
                    time.sleep(4) # Wait 4 seconds before retry
                    
                    # Reconstruct headers
                    headers = original_kwargs.get("headers", {})
                    auth_required = original_kwargs.get("auth_required", False)
                    headers.update(self._get_headers(auth=auth_required))
                    
                    response = self.session.request(method, url, headers=headers, **kwargs)
                    
                    if response.status_code == 403:
                        print("Retry failed with 403.")
                        print(f"Retry Body: {response.text[:500]}")
                        print("Stopping execution to prevent further blocking.")
                        raise requests.exceptions.HTTPError("403 Forbidden - Blocked by DataDome", response=response)
            
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            # If it's still 403 or other error
            print(f"Request failed: {e}")
            raise e

    def login_by_email(self, email):
        url = f"{self.BASE_URL}auth/v5/authByEmail"
        payload = {
            "device_type": "ANDROID",
            "email": email
        }
        response = self._request("POST", url, json=payload)
        return response.json()

    def poll_auth(self, polling_id, email):
        url = f"{self.BASE_URL}auth/v5/authByRequestPollingId"
        payload = {
            "device_type": "ANDROID",
            "email": email,
            "request_polling_id": polling_id
        }
        
        # Polling loop
        for _ in range(24): # Try for 2 minutes (5s * 24)
            try:
                response = self._request("POST", url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("access_token"):
                        self.access_token = data["access_token"]
                        self.refresh_token = data["refresh_token"]
                        self.user_id = data["startup_data"]["user"]["user_id"]
                        self.save_tokens() # Save after successful login
                        return data
                elif response.status_code == 202:
                    # Still waiting for confirmation
                    pass
                else:
                    print(f"Polling status: {response.status_code}")
            except Exception as e:
                # If it's a 403 that wasn't fixed, or other error
                print(f"Polling error: {e}")
                if "403" in str(e):
                    print("Stopping polling due to 403.")
                    return None
            
            time.sleep(5)
        
        return None

    def refresh_session(self):
        if not self.refresh_token:
            return False
            
        url = f"{self.BASE_URL}token/v1/refresh"
        payload = {
            "refresh_token": self.refresh_token
        }
        
        try:
            response = self._request("POST", url, json=payload)
            data = response.json()
            self.access_token = data["access_token"]
            if "refresh_token" in data:
                self.refresh_token = data["refresh_token"]
            
            self.save_tokens() # Save refreshed tokens
            return True
        except Exception as e:
            print(f"Refresh token error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Refresh error body: {e.response.text}")
            return False

    def get_items(self, lat, long, radius=10, favorites_only=False):
        url = f"{self.BASE_URL}item/v8/"
        payload = {
            "favorites_only": favorites_only,
            "origin": {
                "latitude": lat,
                "longitude": long
            },
            "radius": radius
        }
        
        response = self._request("POST", url, json=payload, auth_required=True)
        return response.json()

    def confirm_by_email_link(self, link):
        # Extract user_id and token from link
        # Link format: https://space.toogoodtogo.com/login/accept/{user_id}/{token}
        try:
            # Handle both full URL and just the path if user pastes weirdly
            if "/login/accept/" not in link:
                print("Invalid link format. Expected .../login/accept/USER_ID/TOKEN")
                return False
                
            parts = link.split("/login/accept/")
            if len(parts) < 2:
                return False
            
            path_parts = parts[1].split("/")
            if len(path_parts) < 2:
                return False
                
            user_id = path_parts[0]
            token = path_parts[1].split("?")[0] # Remove query params if any
            
            # Try multiple endpoints as the correct one is uncertain
            endpoints = [
                "https://api.toogoodtogo.com/web/auth/v3/authByRequestToken",
                "https://space.toogoodtogo.com/api/web/auth/v3/authByRequestToken",
                "https://space.toogoodtogo.com/web/auth/v3/authByRequestToken"
            ]
            
            payload = {
                "userId": user_id,
                "requestToken": token
            }
            
            # Parse domain from link for Origin
            parsed_link = urllib.parse.urlparse(link)
            origin = f"{parsed_link.scheme}://{parsed_link.netloc}" if parsed_link.netloc else "https://space.toogoodtogo.com"

            # 1. Visit the link first to get cookies/CSRF token
            print(f"Visiting {link} to establish session...")
            try:
                # Use a browser User-Agent for the initial GET to behave like a browser
                browser_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                self.session.headers.update({"User-Agent": browser_ua})
                self.session.get(link)
                # Restore app UA
                self.session.headers.update({"User-Agent": self.USER_AGENT})
            except Exception as e:
                print(f"Error visiting link: {e}")

            # 2. Extract CSRF token if present
            csrf_token = self.session.cookies.get("XSRF-TOKEN") or self.session.cookies.get("csrf_token")
            print(f"CSRF Token found: {csrf_token is not None}")

            # Use the App User-Agent for this call
            headers = {
                "User-Agent": self.USER_AGENT,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": origin,
                "Referer": link
            }

            if csrf_token:
                headers["X-XSRF-TOKEN"] = csrf_token
                headers["X-CSRF-Token"] = csrf_token
            
            print(f"Confirming with User ID: {user_id}...")
            
            for url in endpoints:
                print(f"Trying confirmation URL: {url}")
                try:
                    # Use self.session to include cookies (DataDome)
                    response = self.session.post(url, json=payload, headers=headers)
                    
                    if response.status_code != 200:
                        print(f"Response Headers: {dict(response.headers)}")
                        print(f"Response Body: {response.text}")

                    if response.status_code == 200:
                        print("Confirmation successful!")
                        return True
                    else:
                        print(f"Failed with status {response.status_code} on {url}")
                except Exception as e:
                    print(f"Error hitting {url}: {e}")
            
            print("All confirmation attempts failed.")
            return False
        except Exception as e:
            print(f"Confirmation error: {e}")
            return False


def main():
    client = TgtgClient()
    
    print("--- TooGoodToGo Magic Bag Finder ---")
    
    # Try to load tokens first
    if client.load_tokens():
        print("Loaded saved tokens.")
        if client.refresh_session():
            print("Session refreshed successfully.")
            print(f"User ID: {client.user_id}")
            # Skip login flow
            do_login = False
        else:
            print("Session refresh failed. Login required.")
            do_login = True
    else:
        do_login = True
    
    if do_login:
        email = input("Enter your email address: ")
        
        print(f"Requesting login for {email}...")
        try:
            auth_response = client.login_by_email(email)
            polling_id = auth_response["polling_id"]
            print(f"Please check your email ({email}) and click the login link.")
            
            print("\nNOTE: If clicking the link in the email fails (e.g. 'Something went wrong'),")
            print("please copy the link address and paste it here.")
            print("Otherwise, just press Enter after you have clicked the link on your phone.")
            
            user_input = input("Link or Enter: ").strip()
            
            if user_input and "http" in user_input:
                client.confirm_by_email_link(user_input)
                print("Waiting for token generation...")
            else:
                print("Waiting for confirmation...")
            
            login_data = client.poll_auth(polling_id, email)
            
            if login_data:
                print("Login successful!")
                print(f"User ID: {client.user_id}")
            else:
                print("Login timed out or failed.")
                return # Exit if login failed
                
        except Exception as e:
            print(f"An error occurred during login: {e}")
            return

    # Proceed to get items
    try:
        # Default location (e.g., London) if user just presses enter
        lat_input = input("Enter latitude (default 51.5074): ") or "51.5074"
        long_input = input("Enter longitude (default -0.1278): ") or "-0.1278"
        radius_input = input("Enter radius in km (default 5): ") or "5"
        
        lat = float(lat_input)
        long = float(long_input)
        radius = int(radius_input)
        
        print(f"Searching for bags within {radius}km of {lat}, {long}...")
        items_response = client.get_items(lat, long, radius)
        
        items = items_response.get("items", [])
        print(f"\nFound {len(items)} items:")
        
        for item_wrapper in items:
            item = item_wrapper.get("item", {})
            store = item_wrapper.get("store", {})
            items_available = item_wrapper.get("items_available", 0)
            
            if items_available > 0:
                print(f"- [{items_available} available] {item.get('name')} at {store.get('store_name')}")
                price = item.get('item_price', {})
                print(f"  Price: {price.get('minor_units', 0) / (10 ** price.get('decimals', 2))} {price.get('code')}")
                
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
