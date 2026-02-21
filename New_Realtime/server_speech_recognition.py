"""
Realtime Streaming Speech Recognition Server
----------------------------------------------
Single TCP connection per session. Receives audio chunks from Pico,
streams to Google Speech-to-Text, sends interim/final transcripts back.

Protocol (single TCP connection):
  Handshake:    Pico sends "START\n"
  Audio chunk:  [0x01] [2-byte LE length] [PCM bytes]
  Stop:         [0x02]
  Transcript:   [0x01] text \n  (interim)
                [0x02] text \n  (final)

Audio format: 16kHz, 16-bit, mono (LINEAR16)
"""

import os
import io
import wave
import socket
import struct
import time
import threading
import queue
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
                    if '=' in line:
                        key, _, value = line.partition('=')
                        os.environ.setdefault(key.strip(), value.strip())
                    elif line.startswith('AIza'):
                        os.environ.setdefault('GOOGLE_API_KEY', line)
            print(f"Loaded .env from: {env_path}")
            return
    print("No .env file found")


load_env_file()

CREDENTIALS_VALID = False
client = None
streaming_config = None

# Option 1: Service Account (JSON file)
if GOOGLE_IMPORT_SUCCESS and os.path.exists(cred_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
    try:
        client = speech.SpeechClient()
        CREDENTIALS_VALID = True
        print(f"Using service account: {cred_path}")
    except Exception as e:
        print(f"Service account error: {e}")

# Option 2: API Key
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

if CREDENTIALS_VALID and GOOGLE_IMPORT_SUCCESS:
    streaming_config = speech.StreamingRecognitionConfig(
        config=speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="en-US",
            enable_automatic_punctuation=True,
        ),
        interim_results=True,
    )
else:
    print("WARNING: No valid credentials. Speech recognition will not work.")

# ---------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
NUM_CHANNELS = 1
HOST = "0.0.0.0"
PORT = 5000

# Protocol constants
MSG_AUDIO = 0x01
MSG_STOP  = 0x02
TRANSCRIPT_INTERIM = 0x01
TRANSCRIPT_FINAL   = 0x02

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
    duration = len(pcm_data) / (SAMPLE_RATE * SAMPLE_WIDTH * NUM_CHANNELS)
    print(f"  Saved WAV: {filepath} ({len(pcm_data)} bytes, {duration:.1f}s)")


# ---------------------------------------------------------------
# SESSION HANDLER
# ---------------------------------------------------------------
class StreamingSession:
    """Handles one recording session: receives audio, streams to Google, sends transcripts."""

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.audio_queue = queue.Queue()
        self.all_pcm = bytearray()       # Accumulate for WAV saving
        self.is_running = False
        self.send_lock = threading.Lock()  # Protect socket writes

    def run(self):
        """Main session loop."""
        print(f"\n{'='*50}")
        print(f"Session from {self.addr}")

        self.is_running = True

        # Start Google streaming recognition in background thread
        recognition_thread = threading.Thread(target=self._recognition_loop, daemon=True)
        recognition_thread.start()

        try:
            # Receive audio chunks from Pico
            while self.is_running:
                # Read message type byte
                type_byte = self.conn.recv(1)
                if not type_byte:
                    print("  Connection closed by client")
                    break

                msg_type = type_byte[0]

                if msg_type == MSG_AUDIO:
                    # Read 2-byte length
                    len_bytes = self._recv_exact(2)
                    if not len_bytes:
                        break
                    chunk_len = struct.unpack('<H', len_bytes)[0]

                    # Read PCM data
                    pcm_data = self._recv_exact(chunk_len)
                    if not pcm_data:
                        break

                    # Feed to Google and accumulate
                    self.audio_queue.put(pcm_data)
                    self.all_pcm.extend(pcm_data)

                elif msg_type == MSG_STOP:
                    print("  Received STOP from client")
                    break

                else:
                    print(f"  Unknown message type: 0x{msg_type:02x}")

        except socket.timeout:
            print("  Socket timeout")
        except ConnectionError as e:
            print(f"  Connection error: {e}")
        except Exception as e:
            print(f"  Error: {e}")
        finally:
            # Stop recognition
            self.is_running = False
            self.audio_queue.put(None)  # Sentinel to stop generator

            # Wait briefly for final transcript
            time.sleep(1.5)

            # Save WAV
            if self.all_pcm:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                wav_path = os.path.join(recordings_dir, f"recording_{timestamp}.wav")
                save_wav(bytes(self.all_pcm), wav_path)

            self.conn.close()
            print(f"  Session ended ({len(self.all_pcm)} bytes total)")

    def _recv_exact(self, n):
        """Receive exactly n bytes."""
        data = b""
        while len(data) < n:
            chunk = self.conn.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    def send_transcript(self, text, is_final):
        """Send transcript back to Pico over the same TCP connection."""
        prefix = bytes([TRANSCRIPT_FINAL if is_final else TRANSCRIPT_INTERIM])
        payload = prefix + text.encode('utf-8') + b'\n'
        with self.send_lock:
            try:
                self.conn.sendall(payload)
                tag = "FINAL" if is_final else "interim"
                print(f"  → [{tag}] {text}")
            except Exception as e:
                print(f"  Send transcript error: {e}")

    def _audio_generator(self):
        """Generate audio chunks for Google streaming API."""
        while self.is_running:
            try:
                data = self.audio_queue.get(timeout=0.1)
                if data is None:
                    return
                yield speech.StreamingRecognizeRequest(audio_content=data)
            except queue.Empty:
                continue

    def _recognition_loop(self):
        """Background thread: stream audio to Google and send transcripts back."""
        if not CREDENTIALS_VALID or not client or not streaming_config:
            self.send_transcript("[No credentials]", True)
            return

        try:
            print("  Starting Google streaming recognition...")
            responses = client.streaming_recognize(streaming_config, self._audio_generator())

            for response in responses:
                if not self.is_running and not response.results:
                    break

                if not response.results:
                    continue

                result = response.results[0]
                if not result.alternatives:
                    continue

                transcript = result.alternatives[0].transcript
                is_final = result.is_final

                self.send_transcript(transcript, is_final)

            print("  Recognition stream ended")

        except Exception as e:
            print(f"  Recognition error: {e}")


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
    print("Waiting for connections...\n")

    while True:
        try:
            conn, addr = server_sock.accept()
            conn.settimeout(60.0)

            # Wait for START handshake
            try:
                handshake = conn.recv(16)
                if not handshake or not handshake.strip().startswith(b"START"):
                    print(f"Invalid handshake from {addr}: {handshake}")
                    conn.close()
                    continue
            except Exception as e:
                print(f"Handshake error: {e}")
                conn.close()
                continue

            # Handle session in a thread
            session = StreamingSession(conn, addr)
            t = threading.Thread(target=session.run, daemon=True)
            t.start()

        except Exception as e:
            print(f"Server error: {e}")
            time.sleep(1)


# ---------------------------------------------------------------
# GET LOCAL IP
# ---------------------------------------------------------------
def get_local_ip():
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
    print("Realtime Streaming Speech Recognition Server")
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