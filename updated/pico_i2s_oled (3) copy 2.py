"""
Speech Recognition Client for Pico with ESP8285 WiFi
-----------------------------------------------------
Root cause of missing transcripts — definitively identified:

  audio_in.readinto() BLOCKS for ~50ms waiting for the I2S DMA buffer.
  The ESP8285 hardware UART RX FIFO is only 128 bytes.
  During the 50ms block the ESP receives +IPD transcript bytes from the
  server, fills the 128-byte FIFO, then DROPS the rest — silently.
  By the time readinto() returns and check_transcript() runs, the +IPD
  frame is gone.

Fix:
  1. Use I2S readinto() with a small internal buffer and poll it in a
     tight loop using utime so we never block longer than ~5ms at a time.
     This keeps the UART FIFO drained continuously.
  2. Accumulate audio into a staging buffer until we have CHUNK_SAMPLES
     worth of data, then send it.
  3. check_transcript() is called every ~5ms instead of every ~85ms.
"""

from machine import UART, Pin, I2S
import utime
import time
import struct

try:
    from machine import SoftI2C
    _HAS_SOFTI2C = True
except ImportError:
    _HAS_SOFTI2C = False

try:
    import ssd1306
except ImportError:
    ssd1306 = None

# ---------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------
WIFI_SSID     = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
SERVER_IP     = "192.168.1.100"
SERVER_PORT   = 5000

UART_ID   = 0
UART_BAUD = 115200

SCK_PIN    = 16
WS_PIN     = 17
SD_PIN     = 18
SCL_PIN    =  5
SDA_PIN    =  4
BUTTON_PIN = 14

SAMPLE_RATE     = 16000
BITS_PER_SAMPLE = 16

# Audio is accumulated in a staging buffer. We send once we have
# SEND_SAMPLES worth of PCM. At 16kHz, 800 samples = 50ms audio.
# The I2S readinto() polls in READ_SAMPLES chunks — small enough
# that we never block longer than READ_MS milliseconds.
READ_SAMPLES  = 128    # one I2S read = 256 bytes, ~8ms — keeps FIFO drained
SEND_SAMPLES  = 800    # accumulate to 1600 bytes before sending (50ms audio)

ESP_MAX_SEND  = 2048
DEBOUNCE_MS   = 300

# ---------------------------------------------------------------
# HARDWARE
# ---------------------------------------------------------------
try:
    led = Pin("LED", Pin.OUT)
except:
    led = Pin(25, Pin.OUT)

button   = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)
esp_uart = UART(UART_ID, UART_BAUD)

# ---------------------------------------------------------------
# OLED
# ---------------------------------------------------------------
oled = None
if _HAS_SOFTI2C and ssd1306:
    try:
        i2c = SoftI2C(scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=200000)
        oled = ssd1306.SSD1306_I2C(128, 64, i2c)
    except Exception as e:
        print(f"OLED Init Error: {e}")


def display_status(line1, line2="", line3=""):
    print(f"Display: {line1} | {line2} | {line3}")
    if not oled:
        return
    oled.fill(0)
    oled.text(line1[:16], 0,  0)
    if line2: oled.text(line2[:16], 0, 16)
    if line3: oled.text(line3[:16], 0, 32)
    oled.show()


def display_transcript(text):
    print(f">>> TRANSCRIPT: {text}")   # THIS SHOULD PRINT TO TERMINAL
    if not oled:
        return
    oled.fill(0)
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w) if cur else w
        if len(test) <= 16:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    
    print(f"DEBUG OLED LINES: {lines}") # CHECK THIS

    for i, ln in enumerate(lines[:8]):
        oled.text(ln, 0, i * 8)
    oled.show()


# ---------------------------------------------------------------
# I2S  — sized for READ_SAMPLES poll chunks
# ---------------------------------------------------------------
audio_in = I2S(
    0,
    sck=Pin(SCK_PIN), ws=Pin(WS_PIN), sd=Pin(SD_PIN),
    mode=I2S.RX,
    bits=BITS_PER_SAMPLE,
    format=I2S.MONO,
    rate=SAMPLE_RATE,
    ibuf=SEND_SAMPLES * 4 * 4,   # large internal DMA buffer
)

# ---------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------
def blink_led(times, delay=0.2):
    for _ in range(times):
        led.on();  time.sleep(delay)
        led.off(); time.sleep(delay)


def _uart_discard_all():
    """Drain UART RX FIFO. Only safe during init."""
    time.sleep_ms(30)
    while esp_uart.any():
        esp_uart.read()
        time.sleep_ms(10)


def _drain_with_retry(ms=200):
    """Actively drain UART for ms milliseconds — flush stale session bytes."""
    deadline = utime.ticks_add(utime.ticks_ms(), ms)
    while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
        if esp_uart.any():
            esp_uart.read()
        time.sleep_ms(5)


def strip_at_echo(data):
    """
    Strip AT command echo lines from received bytes.
    Lines starting with 'AT', bare 'OK', bare '>' and empty lines are removed.
    +IPD frames and payloads pass through unchanged.
    """
    if b"+IPD" not in data and b"\r\n" not in data:
        return data
    result = b""
    i = 0
    while i < len(data):
        end = data.find(b"\r\n", i)
        if end < 0:
            result += data[i:]
            break
        line = data[i:end]
        if (line.startswith(b"AT") or
                line == b"OK" or
                line == b"" or
                line == b">"):
            i = end + 2
            continue
        result += data[i:end + 2]
        i = end + 2
    return result


# ---------------------------------------------------------------
# AT COMMAND LAYER
# ---------------------------------------------------------------
def _wait_for_ack(ack, timeout):
    """Wait for ack string. Returns (bool, str)."""
    response = ""
    start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk:
                try:
                    response += chunk.decode('utf-8', 'ignore')
                except Exception:
                    pass
                if ack in response:
                    return True, response
                if "ERROR" in response:
                    return False, response
        time.sleep_ms(10)
    return False, response


def _wait_for_prompt(timeout=3000):
    """Wait for '>' after AT+CIPSEND. Returns (found, clean_pre_bytes)."""
    accumulated = b""
    start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk:
                accumulated += chunk
                if b">" in accumulated:
                    # Return EVERYTHING except the prompt, run through strip_at_echo
                    return True, strip_at_echo(accumulated.replace(b">", b""))
                if b"ERROR" in accumulated or b"link is not valid" in accumulated:
                    return False, b""
        time.sleep_ms(5)
    return False, b""


def _wait_send_ok(timeout=8000, pre_buffer=b""):
    """Wait for SEND OK. Returns (success, clean_leftover)."""
    accumulated = pre_buffer
    start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk:
                accumulated += chunk
                for marker in (b"SEND OK", b"SEND FAIL", b"link is not valid"):
                    if marker in accumulated:
                        # Return EVERYTHING except the marker, run through strip_at_echo
                        cleaned = strip_at_echo(accumulated.replace(marker, b""))
                        return marker == b"SEND OK", cleaned
        time.sleep_ms(5)
    print("_wait_send_ok timeout")
    return False, b""


def esp_send_cmd(cmd, ack="OK", timeout=5000):
    """INIT-ONLY: flush then send AT command."""
    _uart_discard_all()
    esp_uart.write(cmd + '\r\n')
    return _wait_for_ack(ack, timeout)


def esp_send_data(link_id, data, timeout=8000):
    """
    Send data over link_id without flushing UART.
    Returns (success, clean_leftover).
    """
    offset   = 0
    leftover = b""
    while offset < len(data):
        chunk = data[offset: offset + ESP_MAX_SEND]
        esp_uart.write(f'AT+CIPSEND={link_id},{len(chunk)}\r\n')
        ok, pre = _wait_for_prompt(3000)
        if pre:
            leftover += pre
        if not ok:
            print(f"CIPSEND prompt failed for link {link_id}")
            return False, leftover
        
        # Chunked write + RX poll
        rx_during_tx = b""
        c_idx = 0
        while c_idx < len(chunk):
            w_size = 64
            esp_uart.write(chunk[c_idx : c_idx + w_size])
            c_idx += w_size
            # Poll RX to prevent FIFO overflow
            while esp_uart.any():
                r = esp_uart.read()
                if r: rx_during_tx += r
        
        ok2, lv = _wait_send_ok(timeout, rx_during_tx)
        if lv:
            leftover += lv
        if not ok2:
            return False, leftover
        offset += len(chunk)
    return True, leftover


def esp_init():
    display_status("Init ESP8285...")
    esp_uart.write('+++')
    time.sleep(1)
    _uart_discard_all()

    ok, _ = esp_send_cmd("AT", "OK", 2000)
    if not ok: display_status("ESP8285 Error", "Not responding"); return False

    ok, _ = esp_send_cmd("AT+CWMODE=1", "OK")
    if not ok: display_status("ESP8285 Error", "Mode failed"); return False

    display_status("Connecting WiFi", WIFI_SSID[:16])
    ok, _ = esp_send_cmd(f'AT+CWJAP="{WIFI_SSID}","{WIFI_PASSWORD}"', "OK", 20000)
    if not ok: display_status("WiFi Failed!"); return False

    display_status("Setting Baud...")
    ok, _ = esp_send_cmd("AT+UART_CUR=921600,8,1,0,0", "OK", 1000)
    if ok:
        time.sleep_ms(150)
        esp_uart.init(921600)
        time.sleep_ms(100)
        _uart_discard_all()
        ok2, _ = esp_send_cmd("AT", "OK", 2000)
        print("Switched to 921600 —", "confirmed OK" if ok2 else "no echo, continuing")
    else:
        print("Baud switch failed — staying 115200")

    ok, _ = esp_send_cmd("AT+CIPMODE=0", "OK", 2000)
    if not ok: display_status("CIPMODE failed"); return False

    ok, _ = esp_send_cmd("AT+CIPMUX=1", "OK", 2000)
    if not ok: display_status("CIPMUX failed"); return False

    display_status("WiFi Connected!")
    blink_led(3, 0.1)
    return True


def esp_connect_tcp(link_id, host, port, timeout=10000):
    esp_uart.write(f'AT+CIPSTART={link_id},"TCP","{host}",{port}\r\n')
    ok, _ = _wait_for_ack("OK", timeout)
    return ok


def esp_close_tcp(link_id):
    esp_uart.write(f'AT+CIPCLOSE={link_id}\r\n')
    _wait_for_ack("OK", 2000)


def esp_check_data():
    """Read UART bytes, strip AT echoes, return clean bytes or None."""
    if esp_uart.any():
        raw = esp_uart.read()
        if raw:
            clean = strip_at_echo(raw)
            return clean if clean else None
    return None


# ---------------------------------------------------------------
# SPEECH CLIENT
# ---------------------------------------------------------------
class SpeechClient:
    def __init__(self):
        self.audio_link      = 0
        self.transcript_link = 1
        self.connected       = False
        self.recv_buffer     = b""
        self.recv_buffer     = b""
        self.transcript_buffer = b""  # [NEW] Buffer for fragmented transcript stream
        self._buf_stale_ms   = None

    def connect(self):
        display_status("Connecting to", "server...")
        _drain_with_retry(200)
        esp_close_tcp(self.audio_link)
        esp_close_tcp(self.transcript_link)
        time.sleep_ms(400)

        if not esp_connect_tcp(self.audio_link, SERVER_IP, SERVER_PORT):
            display_status("Audio connect", "failed!"); return False
        time.sleep_ms(300)
        ok, lv = esp_send_data(self.audio_link, b"AUDIO")
        if lv: self.recv_buffer += lv
        if not ok:
            display_status("Audio init", "failed!"); return False

        time.sleep_ms(500)

        if not esp_connect_tcp(self.transcript_link, SERVER_IP, SERVER_PORT + 1):
            display_status("Transcript", "connect failed!")
            esp_close_tcp(self.audio_link); return False
        time.sleep_ms(300)
        ok, lv = esp_send_data(self.transcript_link, b"TRANSCRIPT")
        if lv: self.recv_buffer += lv
        if not ok:
            display_status("Transcript init", "failed!")
            esp_close_tcp(self.audio_link)
            esp_close_tcp(self.transcript_link); return False

        self.connected     = True
        self.recv_buffer   = b""
        self.transcript_buffer = b""
        self._buf_stale_ms = None
        display_status("Server OK!", "Press button", "to record")
        blink_led(2, 0.1)
        return True

    def disconnect(self):
        esp_close_tcp(self.audio_link)
        esp_close_tcp(self.transcript_link)
        _drain_with_retry(300)
        self.connected     = False
        self.recv_buffer   = b""
        self.transcript_buffer = b""
        self._buf_stale_ms = None

    def send_audio(self, pcm_bytes):
        if not self.connected:
            return False
        packet = struct.pack('<I', len(pcm_bytes)) + bytes(pcm_bytes)
        ok, lv = esp_send_data(self.audio_link, packet)
        if lv:
            self.recv_buffer += lv
        return ok

    def send_stop(self):
        if not self.connected:
            return False
        msg    = b"STOP_RECORDING"
        packet = struct.pack('<I', 0xFFFFFFFF) + struct.pack('<I', len(msg)) + msg
        ok, lv = esp_send_data(self.audio_link, packet)
        if lv:
            self.recv_buffer += lv
        return ok

    def drain_uart_to_buffer(self):
        """
        Read all pending UART bytes into recv_buffer immediately.
        """
        raw = esp_check_data()
        if raw:
            print(f"DEBUG UART: {raw}")  # Uncomment to see ALL raw bytes
            self.recv_buffer += raw

    def check_transcript(self):
        """
        Parse +IPD frames from recv_buffer. Returns transcript string or None.
        drain_uart_to_buffer() should be called before this.
        """
        found_transcript = None

        while True:
            # 1. Extract next +IPD packet
            idx = self.recv_buffer.find(b"+IPD")
            if idx < 0:
                if self.recv_buffer:
                    now = utime.ticks_ms()
                    if self._buf_stale_ms is None:
                        self._buf_stale_ms = now
                    elif utime.ticks_diff(now, self._buf_stale_ms) > 2000:
                        self.recv_buffer   = b""
                        self._buf_stale_ms = None
                else:
                    self._buf_stale_ms = None
                break

            self._buf_stale_ms = None

            if idx > 0:
                self.recv_buffer = self.recv_buffer[idx:]

            colon = self.recv_buffer.find(b":")
            if colon < 0:
                break

            try:
                hdr   = self.recv_buffer[:colon].decode('utf-8', 'ignore')
                parts = hdr.replace("+IPD,", "").split(",")
                if len(parts) < 2:
                    self.recv_buffer = self.recv_buffer[4:]
                    continue

                link_id  = int(parts[0])
                data_len = int(parts[1])
                d_start  = colon + 1
                d_end    = d_start + data_len

                if len(self.recv_buffer) < d_end:
                    break   # payload not yet fully arrived

                payload          = self.recv_buffer[d_start:d_end]
                self.recv_buffer = self.recv_buffer[d_end:]

                # 2. Process payload
                if link_id == self.transcript_link:
                    # Append strictly to transcript buffer
                    # print(f"DEBUG: Found transcript payload: {len(payload)} bytes")
                    # print(f"DEBUG PAYLOAD: {payload!r}")
                    # print(f"DEBUG HEX: {[hex(x) for x in payload]}")
                    self.transcript_buffer += payload
            except Exception as e:
                print(f"IPD parse error: {e}")
                self.recv_buffer = self.recv_buffer[4:]

        # 3. Parse complete messages from transcript_buffer (NEWLINE PROTOCOL)
        latest_text = None
        while True:
            idx = self.transcript_buffer.find(b'\n')
            if idx < 0:
                break
            
            line = self.transcript_buffer[:idx]
            self.transcript_buffer = self.transcript_buffer[idx+1:]
            
            try:
                decoded = line.decode('utf-8', 'ignore').strip()
                if not decoded or decoded == "KEEPALIVE":
                    continue
                latest_text = decoded
            except:
                pass
                
        return latest_text

    def _parse_transcript(self, data):
        if len(data) < 4:
            return None
        length = struct.unpack('<I', data[:4])[0]
        if length == 0:
            return None   # keepalive
        if len(data) >= 4 + length:
            return data[4:4 + length].decode('utf-8', 'ignore')
        return None


# ---------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------
def main():
    is_recording = False

    display_status("Starting...")
    time.sleep(1)

    if not esp_init():
        display_status("Init failed!", "Check ESP8285")
        while True:
            blink_led(5, 0.1)
            time.sleep(2)

    client = SpeechClient()
    while not client.connect():
        display_status("Retrying...", "server conn")
        time.sleep(3)

    # Small I2S read buffer — READ_SAMPLES at a time so we never block long
    read_buf     = bytearray(READ_SAMPLES * 2)
    # Staging buffer — accumulate until SEND_SAMPLES worth collected
    stage_buf    = bytearray(SEND_SAMPLES * 2)
    stage_pos    = 0

    current_transcript = ""
    last_displayed_msg = ""
    button_held     = False
    last_press_time = 0
    audio_packets   = 0
    last_display_time = 0

    print("Ready! Press button to start/stop recording.")

    while True:
        try:
            # ---- Drain UART first — always, every iteration ----
            # This is the critical change: we drain UART at the TOP of every
            # loop, before and after any I2S read, so +IPD bytes accumulate
            # in recv_buffer rather than overflowing the ESP FIFO.
            client.drain_uart_to_buffer()

            # ---- Button (active LOW, debounced) ----
            if button.value() == 0:
                now = utime.ticks_ms()
                if not button_held and utime.ticks_diff(now, last_press_time) > DEBOUNCE_MS:
                    last_press_time = now
                    button_held     = True
                    if is_recording:
                        is_recording = False
                        led.off()
                        stage_pos    = 0   # discard partial staging buffer
                        print(f">>> STOP (sent {audio_packets} packets)")
                        client.send_stop()
                        display_status("Stopped", "Press button", "to record")
                        audio_packets = 0
                    else:
                        is_recording    = True
                        current_transcript = ""
                        last_displayed_msg = ""
                        audio_packets   = 0
                        stage_pos       = 0
                        led.on()
                        display_status("Recording...", "Speak now")
                        print(">>> RECORDING STARTED")
            else:
                button_held = False

            # ---- Non-blocking I2S read ----
            # readinto() with a small buffer returns quickly (< 8ms).
            # We accumulate samples into stage_buf; when full, send to server.
            if is_recording:
                n = audio_in.readinto(read_buf)
                if n > 0:
                    # Drain UART again immediately after I2S read
                    client.drain_uart_to_buffer()

                    # Accumulate into staging buffer
                    space = len(stage_buf) - stage_pos
                    copy  = min(n, space)
                    stage_buf[stage_pos:stage_pos + copy] = read_buf[:copy]
                    stage_pos += copy

                    # When staging buffer is full, send it
                    if stage_pos >= len(stage_buf):
                        audio_packets += 1
                        if audio_packets <= 3 or audio_packets % 20 == 0:
                            print(f">>> AUDIO packet #{audio_packets}: {stage_pos}B PCM")

                        # Drain UART one more time before the blocking CIPSEND
                        client.drain_uart_to_buffer()

                        if not client.send_audio(stage_buf):
                            print(f">>> SEND FAILED at packet #{audio_packets}, reconnecting...")
                            is_recording  = False
                            audio_packets = 0
                            stage_pos     = 0
                            led.off()
                            display_status("Send failed!", "Reconnecting")
                            client.disconnect()
                            while not client.connect():
                                time.sleep(3)

                        stage_pos = 0

            # ---- Transcript check ----
            client.drain_uart_to_buffer()
            transcript = client.check_transcript()
            if transcript:
                current_transcript = transcript
                
            if current_transcript != last_displayed_msg:
                now = utime.ticks_ms()
                # Throttling: Only update OLED every 100ms prevents stalling audio loop
                if utime.ticks_diff(now, last_display_time) > 100:
                    display_transcript(current_transcript)
                    last_displayed_msg = current_transcript
                    last_display_time  = now

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(1)

    client.disconnect()
    audio_in.deinit()
    led.off()
    display_status("Stopped")


if __name__ == "__main__":
    main()
