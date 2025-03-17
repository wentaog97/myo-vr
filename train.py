import pandas as pd
import glob
import os
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score
import joblib

# Load and concatenate multiple CSV files matching the given glob pattern.
# Each file is expected to have columns: [timestamp, emg1_1..emg1_8, emg2_1..emg2_8, pose]
# Returns a pandas DataFrame with all rows from all files.
def load_emg_data(pattern='myo_raw_*_emg.csv'):
    files = glob.glob(pattern)
    if not files:
        print(f"No files found matching pattern: {pattern}")
        return pd.DataFrame()

    dfs = []
    for f in files:
        df = pd.read_csv(f)
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)

def prepare_features_labels(df):
    # Identify feature columns
    feature_cols = [col for col in df.columns if col.startswith('emg1_') or col.startswith('emg2_')]
    # Example: emg1_1..emg1_8, emg2_1..emg2_8 => total 16 channels

    # We'll treat them as 16 separate features. 
    # If you want to exclude 'timestamp', do it here. 
    X = df[feature_cols].values

    # Label: 'pose'
    if 'pose' not in df.columns:
        raise ValueError("DataFrame must contain a 'pose' column for labels.")
    y_str = df['pose'].values

    # Convert string poses to numeric labels
    label_encoder = LabelEncoder()
    y = label_encoder.fit_transform(y_str)

    return X, y, label_encoder

def main():
    data_df = load_emg_data(pattern='myo_raw_*_emg.csv')
    if data_df.empty:
        print("No data found. Exiting.")
        return

    X, y, label_encoder = prepare_features_labels(data_df)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    clf = RandomForestClassifier(n_estimators=100, random_state=42)
    clf.fit(X_train_scaled, y_train)

    y_pred = clf.predict(X_test_scaled)
    print("Accuracy:", accuracy_score(y_test, y_pred))
    print("Classification Report:\n", classification_report(y_test, y_pred, target_names=label_encoder.classes_))

    os.makedirs('models', exist_ok=True)
    joblib.dump({
        'classifier': clf,
        'scaler': scaler,
        'label_encoder': label_encoder
    }, 'models/myo_emg_model.pkl')
    print("Model saved to models/myo_emg_model.pkl")

if __name__ == '__main__':
    main()
