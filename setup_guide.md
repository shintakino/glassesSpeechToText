# Pico Setup Guide — I2S Microphone + OLED + SD Card

Step-by-step setup for the push-to-talk speech recognition system.

## Parts Needed

| Part | Model | Qty |
|---|---|---|
| MCU + WiFi | Pico + ESP8285 board | 1 |
| Microphone | INMP441 (I2S) | 1 |
| Display | SSD1306 OLED 0.96" (I2C) | 1 |
| Storage | MicroSD card module (SPI) | 1 |
| Button | 6x6mm tactile push button | 1 |
| SD Card | MicroSD, FAT32 formatted | 1 |
| Wires | Jumper wires | ~15 |

## Wiring

### INMP441 Microphone (I2S)

| Mic Pin | → Pico |
|---|---|
| SCK | GPIO 16 |
| WS | GPIO 17 |
| SD | GPIO 18 |
| L/R | GND |
| VCC | 3.3V |
| GND | GND |

### SSD1306 OLED Display (I2C)

| OLED Pin | → Pico |
|---|---|
| SCL | GPIO 5 |
| SDA | GPIO 4 |
| VCC | 3.3V |
| GND | GND |

### MicroSD Card Module (SPI1)

| SD Pin | → Pico |
|---|---|
| GND | GND |
| VCC | 3.3V |
| MISO | GPIO 12 |
| MOSI | GPIO 11 |
| SCK | GPIO 10 |
| CS | GPIO 13 |

### Push Button

| Button Pin | → Pico |
|---|---|
| One leg | GPIO 14 |
| Other leg | GND |

## Software Setup

### 1. Install MicroPython

1. Download MicroPython `.uf2` from [micropython.org](https://micropython.org/download/RPI_PICO/)
2. Hold BOOTSEL button, plug in USB
3. Drag `.uf2` file onto the `RPI-RP2` drive

### 2. Copy Required Libraries to Pico

You need two library files on the Pico:

| File | Source | Purpose |
|---|---|---|
| `ssd1306.py` | [micropython-lib](https://github.com/micropython/micropython-lib/blob/master/micropython/drivers/display/ssd1306/ssd1306.py) | OLED driver |
| `sdcard.py` | [micropython-lib](https://github.com/micropython/micropython-lib/blob/master/micropython/drivers/storage/sdcard/sdcard.py) | SD card driver |

Copy both files to the root of the Pico filesystem using Thonny or `mpremote`:

```bash
mpremote cp ssd1306.py :ssd1306.py
mpremote cp sdcard.py :sdcard.py
```

### 3. Format the SD Card

- Insert SD card into your PC
- Format as **FAT32** (not exFAT)
- Cards up to 32GB work best

### 4. Configure the Pico Script

Open `pico_i2s_oled_sdcard.py` and update:

```python
WIFI_SSID     = "YourWiFiName"
WIFI_PASSWORD = "YourWiFiPassword"
SERVER_IP     = "192.168.1.100"   # Your PC's IP (shown when server starts)
SERVER_PORT   = 5000
```

### 5. Upload to Pico

```bash
mpremote cp pico_i2s_oled_sdcard.py :main.py
```

> Naming it `main.py` makes it auto-run on boot.

## Server Setup (on your PC)

### 1. Install Python Dependencies

```bash
pip install google-cloud-speech
```

### 2. Set Up Google Credentials

**Option A** — Service Account (recommended):
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable **Cloud Speech-to-Text API**
3. Create Service Account → download JSON key
4. Rename to `speech_key.json`, place in `New_Not_Realtime/`

**Option B** — API Key:
1. Create API key in Google Cloud Console
2. Add to `.env` file: `GOOGLE_API_KEY=AIza...`

### 3. Start the Server

```bash
cd New_Not_Realtime
python server_speech_recognition.py
```

The server will display its IP address — use this for `SERVER_IP` in the Pico code.

## Usage

1. Power on the Pico
2. Wait for "Ready!" on OLED
3. **Hold the button** and speak (up to 60 seconds)
4. **Release the button** — recording sends to server
5. Transcript appears on OLED

## Troubleshooting

| Issue | Fix |
|---|---|
| "SD Card failed!" on OLED | Check wiring (SCK=10, MOSI=11, MISO=12, CS=13). Ensure FAT32 format. |
| "ESP8285 Not responding" | Check UART connection. Try power cycling. |
| "WiFi Failed!" | Verify SSID/password. Move closer to router. |
| "Connect failed!" | Check SERVER_IP matches your PC. Ensure server is running. |
| No sound / empty transcript | Check INMP441 L/R pin is connected to GND. |
| OLED blank | Check I2C wiring (SDA=4, SCL=5). Try swapping SDA/SCL. |
| `sdcard` import error | Copy `sdcard.py` to Pico root filesystem. |
