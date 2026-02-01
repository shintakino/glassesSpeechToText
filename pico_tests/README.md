# Pico Component Tests

This folder contains individual test scripts for each hardware component.
Run these to verify your hardware before running the full speech recognition script.

## Test Order (Recommended)

1. **test_led.py** - Basic board test (LED blink)
2. **test_button.py** - Button input with debounce (GPIO 14)
3. **test_oled.py** - OLED display (I2C)
4. **test_microphone.py** - I2S microphone audio levels
5. **test_wifi.py** - ESP8285 WiFi connection
6. **test_tcp.py** - TCP connection to server

## How to Run

1. Connect your Pico to your computer
2. Open Thonny or another MicroPython IDE
3. Upload the test file to the Pico
4. Run it and check the output

## Pin Configuration

| Component | Pin |
|-----------|-----|
| Button | GPIO 14 |
| OLED SCL | GPIO 1 |
| OLED SDA | GPIO 0 |
| I2S SCK | GPIO 16 |
| I2S WS | GPIO 17 |
| I2S SD | GPIO 18 |
| ESP8285 | UART0 (default) |

## Troubleshooting

- **OLED not found**: Check I2C wiring, run `i2c.scan()` to find address
- **Button not working**: Check if using pull-up or pull-down, wire accordingly
- **Microphone silent**: Check L/R pin connection (GND = left channel)
- **WiFi not responding**: Check UART baud rate (115200), try power cycling
