from flask import Flask
import requests
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

EMAIL = "malykarel74@gmail.com"
PASSWORD = "Poklop74"
SN = "SB825040"

HIGH_LEVEL = 180
ON_DURATION = timedelta(minutes=3)
OFF_DURATION = timedelta(minutes=25)
STATE_FILE = "stav.json"

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

    def login(self, username, password):
        url = f'{self.server}/api/auth/login'
        response = httpPost(url, {}, data={'username': username, 'password': password})
        self.userToken = response["token"]
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
    weekday = now.weekday()  # 0 = pondělí, 6 = neděle
    hour = now.hour
    minute = now.minute
    time = hour * 60 + minute  # čas v minutách

    # Víkend (sobota, neděle): jen 23:00–2:50
    if weekday == 5 or weekday == 6:
        return (1380 <= time <= 1439) or (0 <= time < 170)

    # Pondělí až pátek: 11:00–14:50 a 23:00–2:50
    if (660 <= time <= 890):  # 11:00–14:50
        return True
    if (1380 <= time <= 1439):  # 23:00–23:59
        return True
    if (0 <= time < 170):  # 0:00–2:50 (následující den ráno)
        return True

    return False

def main():
    now = datetime.now(ZoneInfo("Europe/Prague"))
    print(f"Aktuální čas na serveru: {now.strftime('%Y-%m-%d %H:%M:%S')}")

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
    app.run(host="0.0.0.0", port=81)
