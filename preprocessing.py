import csv
import struct
import glob
import os

def preprocess_myo_csv(input_csv, output_csv):
    """
    Read a CSV with columns [timestamp, type, raw_hex, pose],
    extract rows where type='EMG', parse the 16 raw bytes into two 8-channel samples,
    and write a new CSV with columns:
      [timestamp, emg1_1..8, emg2_1..8, pose]
    """
    with open(input_csv, 'r', newline='') as fin, open(output_csv, 'w', newline='') as fout:
        reader = csv.DictReader(fin)
        fieldnames = [
            'timestamp',
            'emg1_1','emg1_2','emg1_3','emg1_4','emg1_5','emg1_6','emg1_7','emg1_8',
            'emg2_1','emg2_2','emg2_3','emg2_4','emg2_5','emg2_6','emg2_7','emg2_8',
            'pose'
        ]
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            if row.get('type') != 'EMG':
                continue  # skip IMU or other lines

            timestamp = row['timestamp']
            pose = row.get('pose', '')

            raw_hex = row['raw_hex']
            raw_bytes = bytes.fromhex(raw_hex)
            if len(raw_bytes) < 16:
                # skip malformed lines
                continue

            # Parse as 16 signed 8-bit integers => two 8-channel samples
            samples = struct.unpack('16b', raw_bytes)
            emg1 = samples[0:8]
            emg2 = samples[8:16]

            out_row = {
                'timestamp': timestamp,
                'emg1_1': emg1[0], 'emg1_2': emg1[1], 'emg1_3': emg1[2], 'emg1_4': emg1[3],
                'emg1_5': emg1[4], 'emg1_6': emg1[5], 'emg1_7': emg1[6], 'emg1_8': emg1[7],
                'emg2_1': emg2[0], 'emg2_2': emg2[1], 'emg2_3': emg2[2], 'emg2_4': emg2[3],
                'emg2_5': emg2[4], 'emg2_6': emg2[5], 'emg2_7': emg2[6], 'emg2_8': emg2[7],
                'pose': pose,
            }
            writer.writerow(out_row)

def main():
    # For example, process all CSV files matching 'myo_raw_*.csv'
    input_pattern = 'myo_raw_*.csv'
    csv_files = glob.glob(input_pattern)
    if not csv_files:
        print(f"No files found matching pattern '{input_pattern}'")
        return

    print(f"Found {len(csv_files)} CSV files. Processing...")

    for input_csv in csv_files:
        # Output filename: append '_emg' before .csv
        base, ext = os.path.splitext(input_csv)
        output_csv = f"{base}_emg{ext}"

        preprocess_myo_csv(input_csv, output_csv)
        print(f"Processed {input_csv} -> {output_csv}")

if __name__ == '__main__':
    main()
