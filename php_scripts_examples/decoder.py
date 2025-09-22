# decode_response.py
import json
import base64

# --- Configuration ---
# The name of the JSON file  saved from  curl command
INPUT_JSON_FILE = "decoder/response_pdf.json"

# --- Script ---
print(f"Reading response from '{INPUT_JSON_FILE}'...")

try:
    with open(INPUT_JSON_FILE, 'r') as f:
        data = json.load(f)
except FileNotFoundError:
    print(f"Error: The file '{INPUT_JSON_FILE}' was not found.")
    print("Please make sure you've run the curl command and saved the output correctly.")
    exit()
except json.JSONDecodeError:
    print(f"Error: The file '{INPUT_JSON_FILE}' is not a valid JSON file.")
    exit()

# Decode the non-anonymous report
non_anon_base64 = data.get("non_anonymous_report_base64")
if non_anon_base64:
    non_anon_bytes = base64.b64decode(non_anon_base64)
    output_filename_non_anon = "DECODED_non_anonymous_report.pdf"
    with open(output_filename_non_anon, 'wb') as f_out:
        f_out.write(non_anon_bytes)
    print(f"✅ Successfully saved '{output_filename_non_anon}'")
else:
    print("⚠️  'non_anonymous_report_base64' key not found in JSON.")

# Decode the anonymous report
anon_base64 = data.get("anonymous_report_base64")
if anon_base64:
    anon_bytes = base64.b64decode(anon_base64)
    output_filename_anon = "DECODED_anonymous_report.pdf"
    with open(output_filename_anon, 'wb') as f_out:
        f_out.write(anon_bytes)
    print(f"✅ Successfully saved '{output_filename_anon}'")
else:
    print("⚠️  'anonymous_report_base64' key not found in JSON.")