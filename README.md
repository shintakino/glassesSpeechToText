# Glasses Speech-to-Text Project

This project implements a wearable speech-to-text system using a Raspberry Pi Pico (with ESP8285 WiFi), an INMP441 I2S microphone, and an OLED display. It captures audio, streams it to a Python server via TCP/WiFi, processes it using Google Cloud Speech-to-Text, and displays the live transcript on the OLED screen.

## Features

- **Real-time Speech Recognition**: Streams audio to a backend server for processing.
- **Visual Feedback**: Displays connection status and live transcripts on a 0.96" OLED.
- **Wireless**: Uses ESP8285 for WiFi connectivity.
- **Battery Powered**: Designed for portability with LiPo battery support.
- **Button Control**: Simple push-button interface to start/stop recording.

## Hardware Requirements

See [schematic.md](schematic.md) for full Bill of Materials and wiring diagram.

- Raspberry Pi Pico (RP2040) + ESP8285 WiFi
- INMP441 I2S Microphone
- ssd1306 0.96" OLED Display
- LiPo Battery & TP4056 Charger
- Push Button & Switch

## Software Setup

### 1. Server Side
The server handles audio processing using Google Cloud Speech-to-Text.

1.  Install dependencies:
    ```bash
    pip install google-cloud-speech websockets asyncio
    ```
2.  Set up Google Cloud credentials:
    - Place your `service_account.json` key in the project root.
    - Set environment variable: `export GOOGLE_APPLICATION_CREDENTIALS="path/to/service_account.json"`
3.  Run the server:
    ```bash
    python server_speech_recognition.py
    ```

### 2. Pico Client
The Pico captures audio and handles the UI.

1.  Flash your Pico with **MicroPython** firmware.
2.  Upload the following files to the Pico:
    - `pico_i2s_oled.py` (Main script)
    - `ssd1306.py` (Display driver)
3.  Configure WiFi in `pico_i2s_oled.py`:
    ```python
    WIFI_SSID = "YOUR_SSID"
    WIFI_PASSWORD = "YOUR_PASSWORD"
    SERVER_IP = "YOUR_SERVER_IP"
    ```
4.  Run `pico_i2s_oled.py`.

## Usage

1.  Power on the device.
2.  Wait for WiFi connection (LED blinks).
3.  Press the **Button** to start recording (OLED shows "Recording...").
4.  Speak into the microphone.
5.  Text will appear on the OLED display.
6.  Press the button again to stop.

## Testing

Use the scripts in `pico_tests/` to verify individual components:
- `test_oled.py`: Check display.
- `test_microphone.py`: Check audio levels.
- `test_streaming.py`: Test full audio pipeline.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
