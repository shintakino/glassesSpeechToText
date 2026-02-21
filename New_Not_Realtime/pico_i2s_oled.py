"""
Push-to-Talk Speech Client for Pico with ESP8285 WiFi
-----------------------------------------------------
Hold the button to record audio, release to send to server.
Server transcribes and sends text back for OLED display.

Protocol (single TCP connection per recording):
  Pico → Server:  [4-byte PCM length (LE)] + [raw PCM bytes]
  Server → Pico:  [4-byte text length (LE)] + [UTF-8 transcript]
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

# Max recording buffer: ~5 seconds at 16kHz 16-bit mono = 160,000 bytes
# Pico W has ~192KB usable RAM, so this is near the limit
MAX_RECORD_BYTES = 160000
READ_CHUNK       = 1600   # 100ms of audio per I2S read (800 samples * 2 bytes)

ESP_MAX_SEND     = 2048
DEBOUNCE_MS      = 200

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
        i2c = SoftI2C(scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=400000)
        oled = ssd1306.SSD1306_I2C(128, 64, i2c)
        oled.fill(0)
        oled.text("OLED Ready", 0, 0)
        oled.show()
    except Exception as e:
        print(f"OLED Init Error: {e}")


def display_status(line1, line2="", line3="", line4=""):
    print(f"Display: {line1} | {line2} | {line3} | {line4}")
    if not oled:
        return
    oled.fill(0)
    oled.text(line1[:16], 0,  0)
    if line2: oled.text(line2[:16], 0, 16)
    if line3: oled.text(line3[:16], 0, 32)
    if line4: oled.text(line4[:16], 0, 48)
    oled.show()


def display_transcript(text):
    print(f"TRANSCRIPT: {text}")
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

    # Show last 8 lines (auto-scroll to bottom)
    visible = lines[-8:] if len(lines) > 8 else lines
    for i, ln in enumerate(visible):
        oled.text(ln, 0, i * 8)
    oled.show()


# ---------------------------------------------------------------
# I2S MICROPHONE
# ---------------------------------------------------------------
audio_in = I2S(
    0,
    sck=Pin(SCK_PIN), ws=Pin(WS_PIN), sd=Pin(SD_PIN),
    mode=I2S.RX,
    bits=BITS_PER_SAMPLE,
    format=I2S.MONO,
    rate=SAMPLE_RATE,
    ibuf=READ_CHUNK * 4,   # DMA buffer
)

# ---------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------
def blink_led(times, delay=0.2):
    for _ in range(times):
        led.on();  time.sleep(delay)
        led.off(); time.sleep(delay)


def _uart_discard_all():
    """Drain UART RX FIFO."""
    time.sleep_ms(30)
    while esp_uart.any():
        esp_uart.read()
        time.sleep_ms(10)


# ---------------------------------------------------------------
# AT COMMAND LAYER
# ---------------------------------------------------------------
def _wait_for_ack(ack, timeout):
    response = ""
    start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk:
                try:
                    response += chunk.decode('utf-8', 'ignore')
                except:
                    pass
                if ack in response:
                    return True, response
                if "ERROR" in response:
                    return False, response
        time.sleep_ms(10)
    return False, response


def _wait_for_prompt(timeout=3000):
    """Wait for '>' after AT+CIPSEND."""
    accumulated = b""
    start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk:
                accumulated += chunk
                if b">" in accumulated:
                    return True
                if b"ERROR" in accumulated or b"link is not valid" in accumulated:
                    return False
        time.sleep_ms(5)
    return False


def _wait_send_ok(timeout=8000):
    """Wait for SEND OK."""
    accumulated = b""
    start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk:
                accumulated += chunk
                if b"SEND OK" in accumulated:
                    return True
                if b"SEND FAIL" in accumulated or b"link is not valid" in accumulated:
                    return False
        time.sleep_ms(5)
    print("_wait_send_ok timeout")
    return False


def esp_send_cmd(cmd, ack="OK", timeout=5000):
    """Send AT command (INIT only)."""
    _uart_discard_all()
    esp_uart.write(cmd + '\r\n')
    return _wait_for_ack(ack, timeout)


def esp_send_data(link_id, data, timeout=8000):
    """Send data over TCP link_id in chunks."""
    offset = 0
    while offset < len(data):
        chunk = data[offset: offset + ESP_MAX_SEND]
        esp_uart.write(f'AT+CIPSEND={link_id},{len(chunk)}\r\n')
        if not _wait_for_prompt(3000):
            print(f"CIPSEND prompt failed")
            return False

        # Write in small bursts
        c_idx = 0
        while c_idx < len(chunk):
            esp_uart.write(chunk[c_idx : c_idx + 64])
            c_idx += 64
            time.sleep_ms(1)

        if not _wait_send_ok(timeout):
            return False
        offset += len(chunk)
    return True


def esp_init():
    display_status("Init ESP8285...")
    esp_uart.write('+++')
    time.sleep_ms(1000)
    _uart_discard_all()

    ok, _ = esp_send_cmd("AT", "OK", 2000)
    if not ok: display_status("ESP8285 Error", "Not responding"); return False

    ok, _ = esp_send_cmd("AT+CWMODE=1", "OK")
    if not ok: display_status("ESP8285 Error", "Mode failed"); return False

    display_status("Connecting WiFi", WIFI_SSID[:16])
    ok, _ = esp_send_cmd(f'AT+CWJAP="{WIFI_SSID}","{WIFI_PASSWORD}"', "OK", 20000)
    if not ok: display_status("WiFi Failed!"); return False

    # Try higher baud rate for faster data transfer
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


def esp_receive_data(link_id, timeout=30000):
    """
    Wait for +IPD response data on link_id.
    Collects all +IPD frames until the connection closes or timeout.
    Returns the combined payload bytes.
    """
    payload = b""
    start = utime.ticks_ms()
    raw_buf = b""

    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk:
                raw_buf += chunk

                # Parse +IPD frames from raw_buf
                while True:
                    idx = raw_buf.find(b"+IPD")
                    if idx < 0:
                        break

                    # Discard anything before +IPD
                    if idx > 0:
                        raw_buf = raw_buf[idx:]

                    colon = raw_buf.find(b":")
                    if colon < 0:
                        break  # Header not complete yet

                    try:
                        hdr = raw_buf[:colon].decode('utf-8', 'ignore')
                        parts = hdr.replace("+IPD,", "").split(",")
                        if len(parts) < 2:
                            raw_buf = raw_buf[4:]
                            continue

                        ipd_link = int(parts[0])
                        data_len = int(parts[1])
                        d_start = colon + 1
                        d_end = d_start + data_len

                        if len(raw_buf) < d_end:
                            break  # Payload not fully arrived

                        ipd_payload = raw_buf[d_start:d_end]
                        raw_buf = raw_buf[d_end:]

                        if ipd_link == link_id:
                            payload += ipd_payload

                    except Exception as e:
                        print(f"IPD parse error: {e}")
                        raw_buf = raw_buf[4:]

                # Check for CLOSED marker (connection closed by server)
                if b"CLOSED" in raw_buf:
                    # Extract any remaining +IPD frames first (already done above)
                    break

        time.sleep_ms(5)

    return payload


# ---------------------------------------------------------------
# SEND RECORDING & GET TRANSCRIPT
# ---------------------------------------------------------------
def send_and_transcribe(pcm_buf, pcm_len):
    """
    Connect to server, send raw PCM, receive transcript.
    Returns transcript string or None on failure.
    """
    link_id = 0

    display_status("Connecting", "to server...")
    if not esp_connect_tcp(link_id, SERVER_IP, SERVER_PORT):
        display_status("Connect", "failed!")
        return None

    time.sleep_ms(200)

    # Send: [4-byte PCM length] + [raw PCM data]
    display_status("Sending...", f"{pcm_len} bytes", f"{pcm_len / (SAMPLE_RATE * 2):.1f}s audio")

    # Send length header
    length_header = struct.pack('<I', pcm_len)
    if not esp_send_data(link_id, length_header):
        print("Failed to send length header")
        esp_close_tcp(link_id)
        return None

    # Send PCM data in chunks (memoryview for efficiency)
    offset = 0
    chunk_size = ESP_MAX_SEND
    total_sent = 0
    while offset < pcm_len:
        end = min(offset + chunk_size, pcm_len)
        chunk = pcm_buf[offset:end]
        if not esp_send_data(link_id, chunk):
            print(f"Failed to send PCM at offset {offset}")
            esp_close_tcp(link_id)
            return None
        total_sent += len(chunk)
        offset = end

    print(f"Sent {total_sent} bytes of PCM data")
    display_status("Waiting for", "transcript...")

    # Receive transcript response
    response = esp_receive_data(link_id, timeout=30000)
    esp_close_tcp(link_id)

    if len(response) < 4:
        print(f"Response too short: {len(response)} bytes")
        return None

    # Parse: [4-byte text length] + [UTF-8 text]
    text_len = struct.unpack('<I', response[:4])[0]
    if len(response) < 4 + text_len:
        print(f"Incomplete response: expected {text_len}, got {len(response) - 4}")
        # Use whatever we have
        transcript = response[4:].decode('utf-8', 'ignore')
    else:
        transcript = response[4:4 + text_len].decode('utf-8', 'ignore')

    return transcript


# ---------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------
def main():
    display_status("Starting...")
    time.sleep_ms(1000)

    if not esp_init():
        display_status("Init failed!", "Check ESP8285")
        while True:
            blink_led(5, 0.1)
            time.sleep(2)

    # Pre-allocate recording buffer
    record_buf = bytearray(MAX_RECORD_BYTES)
    read_buf   = bytearray(READ_CHUNK)

    display_status("Ready!", "Hold button", "to record")
    print("Ready! Hold button to record, release to send.")

    while True:
        try:
            # ---- Wait for button press ----
            if button.value() == 0:
                time.sleep_ms(DEBOUNCE_MS)
                if button.value() != 0:
                    continue  # Debounce: was just a glitch

                # ---- RECORDING ----
                led.on()
                display_status("Recording...", "Speak now")
                print(">>> RECORDING STARTED")

                write_pos = 0
                record_start = utime.ticks_ms()

                # Record while button is held down
                while button.value() == 0:
                    if write_pos >= MAX_RECORD_BYTES:
                        # Buffer full — stop recording
                        display_status("Recording...", "Buffer full!", "Release button")
                        print(">>> Buffer full, waiting for release")
                        while button.value() == 0:
                            time.sleep_ms(50)
                        break

                    n = audio_in.readinto(read_buf)
                    if n > 0:
                        # Copy to record buffer
                        space = MAX_RECORD_BYTES - write_pos
                        copy_n = min(n, space)
                        record_buf[write_pos:write_pos + copy_n] = read_buf[:copy_n]
                        write_pos += copy_n

                led.off()
                record_duration = utime.ticks_diff(utime.ticks_ms(), record_start)
                print(f">>> RECORDING STOPPED: {write_pos} bytes, {record_duration}ms")

                if write_pos < 1600:  # Less than 0.05s — too short
                    display_status("Too short!", "Hold longer", "", "Ready!")
                    time.sleep_ms(1500)
                    display_status("Ready!", "Hold button", "to record")
                    continue

                # ---- SEND & TRANSCRIBE ----
                transcript = send_and_transcribe(record_buf, write_pos)

                if transcript:
                    display_transcript(transcript)
                    print(f">>> TRANSCRIPT: {transcript}")
                    # Keep transcript on screen for a while, then show ready
                    time.sleep(5)
                else:
                    display_status("No response", "from server")
                    time.sleep(2)

                display_status("Ready!", "Hold button", "to record")

            time.sleep_ms(50)  # Poll interval

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Loop error: {e}")
            display_status("Error!", str(e)[:16])
            time.sleep_ms(2000)
            display_status("Ready!", "Hold button", "to record")

    audio_in.deinit()
    led.off()
    display_status("Stopped")


if __name__ == "__main__":
    main()
