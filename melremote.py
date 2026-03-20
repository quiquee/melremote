# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "cryptography",
#   "flask",
#   "requests",
# ]
# ///

import base64
import hashlib
import json
import os

import requests as req
from cryptography.fernet import Fernet
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


@app.route("/")
def serve_index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/favicon.ico")
def serve_favicon():
    return send_from_directory(BASE_DIR, "favicon.ico", mimetype="image/svg+xml")



def get_fernet(api_key: str) -> Fernet:
    key_bytes = hashlib.sha256(api_key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)

@app.route("/api/history")
def get_history():
    api_key = request.args.get("key")
    if not api_key:
        return jsonify({"error": "API key is required"}), 400

    history = []
    log_file = os.path.join(BASE_DIR, "chat_history.log")
    if os.path.exists(log_file):
        try:
            f = get_fernet(api_key)
            with open(log_file, "r") as file:
                for line in file:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        decrypted = f.decrypt(line.encode()).decode()
                        history.append(json.loads(decrypted))
                    except Exception:
                        pass
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"history": history[-50:]})

@app.route("/api/models")
def list_models():
    api_key = request.args.get("key")
    if not api_key:
        return jsonify({"error": "API key is required"}), 400

    try:
        all_models = []
        params = {"key": api_key, "pageSize": 100}

        while True:
            resp = req.get(f"{GEMINI_BASE}/models", params=params, timeout=15)
            if resp.status_code != 200:
                try:
                    error_msg = resp.json().get("error", {}).get("message", resp.text)
                except ValueError:
                    error_msg = resp.text
                return jsonify({"error": error_msg}), resp.status_code

            data = resp.json()
            all_models.extend(data.get("models", []))

            next_token = data.get("nextPageToken")
            if next_token:
                params["pageToken"] = next_token
            else:
                break

        filtered = []
        for m in all_models:
            if "generateContent" in m.get("supportedGenerationMethods", []):
                model_id = m["name"].removeprefix("models/")
                filtered.append(
                    {
                        "id": model_id,
                        "displayName": m.get("displayName", model_id),
                    }
                )

        return jsonify({"models": filtered})

    except req.exceptions.Timeout:
        return jsonify({"error": "Request to Gemini API timed out"}), 504
    except req.exceptions.ConnectionError:
        return jsonify({"error": "Could not connect to Gemini API"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json()
    if not body:
        return jsonify({"error": "Request body is required"}), 400

    model = body.get("model")
    api_key = body.get("key")
    contents = body.get("contents")

    if not model:
        return jsonify({"error": "model is required"}), 400
    if not api_key:
        return jsonify({"error": "key is required"}), 400
    if not contents:
        return jsonify({"error": "contents is required"}), 400

    try:
        resp = req.post(
            f"{GEMINI_BASE}/models/{model}:generateContent",
            params={"key": api_key},
            json={"contents": contents},
            headers={"Content-Type": "application/json"},
            timeout=120,
        )

        if resp.status_code == 200:
            try:
                data = resp.json()
                if "candidates" in data and data["candidates"]:
                    # extract the latest text
                    prompt_text = contents[-1]["parts"][0]["text"]
                    response_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    
                    interaction = {
                        "prompt": prompt_text,
                        "response": response_text
                    }
                    
                    f = get_fernet(api_key)
                    encrypted = f.encrypt(json.dumps(interaction).encode()).decode()
                    
                    with open(os.path.join(BASE_DIR, "chat_history.log"), "a") as log_file:
                        log_file.write(encrypted + "\n")
            except Exception as e:
                print(f"Error logging chat: {e}")

        return (resp.text, resp.status_code, {"Content-Type": "application/json"})

    except req.exceptions.Timeout:
        return jsonify({"error": "Request to Gemini API timed out"}), 504
    except req.exceptions.ConnectionError:
        return jsonify({"error": "Could not connect to Gemini API"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def main() -> None:
    app.run(host="0.0.0.0", port=5000, debug=True)


if __name__ == "__main__":
    main()
