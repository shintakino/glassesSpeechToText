"""
Push-to-Talk Speech Recognition Server
---------------------------------------
Receives raw PCM audio from Pico W via TCP, saves as WAV file,
transcribes using Google Cloud Speech-to-Text, and sends
the transcript back.

Protocol (single TCP connection per recording):
  Pico → Server:  [4-byte PCM length (LE)] + [raw PCM bytes]
  Server → Pico:  [4-byte text length (LE)] + [UTF-8 transcript]

Audio format: 16kHz, 16-bit, mono (LINEAR16)

Requirements:
  pip install google-cloud-speech

Usage:
  1. Place speech_key.json in same directory (or set GOOGLE_API_KEY env var)
  2. python server_speech_recognition.py
  3. Update Pico code with the displayed IP address
"""

import os
import io
import wave
import socket
import struct
import time
import threading
from datetime import datetime

# ---------------------------------------------------------------
# GOOGLE CLOUD SPEECH SETUP
# ---------------------------------------------------------------
try:
    from google.cloud import speech
    from google.api_core.client_options import ClientOptions
    GOOGLE_IMPORT_SUCCESS = True
except ImportError:
    GOOGLE_IMPORT_SUCCESS = False
    print("WARNING: google-cloud-speech not installed.")
    print("  Install with: pip install google-cloud-speech")

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
cred_path = os.path.join(current_dir, "speech_key.json")
recordings_dir = os.path.join(current_dir, "recordings")

# Create recordings directory
os.makedirs(recordings_dir, exist_ok=True)


def load_env_file():
    """Load API key from .env file (check current dir and parent dir)."""
    for d in [current_dir, parent_dir]:
        env_path = os.path.join(d, ".env")
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    # Support both "KEY=VALUE" and bare "VALUE" (plain API key)
                    if '=' in line:
                        key, _, value = line.partition('=')
                        os.environ.setdefault(key.strip(), value.strip())
                    elif line.startswith('AIza'):
                        # Bare API key (no KEY= prefix)
                        os.environ.setdefault('GOOGLE_API_KEY', line)
            print(f"Loaded .env from: {env_path}")
            return
    print("No .env file found")


load_env_file()

CREDENTIALS_VALID = False
client = None

# Option 1: Service Account (JSON file)
if GOOGLE_IMPORT_SUCCESS and os.path.exists(cred_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
    try:
        client = speech.SpeechClient()
        CREDENTIALS_VALID = True
        print(f"Using service account: {cred_path}")
    except Exception as e:
        print(f"Service account error: {e}")

# Option 2: API Key (from env var or .env file)
if not CREDENTIALS_VALID and GOOGLE_IMPORT_SUCCESS:
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
    if GOOGLE_API_KEY:
        try:
            client_options = ClientOptions(api_key=GOOGLE_API_KEY)
            client = speech.SpeechClient(client_options=client_options)
            CREDENTIALS_VALID = True
            print(f"Using API key: {GOOGLE_API_KEY[:10]}...")
        except Exception as e:
            print(f"API key error: {e}")

if not CREDENTIALS_VALID:
    print("WARNING: No valid credentials. Speech recognition will not work.")
    print("  Place speech_key.json in this directory or set GOOGLE_API_KEY env var.")

# ---------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2       # 16-bit = 2 bytes
NUM_CHANNELS = 1       # mono
HOST = "0.0.0.0"
PORT = 5000

# ---------------------------------------------------------------
# WAV FILE HELPERS
# ---------------------------------------------------------------
def save_wav(pcm_data, filepath):
    """Save raw PCM data as a WAV file."""
    with wave.open(filepath, 'wb') as wf:
        wf.setnchannels(NUM_CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)
    print(f"  Saved WAV: {filepath} ({len(pcm_data)} bytes PCM, "
          f"{len(pcm_data) / (SAMPLE_RATE * SAMPLE_WIDTH * NUM_CHANNELS):.1f}s)")


def pcm_to_wav_bytes(pcm_data):
    """Convert raw PCM data to in-memory WAV bytes (for Google API if needed)."""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(NUM_CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)
    return buf.getvalue()


# ---------------------------------------------------------------
# SPEECH RECOGNITION
# ---------------------------------------------------------------
def transcribe_pcm(pcm_data):
    """Transcribe raw PCM audio using Google Cloud Speech-to-Text (synchronous)."""
    if not CREDENTIALS_VALID or not client:
        return "[No credentials - recognition disabled]"

    if len(pcm_data) < 1600:  # Less than 0.05s of audio
        return "[Audio too short]"

    try:
        # Google recognize() accepts raw LINEAR16 directly — no WAV wrapper needed
        audio = speech.RecognitionAudio(content=pcm_data)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            language_code="en-US",
            enable_automatic_punctuation=True,
        )

        print("  Sending to Google Speech API...")
        response = client.recognize(config=config, audio=audio)

        # Collect all transcripts
        transcript_parts = []
        for result in response.results:
            if result.alternatives:
                transcript_parts.append(result.alternatives[0].transcript)

        if transcript_parts:
            full_transcript = " ".join(transcript_parts)
            print(f"  Transcript: {full_transcript}")
            return full_transcript
        else:
            print("  No speech detected")
            return "[No speech detected]"

    except Exception as e:
        error_msg = f"[Error: {e}]"
        print(f"  Recognition error: {e}")
        return error_msg


# ---------------------------------------------------------------
# RECEIVE HELPERS
# ---------------------------------------------------------------
def recv_exact(sock, n):
    """Receive exactly n bytes from a socket."""
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed while receiving data")
        data += chunk
    return data


# ---------------------------------------------------------------
# CLIENT HANDLER
# ---------------------------------------------------------------
def handle_client(conn, addr):
    """Handle a single recording from the Pico."""
    try:
        print(f"\n{'='*50}")
        print(f"Connection from {addr}")

        # 1. Receive PCM length (4 bytes, little-endian)
        length_bytes = recv_exact(conn, 4)
        pcm_length = struct.unpack('<I', length_bytes)[0]
        print(f"  Expecting {pcm_length} bytes of PCM audio "
              f"({pcm_length / (SAMPLE_RATE * SAMPLE_WIDTH):.1f}s)")

        if pcm_length == 0 or pcm_length > 6000000:  # Sanity check (~60s at 48kHz stereo)
            print(f"  Invalid PCM length: {pcm_length}")
            error_msg = "[Invalid audio length]"
            response = struct.pack('<I', len(error_msg)) + error_msg.encode('utf-8')
            conn.sendall(response)
            return

        # 2. Receive raw PCM data
        print(f"  Receiving audio data...")
        pcm_data = recv_exact(conn, pcm_length)
        print(f"  Received {len(pcm_data)} bytes")

        # 3. Save as WAV file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        wav_filename = f"recording_{timestamp}.wav"
        wav_path = os.path.join(recordings_dir, wav_filename)
        save_wav(pcm_data, wav_path)

        # 4. Transcribe
        transcript = transcribe_pcm(pcm_data)

        # 5. Send transcript back to Pico
        transcript_bytes = transcript.encode('utf-8')
        response = struct.pack('<I', len(transcript_bytes)) + transcript_bytes
        conn.sendall(response)
        print(f"  Sent transcript ({len(transcript_bytes)} bytes): {transcript}")

    except ConnectionError as e:
        print(f"  Connection error: {e}")
    except Exception as e:
        print(f"  Error handling client: {e}")
        try:
            error_msg = f"[Server error]"
            response = struct.pack('<I', len(error_msg)) + error_msg.encode('utf-8')
            conn.sendall(response)
        except:
            pass
    finally:
        conn.close()
        print(f"  Connection closed")


# ---------------------------------------------------------------
# SERVER
# ---------------------------------------------------------------
def start_server():
    """Start the TCP server."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, PORT))
    server_sock.listen(1)

    print(f"\nListening on port {PORT}")
    print("Waiting for Pico to connect...\n")

    while True:
        try:
            conn, addr = server_sock.accept()
            conn.settimeout(30.0)  # 30s timeout for receiving data
            # Handle each connection in a thread (in case of slow transcription)
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
        except Exception as e:
            print(f"Server error: {e}")
            time.sleep(1)


# ---------------------------------------------------------------
# GET LOCAL IP
# ---------------------------------------------------------------
def get_local_ip():
    """Get local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


# ---------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 50)
    print("Push-to-Talk Speech Recognition Server")
    print("=" * 50)

    local_ip = get_local_ip()
    print(f"\nServer IP Address: {local_ip}")
    print(f"Port: {PORT}")
    print(f"Recordings saved to: {recordings_dir}")
    print(f"\nUpdate Pico code with:")
    print(f'  SERVER_IP = "{local_ip}"')
    print(f"  SERVER_PORT = {PORT}")
    print(f"\nPress Ctrl+C to stop\n")

    try:
        start_server()
    except KeyboardInterrupt:
        print("\n\nStopping server...")
        print("Goodbye!")