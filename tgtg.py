import requests
import time
import uuid
import json
import urllib.parse

class TgtgClient:
    BASE_URL = "https://api.toogoodtogo.com/api/"
    DATADOME_URL = "https://api-sdk.datadome.co/sdk/"
    APP_VERSION = "24.11.0"
    USER_AGENT = f"TGTG/{APP_VERSION} Dalvik/2.1.0 (Linux; U; Android 14; Pixel 7 Pro Build/UQ1A.240105.004)"
    
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

    def _get_headers(self, auth=False):
        headers = {
            "x-correlation-id": str(uuid.uuid4())
        }
        if auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.datadome_cookie:
            # Add datadome cookie to headers if using requests Session cookie jar isn't enough
            # But requests Session handles cookies automatically if we set them.
            # We'll set it in the session cookies.
            pass
        return headers

    def _get_datadome_cookie(self, original_url):
        print("Fetching DataDome cookie...")
        try:
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
                return True
            else:
                print("No cookie in DataDome response.")
                return False
                
        except Exception as e:
            print(f"Failed to fetch DataDome cookie: {e}")
            return False

    def _request(self, method, url, **kwargs):
        # Wrapper to handle 403 DataDome
        headers = kwargs.pop("headers", {})
        headers.update(self._get_headers(auth=kwargs.pop("auth_required", False)))
        
        try:
            response = self.session.request(method, url, headers=headers, **kwargs)
            
            if response.status_code == 403:
                print("Received 403 Forbidden. Attempting DataDome bypass...")
                if self._get_datadome_cookie(url):
                    # Retry
                    # Update headers with new cookie if needed (session handles it usually)
                    # But let's make sure we don't reuse the old headers object if it had stale info?
                    # Actually headers are fresh from _get_headers if we called it again, but we passed it in.
                    # We should regenerate headers just in case.
                    headers = kwargs.get("headers", {}) # Original kwargs headers
                    headers.update(self._get_headers(auth=kwargs.get("auth_required", False))) # Re-add auth/correlation
                    
                    response = self.session.request(method, url, headers=headers, **kwargs)
            
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            # If it's still 403 or other error
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
                        return data
                elif response.status_code == 202:
                    # Still waiting for confirmation
                    pass
                else:
                    print(f"Polling status: {response.status_code}")
            except Exception as e:
                # If it's a 403 that wasn't fixed, or other error
                print(f"Polling error: {e}")
            
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
            return True
        except Exception as e:
            print(f"Refresh token error: {e}")
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


def main():
    client = TgtgClient()
    
    print("--- TooGoodToGo Magic Bag Finder ---")
    email = input("Enter your email address: ")
    
    print(f"Requesting login for {email}...")
    try:
        auth_response = client.login_by_email(email)
        polling_id = auth_response["polling_id"]
        print(f"Please check your email ({email}) and click the login link.")
        print("Waiting for confirmation...")
        
        login_data = client.poll_auth(polling_id, email)
        
        if login_data:
            print("Login successful!")
            print(f"User ID: {client.user_id}")
            
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
                    
        else:
            print("Login timed out or failed.")
            
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
