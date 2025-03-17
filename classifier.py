import json
import asyncio
import struct
import time
from bleak import BleakClient
import numpy as np
import joblib

# Setups
with open("config.json", "r") as f:
    config = json.load(f)

MYO_ADDRESS = config["MYO_UUID"]

COMMAND_CHARACTERISTIC_UUID = "d5060401-a904-deb9-4748-2c7f4a124842"

EMG_CHARACTERISTIC_UUIDS = [
    "d5060105-a904-deb9-4748-2c7f4a124842",
    "d5060205-a904-deb9-4748-2c7f4a124842",
    "d5060305-a904-deb9-4748-2c7f4a124842",
    "d5060405-a904-deb9-4748-2c7f4a124842",
]

# Command to set EMG=raw(0x03), IMU=none(0x00) (or send_all=0x03 if you want IMU),
# and classifier=0 (off).
# Adjust IMU mode if you also want orientation/acc data, etc.
SET_MODE_CMD = bytearray([0x01, 3, 0x03, 0x00, 0x00])

# Path to your saved model file (from joblib.dump)
MODEL_PATH = "models/myo_emg_model.pkl"

# Assume the .pkl includes a dict: {'classifier', 'scaler', 'label_encoder'}
model_data = joblib.load(MODEL_PATH)
classifier = model_data['classifier']
scaler = model_data['scaler']
label_encoder = model_data['label_encoder']

start_time = None

def emg_callback(sender: int, data: bytearray):
    """
    Called every time Myo sends an EMG notification.
    data is 16 bytes => 2 sets of 8 channels.
    We parse into 16 signed 8-bit integers, scale, and predict pose.
    """
    t = time.time() - start_time
    # Parse 16 bytes => '16b'
    if len(data) < 16:
        return
    samples = struct.unpack('16b', data)
    # The first 8 are one sub-sample, the next 8 are another
    # We'll just treat them as a 16D feature vector
    # i.e., [emg1_1..8, emg2_1..8]
    X = np.array(samples, dtype=float).reshape(1, -1)  # shape (1,16)

    # Scale the features with the same scaler from training
    X_scaled = scaler.transform(X)

    # Predict
    y_pred = classifier.predict(X_scaled)
    pose_str = label_encoder.inverse_transform(y_pred)[0]

    print(f"Pose={pose_str}")

# Write to command characteristic to set EMG streaming mode.
async def setup_myo(client: BleakClient):
    await client.write_gatt_char(COMMAND_CHARACTERISTIC_UUID, SET_MODE_CMD, response=True)
    print("Myo set to raw EMG streaming mode.")


# Subscribes to all four EMG characteristics, collects data for 'duration' seconds,
# then unsubscribes.
async def stream_emg(client: BleakClient, duration=10.0):

    for uuid in EMG_CHARACTERISTIC_UUIDS:
        await client.start_notify(uuid, emg_callback)

    print(f"Streaming EMG for {duration} seconds... Press Ctrl+C to stop earlier.")
    await asyncio.sleep(duration)

    # Unsubscribe
    try:
        for uuid in EMG_CHARACTERISTIC_UUIDS:
            await client.stop_notify(uuid)
    except Exception:
        pass

async def run_realtime_myo(duration=10.0):
    global start_time

    print(f"Connecting to Myo at address: {MYO_ADDRESS}")
    async with BleakClient(MYO_ADDRESS) as client:
        if client.is_connected:
            print("Connected to Myo!")
            start_time = time.time()

            # Set up raw EMG mode
            await setup_myo(client)

            # Start streaming for 'duration' seconds
            await stream_emg(client, duration)

            print("Done streaming.")
        else:
            print("Failed to connect to Myo.")

def main():
    try:
        duration = 60.0
        asyncio.run(run_realtime_myo(duration=duration))
    except KeyboardInterrupt:
        print("\nInterrupted.")

if __name__ == "__main__":
    main()
