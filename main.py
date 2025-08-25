from flask import Flask
import requests
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

EMAIL = "malykarel74@gmail.com"
PASSWORD = "Poklop74"
SN = "SB825040"

HIGH_LEVEL = 160
ON_DURATION = timedelta(minutes=3)
OFF_DURATION = timedelta(minutes=25)
STATE_FILE = "stav.json"
TOKEN_FILE = "token.json"

# --- HTTP helper funkce ---
def httpPost(url, header={}, params={}, data={}):
    headers = {"Content-Type": "application/json", "Accept": "application/json", **header}
    data = json.dumps(data)
    r = requests.post(url, data=data, headers=headers, params=params)
    r.raise_for_status()
    return r.json()

def httpGet(url, header={}, params={}):
    headers = {"Content-Type": "application/json", "Accept": "application/json", **header}
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    return r.json()

# --- Třída ThingsBoard ---
class ThingsBoard:
    def __init__(self):
        self.server = 'https://cml.seapraha.cz'
        self.userToken = None
        self.customerId = None

    def load_token(self):
        if not os.path.exists(TOKEN_FILE):
            return None
        try:
            with open(TOKEN_FILE, "r") as f:
                token_data = json.load(f)
                expires_at = datetime.fromisoformat(token_data["expiresAt"])
                if datetime.now(ZoneInfo("Europe/Prague")) < expires_at:
                    return token_data["token"]
        except:
            return None
        return None

    def save_token(self, token):
        expires_at = datetime.now(ZoneInfo("Europe/Prague")) + timedelta(hours=24)
        with open(TOKEN_FILE, "w") as f:
            json.dump({"token": token, "expiresAt": expires_at.isoformat()}, f)

    def login(self, username, password):
        token = self.load_token()
        if token:
            self.userToken = token
        else:
            url = f'{self.server}/api/auth/login'
            response = httpPost(url, {}, data={'username': username, 'password': password})
            self.userToken = response["token"]
            self.save_token(self.userToken)

        url = f'{self.server}/api/auth/user'
        response = httpGet(url, {'X-Authorization': f"Bearer {self.userToken}"})
        self.customerId = response["customerId"]["id"]

    def getDevicesByName(self, name):
        url = f'{self.server}/api/customer/{self.customerId}/devices'
        params = {'pageSize': 100, 'page': 0, "textSearch": name}
        response = httpGet(url, {'X-Authorization': f"Bearer {self.userToken}"}, params=params)
        if response["totalElements"] < 1:
            raise Exception(f"Device SN {name} not found!")
        return response["data"]

    def getDeviceValues(self, deviceId, keys):
        url = f'{self.server}/api/plugins/telemetry/DEVICE/{deviceId}/values/timeseries'
        params = {'keys': keys}
        return httpGet(url, {'X-Authorization': f"Bearer {self.userToken}"}, params=params)

    def setDeviceOutput(self, deviceId, output, value):
        method = "setDout1" if output == "OUT1" else "setDout2"
        data = {"method": method, "params": value}
        url = f'{self.server}/api/rpc/twoway/{deviceId}'
        return httpPost(url, {'X-Authorization': f"Bearer {self.userToken}"}, {}, data)

def eStudna_GetWaterLevel(username, password, serialNumber):
    tb = ThingsBoard()
    tb.login(username, password)
    devices = tb.getDevicesByName(f"%{serialNumber}")
    values = tb.getDeviceValues(devices[0]["id"]["id"], "ain1")
    return float(values["ain1"][0]["value"]) * 100

def eStudna_SetOutput(username, password, serialNumber, state):
    tb = ThingsBoard()
    tb.login(username, password)
    devices = tb.getDevicesByName(f"%{serialNumber}")
    device_id = devices[0]["id"]["id"]
    tb.setDeviceOutput(device_id, "OUT1", state)
    tb.setDeviceOutput(device_id, "OUT2", state)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"phase": "off", "until": None}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def is_allowed_time(now: datetime) -> bool:
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute
    time = hour * 60 + minute

    if weekday == 5 or weekday == 6:
        return (1380 <= time <= 1439) or (0 <= time < 170)

    if (660 <= time <= 890):
        return True
    if (1380 <= time <= 1439):
        return True
    if (0 <= time < 170):
        return True

    return False

def main():
    now = datetime.now(ZoneInfo("Europe/Prague"))
    print(f"Aktuální čas na serveru: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=== Karel STUDNA ===")

    if not is_allowed_time(now):
        print("Mimo povolené časy čerpání.")
        return "Mimo povolené časy čerpání."

    level = eStudna_GetWaterLevel(EMAIL, PASSWORD, SN)
    print(f"Aktuální hladina: {level:.1f} cm")

    if level >= HIGH_LEVEL:
        print("Hladina je dostatečná, vypínám čerpadlo.")
        eStudna_SetOutput(EMAIL, PASSWORD, SN, False)
        save_state({"phase": "off", "until": None})
        return "Hladina dostatečná – čerpadlo vypnuto."

    state = load_state()
    until = datetime.fromisoformat(state["until"]) if state["until"] else None

    if state["phase"] == "on" and until and now < until:
        print(f"Čerpadlo běží do {until}")
        return f"Čerpadlo běží do {until}"
    elif state["phase"] == "on":
        print("Fáze ON skončila, vypínám čerpadlo.")
        eStudna_SetOutput(EMAIL, PASSWORD, SN, False)
        next_until = now + OFF_DURATION
        save_state({"phase": "off", "until": next_until.isoformat()})
        return "Fáze ON skončila – přecházím do OFF."

    if state["phase"] == "off" and until and now < until:
        print(f"Pauza – čekám do {until}")
        return f"Pauza – čekám do {until}"

    print("Hladina nedostatečná, zapínám čerpadlo.")
    eStudna_SetOutput(EMAIL, PASSWORD, SN, True)
    next_until = now + ON_DURATION
    save_state({"phase": "on", "until": next_until.isoformat()})
    return "Hladina nízká – čerpadlo zapnuto na 3 minuty."

app = Flask(__name__)

@app.route("/")
def spustit():
    try:
        vysledek = main()
        return f"✅ Spuštěno: {vysledek}"
    except Exception as e:
        return f"❌ Chyba: {e}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
