# ------------------------------------------------------------------------------
#   Data collection script for myo armband
#   - Collects raw EMG and IMU data with timestamp and user defined tag
#   - Outputs CSV file, formatted as: timestamp, type(EMG/IMU), Hex raw data, user tag
#   - Data collected are raw hex format, needs to process before using
# ------------------------------------------------------------------------------
import json
import asyncio
import time
import csv
from datetime import datetime
from bleak import BleakClient

with open("config.json", "r") as f:
    config = json.load(f)

MYO_ADDRESS = config["MYO_UUID"]

IMU_CHARACTERISTIC_UUID = "d5060402-a904-deb9-4748-2c7f4a124842"
EMG_CHARACTERISTIC_UUIDS = [
    "d5060105-a904-deb9-4748-2c7f4a124842",
    "d5060205-a904-deb9-4748-2c7f4a124842",
    "d5060305-a904-deb9-4748-2c7f4a124842",
    "d5060405-a904-deb9-4748-2c7f4a124842",
]
COMMAND_CHARACTERISTIC_UUID = "d5060401-a904-deb9-4748-2c7f4a124842"

# Set mode: EMG=raw (0x03), IMU=raw (0x04), classifier=0
# You can switch to IMU=0x03 to send all instead since some people found more stable
SET_MODE_CMD = bytearray([0x01, 3, 0x03, 0x03, 0x00])

# Keep-alive command: myohw_command_user_action (0x0b)
# Byte0=0x0b, Byte1=1 (payload size), Byte2=0x00 (user_action_single)
KEEP_ALIVE_CMD = bytearray([0x0b, 0x01, 0x00])

# Data buffer
data_rows = []
start_time = None
current_label = ""

# A global flag to stop the background keep-alive task
STOP_KEEP_ALIVE = False

# Callback functions
def emg_callback(sender, raw_data: bytearray):
    t = time.time() - start_time
    row = {
        "timestamp": t,
        "type": "EMG",
        "raw_hex": raw_data.hex(),
        "pose": current_label,
    }
    data_rows.append(row)

def imu_callback(sender, raw_data: bytearray):
    t = time.time() - start_time
    row = {
        "timestamp": t,
        "type": "IMU",
        "raw_hex": raw_data.hex(),
        "pose": current_label,
    }
    data_rows.append(row)

# Keep-Alive Background Task
async def keep_alive_loop(client: BleakClient, interval=5.0):
    """
    Periodically send a user action (keep-alive) command every 'interval' seconds.
    This prevents Myo from partially powering down the IMU.
    """
    global STOP_KEEP_ALIVE
    while not STOP_KEEP_ALIVE:
        await asyncio.sleep(interval)
        try:
            await client.write_gatt_char(COMMAND_CHARACTERISTIC_UUID, KEEP_ALIVE_CMD, response=True)
            print("[KEEP_ALIVE] Sent user action to keep Myo active.")
        except Exception as e:
            print(f"[KEEP_ALIVE] Error sending keep-alive: {e}")
            break

# Setup & Data Collection
async def setup_myo(client: BleakClient):
    """
    Configure raw EMG + raw IMU streaming mode.
    Previously we had a 'never sleep' command, but now we rely on keep_alive_loop.
    """
    await client.write_gatt_char(COMMAND_CHARACTERISTIC_UUID, SET_MODE_CMD, response=True)
    print("Myo set to raw EMG + IMU streaming mode.")

async def collect_data_for_duration(client: BleakClient, duration: float):
    """
    Subscribe to EMG+IMU, gather for 'duration' seconds, then unsubscribe.
    """
    await client.start_notify(IMU_CHARACTERISTIC_UUID, imu_callback)
    for emg_uuid in EMG_CHARACTERISTIC_UUIDS:
        await client.start_notify(emg_uuid, emg_callback)

    await asyncio.sleep(duration)

    # Stop notifications
    try:
        await client.stop_notify(IMU_CHARACTERISTIC_UUID)
        for emg_uuid in EMG_CHARACTERISTIC_UUIDS:
            await client.stop_notify(emg_uuid)
    except Exception:
        pass

# Main application flow
async def run():
    global STOP_KEEP_ALIVE
    print(f"Attempting to connect to Myo at {MYO_ADDRESS}...")
    async with BleakClient(MYO_ADDRESS) as client:
        if client.is_connected:
            print("Connected to Myo!")
            await setup_myo(client)

            # Start background keep-alive
            STOP_KEEP_ALIVE = False
            keep_alive_task = asyncio.create_task(keep_alive_loop(client, interval=5.0))

            while True:
                duration_str = input("Enter duration in seconds (or 'q' to quit): ")
                if duration_str.lower() == 'q':
                    print("Exiting...")
                    break

                try:
                    duration_val = float(duration_str)
                except ValueError:
                    print("Invalid number. Try again.")
                    continue

                pose_label = input("Enter the pose/label name (e.g. 'hand_clench'): ").strip()
                if not pose_label:
                    pose_label = "unlabeled"

                # Countdown
                print(f"Recording for {duration_val} seconds with label '{pose_label}'.")
                for c in [3, 2, 1]:
                    print(c)
                    await asyncio.sleep(1)
                print("Collecting, keep your pose still...")

                global data_rows, start_time, current_label
                data_rows = []
                current_label = pose_label
                start_time = time.time()

                # Collect
                await collect_data_for_duration(client, duration_val)
                print("Collection finished.")

                # Save CSV
                timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                csv_filename = f"myo_raw_{pose_label}_{timestamp_str}.csv"

                columns = ["timestamp", "type", "raw_hex", "pose"]
                with open(csv_filename, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(data_rows)

                print(f"Saved {len(data_rows)} rows to {csv_filename}.")

                again = input("Collect another dataset? (y/n): ").lower()
                if again != 'y':
                    print("Exiting data collection.")
                    break

            # Stop keep-alive
            STOP_KEEP_ALIVE = True
            await asyncio.sleep(0)  # let keep_alive_loop exit

        else:
            print("Failed to connect to Myo.")

def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()
