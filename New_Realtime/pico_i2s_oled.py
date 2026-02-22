"""
Realtime Streaming Speech Client for Pico with ESP8285 WiFi
------------------------------------------------------------
Hold button to record. Audio streams in chunks to server.
Interim transcripts appear on OLED while speaking.

Protocol (single TCP connection):
  Handshake:    "START\n"
  Audio chunk:  [0x01] [2-byte LE length] [PCM bytes]
  Stop:         [0x02]
  Transcript:   [0x01] text \n  (interim)
                [0x02] text \n  (final)
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

# Small I2S reads to keep DMA drained (~8ms each = 128 samples)
READ_SAMPLES    = 128
READ_BYTES      = READ_SAMPLES * 2   # 256 bytes per read
# Accumulate to SEND_BYTES before sending over TCP (~100ms = 3200 bytes)
SEND_BYTES      = 3200
ESP_MAX_SEND    = 2048
DEBOUNCE_MS     = 200

# Protocol constants
MSG_AUDIO = 0x01
MSG_STOP  = 0x02
TRANSCRIPT_INTERIM = 0x01
TRANSCRIPT_FINAL   = 0x02

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
    ibuf=SEND_BYTES * 8,   # Large DMA buffer (800ms) to survive UART delays
)

# ---------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------
def blink_led(times, delay=0.2):
    for _ in range(times):
        led.on();  time.sleep(delay)
        led.off(); time.sleep(delay)


def _uart_discard_all():
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


def _wait_for_prompt(i2s_buf=None, stage_buf=None, stage_pos_ref=None, timeout=3000):
    """Wait for '>' after AT+CIPSEND. Optionally drain I2S while waiting."""
    accumulated = b""
    start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        # Drain I2S to prevent DMA overflow
        if i2s_buf is not None and stage_buf is not None and stage_pos_ref is not None:
            n = audio_in.readinto(i2s_buf)
            if n > 0 and stage_pos_ref[0] + n <= len(stage_buf):
                stage_buf[stage_pos_ref[0]:stage_pos_ref[0]+n] = i2s_buf[:n]
                stage_pos_ref[0] += n
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk:
                accumulated += chunk
                if b">" in accumulated:
                    return True
                if b"ERROR" in accumulated or b"link is not valid" in accumulated:
                    return False
        time.sleep_ms(2)
    return False


def _wait_send_ok(i2s_buf=None, stage_buf=None, stage_pos_ref=None, timeout=8000):
    """Wait for SEND OK. Returns (success, leftover_bytes). Drains I2S while waiting."""
    accumulated = b""
    start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        # Drain I2S to prevent DMA overflow
        if i2s_buf is not None and stage_buf is not None and stage_pos_ref is not None:
            n = audio_in.readinto(i2s_buf)
            if n > 0 and stage_pos_ref[0] + n <= len(stage_buf):
                stage_buf[stage_pos_ref[0]:stage_pos_ref[0]+n] = i2s_buf[:n]
                stage_pos_ref[0] += n
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk:
                accumulated += chunk
                if b"SEND OK" in accumulated:
                    idx = accumulated.find(b"SEND OK")
                    leftover = accumulated[idx + 7:]
                    return True, leftover
                if b"SEND FAIL" in accumulated or b"link is not valid" in accumulated:
                    return False, b""
        time.sleep_ms(2)
    return False, b""


def esp_send_cmd(cmd, ack="OK", timeout=5000):
    _uart_discard_all()
    esp_uart.write(cmd + '\r\n')
    return _wait_for_ack(ack, timeout)


def esp_send_data_fast(link_id, data, i2s_buf=None, stage_buf=None, stage_pos_ref=None, timeout=8000):
    """
    Send data over TCP. Returns (success, leftover_bytes).
    Optionally drains I2S while waiting for UART responses.
    """
    offset = 0
    all_leftover = b""
    while offset < len(data):
        chunk = data[offset: offset + ESP_MAX_SEND]
        esp_uart.write(f'AT+CIPSEND={link_id},{len(chunk)}\r\n')
        if not _wait_for_prompt(i2s_buf, stage_buf, stage_pos_ref, 3000):
            return False, all_leftover

        # Write in small bursts, polling RX and I2S between bursts
        c_idx = 0
        rx_during = b""
        while c_idx < len(chunk):
            esp_uart.write(chunk[c_idx : c_idx + 64])
            c_idx += 64
            # Drain I2S
            if i2s_buf is not None and stage_buf is not None and stage_pos_ref is not None:
                n = audio_in.readinto(i2s_buf)
                if n > 0 and stage_pos_ref[0] + n <= len(stage_buf):
                    stage_buf[stage_pos_ref[0]:stage_pos_ref[0]+n] = i2s_buf[:n]
                    stage_pos_ref[0] += n
            # Quick RX poll
            if esp_uart.any():
                r = esp_uart.read()
                if r:
                    rx_during += r

        ok, leftover = _wait_send_ok(i2s_buf, stage_buf, stage_pos_ref, timeout)
        all_leftover += rx_during + leftover
        if not ok:
            return False, all_leftover
        offset += len(chunk)
    return True, all_leftover


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


# ---------------------------------------------------------------
# TRANSCRIPT PARSER
# ---------------------------------------------------------------
class TranscriptParser:
    """Parse +IPD frames from UART data to extract transcript messages."""

    def __init__(self, link_id):
        self.link_id = link_id
        self.raw_buf = b""
        self.msg_buf = b""      # Decoded payload waiting for newline
        self.accumulated_text = ""   # All finalized text
        self.current_interim = ""    # Current interim text

    def feed(self, data):
        """Feed raw UART bytes. Call parse() after to get transcript."""
        if data:
            self.raw_buf += data

    def drain_uart(self):
        """Read all pending UART bytes."""
        if esp_uart.any():
            raw = esp_uart.read()
            if raw:
                self.raw_buf += raw

    def parse(self):
        """
        Parse +IPD frames and extract transcript messages.
        Returns display text if updated, else None.
        """
        updated = False

        # Extract +IPD payloads into msg_buf
        while True:
            idx = self.raw_buf.find(b"+IPD")
            if idx < 0:
                break

            if idx > 0:
                self.raw_buf = self.raw_buf[idx:]

            colon = self.raw_buf.find(b":")
            if colon < 0:
                break

            try:
                hdr = self.raw_buf[:colon].decode('utf-8', 'ignore')
                parts = hdr.replace("+IPD,", "").split(",")
                if len(parts) < 2:
                    self.raw_buf = self.raw_buf[4:]
                    continue

                ipd_link = int(parts[0])
                data_len = int(parts[1])
                d_start = colon + 1
                d_end = d_start + data_len

                if len(self.raw_buf) < d_end:
                    break  # Incomplete

                payload = self.raw_buf[d_start:d_end]
                self.raw_buf = self.raw_buf[d_end:]

                if ipd_link == self.link_id:
                    self.msg_buf += payload

            except Exception as e:
                print(f"IPD parse error: {e}")
                self.raw_buf = self.raw_buf[4:]

        # Parse newline-delimited transcript messages from msg_buf
        while True:
            nl = self.msg_buf.find(b'\n')
            if nl < 0:
                break

            line = self.msg_buf[:nl]
            self.msg_buf = self.msg_buf[nl + 1:]

            if len(line) < 2:
                continue

            msg_type = line[0]
            text = line[1:].decode('utf-8', 'ignore').strip()

            if not text:
                continue

            if msg_type == TRANSCRIPT_FINAL:
                self.accumulated_text += text + " "
                self.current_interim = ""
                updated = True
            elif msg_type == TRANSCRIPT_INTERIM:
                self.current_interim = text + "..."
                updated = True

        if updated:
            display_text = (self.accumulated_text + self.current_interim).strip()
            return display_text
        return None

    def reset(self):
        self.raw_buf = b""
        self.msg_buf = b""
        self.accumulated_text = ""
        self.current_interim = ""


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

    link_id = 0
    read_buf = bytearray(READ_BYTES)          # Small I2S read buffer
    stage_buf = bytearray(SEND_BYTES * 4)     # Staging: accumulate audio while sending
    stage_pos = [0]                            # Mutable ref for passing to send functions
    parser = TranscriptParser(link_id)

    display_status("Ready!", "Hold button", "to record")
    print("Ready! Hold button to record.")

    while True:
        try:
            # Wait for button press
            if button.value() == 0:
                time.sleep_ms(DEBOUNCE_MS)
                if button.value() != 0:
                    continue

                # ---- START SESSION ----
                led.on()
                parser.reset()
                stage_pos[0] = 0
                display_status("Connecting...")

                if not esp_connect_tcp(link_id, SERVER_IP, SERVER_PORT):
                    display_status("Connect", "failed!")
                    led.off()
                    time.sleep(2)
                    display_status("Ready!", "Hold button", "to record")
                    continue

                time.sleep_ms(200)

                # Send START handshake
                ok, leftover = esp_send_data_fast(link_id, b"START\n")
                if leftover:
                    parser.feed(leftover)
                if not ok:
                    display_status("Handshake", "failed!")
                    esp_close_tcp(link_id)
                    led.off()
                    time.sleep(2)
                    display_status("Ready!", "Hold button", "to record")
                    continue

                display_status("Recording...", "Speak now")
                print(">>> STREAMING STARTED")

                audio_packets = 0
                last_display_time = 0
                stage_pos[0] = 0

                # ---- STREAMING LOOP (while button held) ----
                while button.value() == 0:
                    # 1. Read small I2S chunk (~8ms) into staging buffer
                    n = audio_in.readinto(read_buf)

                    if n > 0:
                        # Accumulate into staging buffer
                        if stage_pos[0] + n <= len(stage_buf):
                            stage_buf[stage_pos[0]:stage_pos[0]+n] = read_buf[:n]
                            stage_pos[0] += n

                    # 2. When enough audio accumulated, send it
                    if stage_pos[0] >= SEND_BYTES:
                        send_len = stage_pos[0]
                        # Build packet: [0x01][2-byte len][PCM]
                        header = bytes([MSG_AUDIO]) + struct.pack('<H', send_len)
                        packet = header + bytes(stage_buf[:send_len])
                        stage_pos[0] = 0  # Reset staging BEFORE send

                        # 3. Send audio chunk — I2S drains into stage_buf during send
                        ok, leftover = esp_send_data_fast(
                            link_id, packet,
                            read_buf, stage_buf, stage_pos
                        )
                        if leftover:
                            parser.feed(leftover)
                        if not ok:
                            print(">>> SEND FAILED, aborting")
                            break

                        audio_packets += 1
                        if audio_packets <= 3 or audio_packets % 20 == 0:
                            print(f">>> Audio chunk #{audio_packets}: {send_len}B")

                    # 4. Poll UART for transcript (non-blocking)
                    parser.drain_uart()
                    transcript = parser.parse()
                    if transcript:
                        now = utime.ticks_ms()
                        if utime.ticks_diff(now, last_display_time) > 200:
                            display_transcript(transcript)
                            last_display_time = now

                # ---- STOP SESSION ----
                led.off()
                print(f">>> STREAMING STOPPED ({audio_packets} chunks)")

                # Send any remaining staged audio
                if stage_pos[0] > 0:
                    send_len = stage_pos[0]
                    header = bytes([MSG_AUDIO]) + struct.pack('<H', send_len)
                    packet = header + bytes(stage_buf[:send_len])
                    ok, leftover = esp_send_data_fast(link_id, packet)
                    if leftover:
                        parser.feed(leftover)
                    stage_pos[0] = 0

                # Send STOP marker
                ok, leftover = esp_send_data_fast(link_id, bytes([MSG_STOP]))
                if leftover:
                    parser.feed(leftover)

                # Wait for final transcript (poll for up to 3 seconds)
                display_status("Waiting for", "final result...")
                deadline = utime.ticks_add(utime.ticks_ms(), 3000)
                while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
                    parser.drain_uart()
                    transcript = parser.parse()
                    if transcript:
                        display_transcript(transcript)
                    time.sleep_ms(50)

                esp_close_tcp(link_id)

                # Show final transcript for a bit
                final_text = (parser.accumulated_text + parser.current_interim).strip()
                if final_text:
                    display_transcript(final_text)
                    time.sleep(3)
                else:
                    display_status("No speech", "detected")
                    time.sleep(2)

                display_status("Ready!", "Hold button", "to record")

            time.sleep_ms(50)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Loop error: {e}")
            display_status("Error!", str(e)[:16])
            try:
                esp_close_tcp(link_id)
            except:
                pass
            time.sleep_ms(2000)
            display_status("Ready!", "Hold button", "to record")

    audio_in.deinit()
    led.off()
    display_status("Stopped")


if __name__ == "__main__":
    main()
