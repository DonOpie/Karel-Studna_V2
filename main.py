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

class ThingsBoard:
    def __init__(self):
        self.server = 'https://cml.seapraha.cz'
        self.userToken = None
        self.customerId = None

    def load_token(self):
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
            expires = datetime.fromisoformat(data["expires"])
            if datetime.now(ZoneInfo("Europe/Prague")) < expires:
                self.userToken = data["token"]
                return True
        return False

    def save_token(self, token):
        expires = datetime.now(ZoneInfo("Europe/Prague")) + timedelta(hours=24)
        with open(TOKEN_FILE, "w") as f:
            json.dump({"token": token, "expires": expires.isoformat()}, f)

    def login(self, username, password):
        if self.load_token():
            # Získání customerId pomocí tokenu
            try:
                url = f'{self.server}/api/auth/user'
                response = httpGet(url, {'X-Authorization': f"Bearer {self.userToken}"})
                self.customerId = response["customerId"]["id"]
                return
            except:
                pass  # Token je neplatný, pokračuj přihlášením

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
    hladina = eStudna_GetWaterLevel(EMAIL, PASSWORD, SN)
    zprava = f"\n✅ **Karel STUDNA**\nAktuální čas: {now.strftime('%Y-%m-%d %H:%M:%S')}\nHladina: {hladina:.1f} cm\n"

    if not is_allowed_time(now):
        return zprava + "⛔ Mimo povolené časy čerpání."

    if hladina >= HIGH_LEVEL:
        eStudna_SetOutput(EMAIL, PASSWORD, SN, False)
        save_state({"phase": "off", "until": None})
        return zprava + "✅ Hladina dostatečná – čerpadlo vypnuto."

    state = load_state()
    until = datetime.fromisoformat(state["until"]) if state["until"] else None

    if state["phase"] == "on" and until and now < until:
        return zprava + f"🚿 Čerpadlo běží do {until.strftime('%H:%M:%S')}"
    elif state["phase"] == "on":
        eStudna_SetOutput(EMAIL, PASSWORD, SN, False)
        next_until = now + OFF_DURATION
        save_state({"phase": "off", "until": next_until.isoformat()})
        return zprava + "🔁 Fáze ON skončila – přecházím do OFF."

    if state["phase"] == "off" and until and now < until:
        return zprava + f"⏸ Pauza – čekám do {until.strftime('%H:%M:%S')}"

    eStudna_SetOutput(EMAIL, PASSWORD, SN, True)
    next_until = now + ON_DURATION
    save_state({"phase": "on", "until": next_until.isoformat()})
    return zprava + "💧 Hladina nízká – čerpadlo zapnuto na 3 minuty."

# --- Flask ---
app = Flask(__name__)

@app.route("/")
def spustit():
    try:
        vysledek = main()
        return f"{vysledek}"
    except Exception as e:
        return f"\n✅ **Karel STUDNA**\n❌ Chyba: {e}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
