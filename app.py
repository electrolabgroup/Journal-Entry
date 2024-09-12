from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import os
import pandas as pd
import requests
import time
from datetime import datetime
from threading import Thread

# Initialize the Flask app and SocketIO
app = Flask(__name__)
socketio = SocketIO(app)

# Folder to store uploaded files and static files
UPLOAD_FOLDER = 'uploads'
STATIC_FOLDER = 'static'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['STATIC_FOLDER'] = STATIC_FOLDER

# Ensure the folders exist
for folder in [UPLOAD_FOLDER, STATIC_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# Base URL and API endpoint for ERP system
base_url = 'http://uat.electrolabgroup.com/'
endpoint = 'api/resource/Journal Entry'
url = base_url + endpoint
headers = {
    'Authorization': 'token 53be8c72ce2399c:b73c79318e16953',
    'Content-Type': 'application/json'
}

# Function to prepare data from DataFrame
def prepare_data(df):
    df = df.fillna('')
    df = df.convert_dtypes()
    grouped = df.groupby('remark')
    journal_entries = []

    for remark, group in grouped:
        main_entry = {
            'voucher_type': group['voucher_type'].iloc[0],
            'naming_series': group['naming_series'].iloc[0],
            'company': group['company'].iloc[0],
            'remark': group['remark'].iloc[0],
            'accounts': []
        }

        for _, row in group.iterrows():
            main_entry['accounts'].append({
                'account': row['account'],
                'credit_in_account_currency': str(row['credit_in_account_currency']),
                'debit_in_account_currency': str(row['debit_in_account_currency']),
                'reference_type': row.get('reference_type') if pd.notna(row.get('reference_type')) else ' ',
                'party_type': row.get('party_type', 'Supplier'),
                'party': row.get('party', 'DHL Express (I) Pvt. Ltd.')
            })

        journal_entries.append(main_entry)

    return journal_entries

def push_data(data):
    messages = []
    failed_entries = []

    for entry in data:
        response = requests.post(url, json=entry, headers=headers)
        if response.status_code == 200:
            status = "Success"
        else:
            status = "Failed"
            failed_entries.append(entry)
        
        # Emit the result via WebSocket
        socketio.emit('data_update', {
            "remark": entry.get('remark', ''), 
            "account": entry.get('accounts', [{}])[0].get('account', ''), 
            "status": status
        })

        # Sleep briefly to simulate processing time
        time.sleep(0.1)
        
    # Save failed entries to an Excel file with a unique name in static folder
    if failed_entries:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f'failed_entries_{timestamp}.xlsx'
        filepath = os.path.join(app.config['STATIC_FOLDER'], filename)
        failed_df = pd.DataFrame(failed_entries)
        failed_df.to_excel(filepath, index=False)

        # Log the file path and name
        print(f"Failed entries file saved as: {filepath}")

        Thread(target=cleanup_temp_files, args=(filepath, 3600)).start()

    return messages, filename if failed_entries else ''

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400

    if file:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)

        # Log the file save
        print(f"File saved to: {filepath}")

        Thread(target=cleanup_temp_files, args=(filepath, 3600)).start()

        try:
            if file.filename.endswith('.csv'):
                df = pd.read_csv(filepath)
            elif file.filename.endswith('.xlsx'):
                df = pd.read_excel(filepath)
            else:
                return jsonify({"status": "error", "message": "Unsupported file format. Please upload a CSV or Excel file."}), 400

            prepared_data = prepare_data(df)
            messages, failed_file = push_data(prepared_data)

            download_link = ''
            if failed_file:
                download_link = f'/static/{failed_file}'

            # Log the download link
            print(f"Download link: {download_link}")

            return jsonify({"status": "success", "messages": messages, "download_link": download_link}), 200

        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

def cleanup_temp_files(filepath, delay):
    time.sleep(delay)  # Wait for the specified time
    if os.path.exists(filepath):
        os.remove(filepath)
        print(f"File {filepath} deleted.")

if __name__ == '__main__':
    socketio.run(app, debug=True)
