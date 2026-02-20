"""
WiFi Speech Recognition Server
--------------------------------
Logs what matters:

  >>> AUDIO PACKET #N     — audio received from Pico
  >>> GOOGLE (FINAL)      — final transcript from Google
  >>> GOOGLE (interim)    — partial result
  >>> SENT TO PICO        — transcript sent to Pico
  >>> KEEPALIVE           — keepalive sent
  >>> STOP RECEIVED       — Pico stopped recording

WinError 10053 fix:
  A threading.Event (session_active) is shared between audio_server and
  transcript_server. When audio disconnects, the event is cleared, which
  causes the transcript keepalive loop to exit cleanly rather than keep
  firing on a dead socket.
"""

import os, socket, struct, threading, queue, time, traceback

try:
    from google.cloud import speech
    from google.api_core.client_options import ClientOptions
    GOOGLE_IMPORT_SUCCESS = True
except ImportError:
    GOOGLE_IMPORT_SUCCESS = False
    print("WARNING: google-cloud-speech not installed.")

# ---------------------------------------------------------------
# CREDENTIALS
# ---------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
cred_path   = os.path.join(current_dir, "speech_key.json")

CREDENTIALS_VALID = False
speech_client     = None
streaming_config  = None

if GOOGLE_IMPORT_SUCCESS and os.path.exists(cred_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
    try:
        speech_client     = speech.SpeechClient()
        CREDENTIALS_VALID = True
        print(f"Using service account: {cred_path}")
    except Exception as e:
        print(f"Service account error: {e}")

if GOOGLE_IMPORT_SUCCESS and not CREDENTIALS_VALID:
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "Your-API-Key")
    if GOOGLE_API_KEY and GOOGLE_API_KEY not in ("YOUR_API_KEY_HERE", "Your-API-Key"):
        try:
            speech_client  = speech.SpeechClient(
                client_options=ClientOptions(api_key=GOOGLE_API_KEY))
            CREDENTIALS_VALID = True
            print("Using API key")
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
    print("WARNING: No valid credentials. Recognition disabled.")

# ---------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------
HOST               = "0.0.0.0"
AUDIO_PORT         = 5000
TRANSCRIPT_PORT    = 5001
AUDIO_TIMEOUT_SECS = 5

# ---------------------------------------------------------------
# SHARED STATE
# transcript_queue: recognition thread -> transcript_server thread
# session_active:   set=Pico connected, clear=Pico disconnected
#                   transcript_server watches this to know when to exit
#                   its keepalive loop and wait for the next connection
# ---------------------------------------------------------------
transcript_queue: queue.Queue  = queue.Queue()
session_active:   threading.Event = threading.Event()


# ---------------------------------------------------------------
# RECOGNITION SESSION
# ---------------------------------------------------------------
class RecognitionSession:
    def __init__(self):
        self.audio_queue      = queue.Queue()
        self.is_running       = False
        self._thread          = None
        self._last_audio_time = None
        self._total_bytes     = 0

    def start(self):
        self.is_running       = True
        self._last_audio_time = time.time()
        self._thread          = threading.Thread(target=self._process, daemon=True)
        self._thread.start()

    def stop(self):
        self.is_running = False
        self.audio_queue.put(None)
        print(f"Recognition stopped ({self._total_bytes:,} bytes sent to Google)")

    def add_audio(self, data):
        if self.is_running:
            self._last_audio_time  = time.time()
            self._total_bytes     += len(data)
            self.audio_queue.put(data)

    def _audio_generator(self):
        while self.is_running:
            try:
                data = self.audio_queue.get(timeout=0.1)
                if data is None:
                    return
                yield speech.StreamingRecognizeRequest(audio_content=data)
            except queue.Empty:
                if (self._last_audio_time and
                        time.time() - self._last_audio_time > AUDIO_TIMEOUT_SECS):
                    print(f"No audio for {AUDIO_TIMEOUT_SECS}s — ending session")
                    return

    def _process(self):
        if not CREDENTIALS_VALID or not speech_client:
            transcript_queue.put("[No credentials]")
            return
        try:
            responses = speech_client.streaming_recognize(
                streaming_config, self._audio_generator()
            )
            for response in responses:
                if not self.is_running:
                    break
                if not response.results:
                    continue
                result = response.results[0]
                if not result.alternatives:
                    continue
                text     = result.alternatives[0].transcript
                is_final = result.is_final

                if not text.strip():
                    print(f">>> GOOGLE ({'FINAL' if is_final else 'interim'}): (empty — skipped)")
                    continue

                print(f">>> GOOGLE ({'FINAL' if is_final else 'interim'}): {text!r}")
                out = text if is_final else text + "..."
                transcript_queue.put(out)

            print("Google stream ended")
        except Exception as e:
            print(f"Google error: {e}")
            traceback.print_exc()


# ---------------------------------------------------------------
# PICO HANDLER
# ---------------------------------------------------------------
class PicoHandler:
    def __init__(self):
        self.current_session = None
        self.last_stop_time  = 0
        self.STOP_GRACE      = 0.5
        self._packet_count   = 0

    def handle_audio(self, data):
        if time.time() - self.last_stop_time < self.STOP_GRACE:
            return
        if self.current_session is None or not self.current_session.is_running:
            print("Creating recognition session...")
            self.current_session = RecognitionSession()
            self.current_session.start()
            self._packet_count   = 0
        self._packet_count += 1
        if self._packet_count <= 3 or self._packet_count % 20 == 0:
            print(f">>> AUDIO PACKET #{self._packet_count}: {len(data):,} bytes from Pico")
        self.current_session.add_audio(data)

    def handle_stop(self):
        print(f">>> STOP RECEIVED (session had {self._packet_count} packets)")
        self.last_stop_time = time.time()
        if self.current_session:
            self.current_session.stop()
            self.current_session = None

    def cleanup(self):
        if self.current_session:
            self.current_session.stop()
            self.current_session = None


pico_handler = PicoHandler()


# ---------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------
def recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except socket.timeout:
            return b''
        if not chunk:
            return b''
        buf += chunk
    return buf


# ---------------------------------------------------------------
# AUDIO SERVER
# Controls session_active event so transcript_server knows when
# the Pico is connected vs. disconnected.
# ---------------------------------------------------------------
def audio_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, AUDIO_PORT))
    srv.listen(1)
    print(f"Audio server listening on port {AUDIO_PORT}")

    while True:
        try:
            conn, addr = srv.accept()
            conn.settimeout(15.0)
            try:
                hs = recv_exact(conn, 5)
                if not hs or not hs.startswith(b"AUDIO"):
                    conn.close(); continue

                print(f"Audio client connected from {addr}")

                # Signal transcript_server that the Pico is now connected.
                # This also causes any stale keepalive loop to see the event
                # cleared and exit before we set it again.
                session_active.clear()   # briefly clear to reset transcript loop
                time.sleep(0.05)
                session_active.set()     # now mark as active

                conn.settimeout(10.0)

                while True:
                    try:
                        lb = recv_exact(conn, 4)
                        if not lb:
                            break

                        length = struct.unpack('<I', lb)[0]

                        if length == 0xFFFFFFFF:
                            tlen = struct.unpack('<I', recv_exact(conn, 4))[0]
                            txt  = recv_exact(conn, tlen)
                            if not txt: break
                            msg  = txt.decode('utf-8', 'ignore')
                            if msg == "STOP_RECORDING":
                                pico_handler.handle_stop()
                            continue

                        audio = recv_exact(conn, length)
                        if len(audio) != length:
                            break
                        pico_handler.handle_audio(audio)

                    except socket.timeout:
                        print("Audio stream timeout")
                        break
                    except Exception as e:
                        print(f"Audio receive error: {e}")
                        break

                print(f"Audio client disconnected")
                # Signal transcript_server to stop its keepalive loop
                session_active.clear()
                pico_handler.cleanup()
                conn.close()

            except Exception as e:
                print(f"Audio handshake error: {e}")
                session_active.clear()
                try: conn.close()
                except: pass

        except Exception as e:
            print(f"Audio server error: {e}")
            time.sleep(1)


# ---------------------------------------------------------------
# TRANSCRIPT SERVER
# Sole writer to the transcript socket.
# Watches session_active: when it's cleared, exits the keepalive
# loop cleanly so the socket is closed before WinError can happen.
# ---------------------------------------------------------------
def transcript_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, TRANSCRIPT_PORT))
    srv.listen(1)
    print(f"Transcript server listening on port {TRANSCRIPT_PORT}")

    while True:
        conn = None
        try:
            conn, addr = srv.accept()
            conn.settimeout(15.0)

            hs = recv_exact(conn, 10)
            if not hs or not hs.startswith(b"TRANSCRIPT"):
                conn.close(); continue

            print(f"Transcript client connected from {addr}")
            conn.setblocking(True)

            # Drain stale queue entries
            while not transcript_queue.empty():
                try: transcript_queue.get_nowait()
                except queue.Empty: break

            KEEPALIVE_INTERVAL = 5.0
            last_keepalive     = time.time()

            while True:
                # Exit loop if audio server signalled disconnection
                if not session_active.is_set():
                    print("Transcript: session ended — closing socket cleanly")
                    break

                # Send any queued transcripts
                try:
                    text = transcript_queue.get(timeout=1.0)
                    data = text.encode('utf-8')
                    conn.sendall(data + b'\n')
                    print(f">>> SENT TO PICO: {text!r}")
                except queue.Empty:
                    pass
                except Exception as e:
                    print(f"Transcript send error: {e}")
                    break

                # Keepalive
                if time.time() - last_keepalive >= KEEPALIVE_INTERVAL:
                    try:
                        conn.sendall(b'KEEPALIVE\n')
                        last_keepalive = time.time()
                        print(">>> KEEPALIVE sent to Pico")
                    except Exception as e:
                        print(f"Keepalive error: {e}")
                        break

            print("Transcript client disconnected")
            try: conn.close()
            except: pass

        except Exception as e:
            print(f"Transcript server error: {e}")
            if conn:
                try: conn.close()
                except: pass
            time.sleep(1)


# ---------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except: return "127.0.0.1"


if __name__ == "__main__":
    print("=" * 50)
    print("WiFi Speech Recognition Server")
    print("=" * 50)
    local_ip = get_local_ip()
    print(f"\nServer IP:       {local_ip}")
    print(f"Audio Port:      {AUDIO_PORT}")
    print(f"Transcript Port: {TRANSCRIPT_PORT}")
    print(f'\nSet in Pico: SERVER_IP = "{local_ip}"')
    print("\nWaiting for Pico... Press Ctrl+C to stop\n")

    threading.Thread(target=audio_server,      daemon=True).start()
    threading.Thread(target=transcript_server,  daemon=True).start()

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        pico_handler.cleanup()
        print("Goodbye!")
