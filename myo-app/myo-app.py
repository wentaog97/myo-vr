''' 
    Myo visualizer - backend
'''

import asyncio
import threading
from typing import Dict, List, Optional
from flask import Flask, abort, jsonify, render_template, request
from bleak import BleakClient, BleakScanner
from flask_socketio import SocketIO

import csv, os, json

# BLE services constants 
_COMMAND_UUID = "d5060401-a904-deb9-4748-2c7f4a124842"  # Myo control characteristic
_VOLT_UUID   = "d5060404-a904-deb9-4748-2c7f4a124842"  # Hidden voltage characteristic
_BATTERY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"  # Battery Service 
_MYO_INFO_UUID = "d5060101-a904-deb9-4748-2c7f4a124842" # Model name
_MYO_FIRMWARE_UUID = "d5060201-a904-deb9-4748-2c7f4a124842" # Firmware version
_MYO_SERVICE_PREFIX = "d506"  # Any service that starts with this is Myo-specific

_EMG_UUID = "d5060105-a904-deb9-4748-2c7f4a124842"
_IMU_UUID = "d5060402-a904-deb9-4748-2c7f4a124842"

# Enable raw EMG + IMU
_SET_MODE_CMD = bytearray([0x01, 3, 0x03, 0x04, 0x00])
# Never-sleep (silent heartbeat)
_NEVER_SLEEP_CMD = bytearray([0x09, 0x01, 0x01])
# Vibration payloads
_VIB_CMDS = {
    "short":  bytearray([0x03, 0x01, 0x01]),
    "medium": bytearray([0x03, 0x01, 0x02]),
    "long":   bytearray([0x03, 0x01, 0x03]),
}
_ALLOW_SLEEP_CMD = bytearray([0x09, 0x01, 0x00])
_DEEP_SLEEP_CMD = bytearray([0x04, 0x00])

# ---------------------------------------------------------------------------
# One global asyncio loop running in a daemon thread so Flask can stay sync 
# ---------------------------------------------------------------------------
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()

def run_async(coro):
    """Run *coro* on the background loop **synchronously** and return result."""
    return asyncio.run_coroutine_threadsafe(coro, loop).result()

def fire_and_forget(coro):
    """Schedule *coro* on the loop without awaiting its result."""
    asyncio.run_coroutine_threadsafe(coro, loop)

# MYO BLE services manager
class MyoManager:
    def __init__(self) -> None:
        self._client: Optional[BleakClient] = None
        self._lock = asyncio.Lock()
        self._connected: bool = False
        self._battery: Optional[int] = None
        self._keep_alive_task: Optional[asyncio.Task] = None
        self._last_error: Optional[str] = None
        self._sku = None
        self._firmware_version = None
        self._emg_mode = 3  # Default raw EMG
        self._imu_mode = 1  # Default raw IMU 

    # ---------- Public sync wrappers called from Flask ----------
    def scan(self) -> List[Dict[str, str]]:
        return run_async(self._scan())

    def connect(self, address: str, set_mode_cmd=None, emg_mode=3, imu_mode=1) -> None:
        self._emg_mode = emg_mode
        self._imu_mode = imu_mode
        run_async(self._connect(address, set_mode_cmd))


    def disconnect_async(self) -> None:
        fire_and_forget(self._disconnect())

    def reset_async(self) -> None: # public wrapper
        fire_and_forget(self._deep_sleep())

    def vibrate_async(self, pattern: str) -> None:
        fire_and_forget(self._vibrate(pattern))

    def refresh_battery_async(self) -> None:
        if self._connected:
            fire_and_forget(self._read_battery())

    # ---------- Public properties ------------------------------
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def battery(self) -> Optional[int]:
        return self._battery
    
    @property
    def sku(self) -> Optional[int]:
        return self._sku
    
    @property
    def firmware_version(self):
        return self._firmware_version

    @property
    def model_name(self) -> Optional[str]:
        models = {
            1: "MYO Black",
            2: "MYO White",
            3: "MYOD5",
            0: "Unknown/Old"
        }
        return models.get(self._sku, f"SKU {self._sku}" if self._sku is not None else None)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error
    
    async def _start_emg_stream(self):
        if not self._client or not self._client.is_connected:
            return

        def notification_handler(_, data: bytearray):
            if len(data) == 16:
                samples = [
                    [int.from_bytes([b], byteorder="little", signed=True) for b in data[:8]],
                    [int.from_bytes([b], byteorder="little", signed=True) for b in data[8:]]
                ]
                socketio.emit("emg", {
                    "samples": samples,
                    "raw": data.hex()
                })


        try:
            await self._client.start_notify(_EMG_UUID, notification_handler)
        except Exception as e:
            print(f"EMG stream error: {e}")

    async def _start_imu_stream(self):
        if not self._client or not self._client.is_connected:
            print("IMU stream: No client or not connected")
            return

        def imu_handler(_, data: bytearray):
            if len(data) == 20:
                q = [int.from_bytes(data[i:i+2], byteorder="little", signed=True) / 16384.0 for i in range(0, 8, 2)]
                a = [int.from_bytes(data[i:i+2], byteorder="little", signed=True) for i in range(8, 14, 2)]
                g = [int.from_bytes(data[i:i+2], byteorder="little", signed=True) for i in range(14, 20, 2)]
                socketio.emit("imu", {
                    "quat": q,
                    "acc": a,
                    "gyro": g,
                    "raw": data.hex()
                })

        try:
            print("Starting IMU notify...")
            await self._client.start_notify(_IMU_UUID, imu_handler)
            print("IMU stream started.")
        except Exception as e:
            print(f"IMU stream error: {e}")


    async def _deep_sleep(self):
        if not self._connected:
            return
        try:
            await self._client.write_gatt_char(_COMMAND_UUID, _DEEP_SLEEP_CMD, response=True)
            await asyncio.sleep(0.2)          
        finally:
            await self._disconnect()        

    async def _scan(self) -> List[Dict[str, str]]:
        devs = await BleakScanner.discover(timeout=4.0)
        filtered = []
        for d in devs:
            name = (d.name or "").lower()
            uuids = [u.lower() for u in d.metadata.get("uuids", [])]
            if "myo" in name or any(u.startswith(_MYO_SERVICE_PREFIX) for u in uuids):
                filtered.append(d)
        seen = {}
        for d in filtered:
            seen.setdefault(d.address, d)
        return [
            {"name": (d.name or "Myo Armband"), "address": d.address}
            for d in seen.values()
        ]

    async def _connect(self, address: str, set_mode_cmd=None):
        # First ensure any existing session is closed (outside lock)
        await self._disconnect()

        async with self._lock:
            self._last_error = None  # clear stale errors
            try:
                self._client = BleakClient(address)
                await self._client.connect()
                self._client.set_disconnected_callback(self._on_ble_disconnect)
                
                # Configure stream + never-sleep heartbeat
                await self._client.write_gatt_char(_COMMAND_UUID, set_mode_cmd or _SET_MODE_CMD, response=True)
                await self._client.write_gatt_char(_COMMAND_UUID, _NEVER_SLEEP_CMD, response=True)

                # Get info about the MYO
                self._connected = True
                await self._read_battery()
                await self._read_model_info()
                await self._read_firmware_info()

                # Start streaming EMG and IMU
                await self._client.write_gatt_char(_COMMAND_UUID, set_mode_cmd or _SET_MODE_CMD, response=True)
                await asyncio.sleep(0.1)
                await self._start_emg_stream()
                await asyncio.sleep(0.1)
                await self._start_imu_stream()
                
                self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())

                print(f"Connected to {address}")

            except Exception as exc:
                await self._disconnect()
                self._last_error = f"Connect failed: {exc}"
                raise

    async def _disconnect(self):
        async with self._lock:
            if self._client and self._client.is_connected:
                if self._keep_alive_task:
                    self._keep_alive_task.cancel()
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
            # Reset state
            self._client = None
            self._keep_alive_task = None
            self._battery = None
            self._connected = False
            print("Disconnected")

    async def _vibrate(self, pattern: str):
        if not self._connected:
            return  # silently ignore when not connected
        payload = _VIB_CMDS.get(pattern, _VIB_CMDS["medium"])
        try:
            await self._client.write_gatt_char(_COMMAND_UUID, payload, response=True)
        except Exception as exc:
            self._last_error = f"Vibrate error: {exc}"

    async def _keep_alive_loop(self):
        try:
            while self._connected:
                await self._client.write_gatt_char(_COMMAND_UUID, _NEVER_SLEEP_CMD, response=True)
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._last_error = f"Keep-alive error: {exc}"
            await self._disconnect()

    async def _read_battery(self):
        # Try standard Battery Service first
        try:
            data = await self._client.read_gatt_char(_BATTERY_UUID)
            if data:
                self._battery = int(data[0])
                return
        except Exception:
            pass 
        try:
            v_bytes = await self._client.read_gatt_char(_VOLT_UUID)
            if v_bytes and len(v_bytes) >= 2:
                millivolts = int.from_bytes(v_bytes[:2], byteorder="little")
                voltage = millivolts / 1000.0  # e.g. 4012 → 4.012 V
                percent = round(min(max((voltage - 3.7) / 0.5, 0), 1) * 100)
                self._battery = percent
                return
        except Exception:
            pass
        self._battery = None  

    async def _read_model_info(self):
        try:
            data = await self._client.read_gatt_char(_MYO_INFO_UUID)
            if len(data) == 20:
                self._sku = data[12]
                print(f"[DEBUG] Myo SKU: {self._sku}")
        except Exception as e:
            print(f"Failed to read model info: {e}")
            self._sku = None
            
    async def _read_firmware_info(self):
        try:
            data = await self._client.read_gatt_char(_MYO_FIRMWARE_UUID)
            if len(data) >= 6:
                major = int.from_bytes(data[0:2], byteorder="little")
                minor = int.from_bytes(data[2:4], byteorder="little")
                patch = int.from_bytes(data[4:6], byteorder="little")
                self._firmware_version = f"{major}.{minor}.{patch}"
                print(f"[DEBUG] Firmware version: {self._firmware_version}")
        except Exception as e:
            print(f"Failed to read firmware version: {e}")
            self._firmware_version = None

    # ---------- BLE callback executed on Bleak thread ----------
    def _on_ble_disconnect(self, _):
        if loop.is_running():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(self._disconnect()))

# ---------------------------------------------------------------------------
# Flask API 
# ---------------------------------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
socketio = SocketIO(app, async_mode="threading")
myo = MyoManager()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/scan")
def scan():
    try:
        return jsonify(myo.scan())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/connect", methods=["POST"])
def connect():
    content = request.get_json() or {}
    addr = content.get("address")
    emg_mode = content.get("emg_mode", 3)  # Default raw
    imu_mode = content.get("imu_mode", 1)  # Default data

    if not addr:
        abort(400, "address missing")

    # Build dynamic SET_MODE_CMD
    set_mode_cmd = bytearray([0x01, 3, emg_mode, imu_mode, 0x00])

    try:
        myo.connect(addr, set_mode_cmd=set_mode_cmd)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/disconnect", methods=["POST"])
def disconnect():
    myo.disconnect_async()
    return jsonify({"success": True})

@app.route("/reset", methods=["POST"])
def reset():
    myo.reset_async()
    return jsonify({"success": True})

@app.route("/vibrate", methods=["POST"])
def vibrate():
    pat = (request.get_json(silent=True) or {}).get("pattern", "medium")
    myo.vibrate_async(pat)
    return jsonify({"success": True})

@app.route("/status")
def status():
    myo.refresh_battery_async()
    
    # If connected, suppress stale errors so UI stays green
    error = None if myo.connected else myo.last_error

    return jsonify({
        "connected": myo.connected,
        "battery": myo.battery,
        "model": myo.model_name,
        "firmware": myo.firmware_version,
        "error": error,
    })

@app.route("/update-mode", methods=["POST"])
def update_mode():
    content = request.get_json() or {}
    emg_mode = content.get("emg_mode")
    imu_mode = content.get("imu_mode")

    if emg_mode is None or imu_mode is None:
        abort(400, "Missing modes")

    set_mode_cmd = bytearray([0x01, 3, emg_mode, imu_mode, 0x00])

    try:
        if myo.connected and myo._client and myo._client.is_connected:
            run_async(myo._client.write_gatt_char(_COMMAND_UUID, set_mode_cmd, response=True))
            myo._emg_mode = emg_mode
            myo._imu_mode = imu_mode
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/save-data", methods=["POST"])
def save_data():
    content = request.get_json()
    path = content.get("path")
    data = content.get("data")

    if not path or not data:
        return jsonify({"error": "Missing path or data"}), 400

    dir_path = os.path.dirname(path)
    os.makedirs(dir_path, exist_ok=True)

    try:
        is_raw = all("raw_hex" in row for row in data)

        with open(path, "w", newline="") as f:
            if is_raw:
                f.write("# Firmware: {}\n".format(myo.firmware_version or 'unknown'))
                f.write("# SKU: {}\n".format(myo.sku or 'unknown'))
                f.write("# Model: {}\n".format(myo.model_name or 'unknown'))
                f.write("# EMG Mode: {}\n".format(
                    {0: "None", 2: "Filtered", 3: "Raw"}.get(myo._emg_mode, f"Unknown ({myo._emg_mode})")
                ))
                f.write("# IMU Mode: {}\n".format(
                    {0: "None", 1: "Data", 2: "Events", 3: "All", 4: "Raw"}.get(myo._imu_mode, f"Unknown ({myo._imu_mode})")
                ))
                f.write("# Format: timestamp,type,raw_hex,label\n")

                writer = csv.writer(f)
                writer.writerow(["timestamp", "type", "raw_hex", "label"])

                for row in data:
                    writer.writerow([
                        row.get("timestamp", ""),
                        row.get("type", ""),
                        row.get("raw_hex", ""),
                        row.get("label", "unlabeled")
                    ])
            else:
                f.write("# Firmware: {}\n".format(myo.firmware_version or 'unknown'))
                f.write("# SKU: {}\n".format(myo.sku or 'unknown'))
                f.write("# Model: {}\n".format(myo.model_name or 'unknown'))
                f.write("# EMG Mode: {}\n".format(
                    {0: "None", 2: "Filtered", 3: "Raw"}.get(myo._emg_mode, f"Unknown ({myo._emg_mode})")
                ))
                f.write("# IMU Mode: {}\n".format(
                    {0: "None", 1: "Data", 2: "Events", 3: "All", 4: "Raw"}.get(myo._imu_mode, f"Unknown ({myo._imu_mode})")
                ))
                f.write("# Format: timestamp,emg_0...7,quat_wxyz,acc_xyz,gyro_xyz,label\n")

                writer = csv.writer(f)
                writer.writerow([
                    "timestamp",
                    *[f"emg_{i}" for i in range(8)],
                    "quat_w", "quat_x", "quat_y", "quat_z",
                    "acc_x", "acc_y", "acc_z",
                    "gyro_x", "gyro_y", "gyro_z",
                    "label"
                ])
                for row in data:
                    ts = row.get("timestamp", "")
                    label = row.get("label", "unlabeled")
                    emg = row.get("emg", [""] * 8)
                    imu = row.get("imu") or {}
                    quat = imu.get("quat", [""] * 4)
                    acc = imu.get("acc", [""] * 3)
                    gyro = imu.get("gyro", [""] * 3)

                    writer.writerow([
                        ts, *emg,
                        *quat, *acc, *gyro,
                        label
                    ])

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"success": True})

if __name__ == "__main__":
    socketio.run(app, debug=True, port=5000)
