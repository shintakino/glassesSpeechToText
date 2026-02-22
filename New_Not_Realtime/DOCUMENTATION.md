# Glasses Speech-to-Text System — Technical Documentation

## Abstract

This document describes the design and implementation of a wearable assistive device that performs automatic speech recognition (ASR) and displays the resulting transcript on a heads-up OLED display embedded in eyewear. The system employs a client-server architecture where a resource-constrained microcontroller captures audio, transmits it over WiFi to a backend server, and receives the transcribed text for immediate visual presentation to the user.

## 1. System Architecture

```
┌─────────────────────────────┐         TCP/WiFi         ┌──────────────────────┐
│        PICO CLIENT          │ ◄──────────────────────► │       SERVER         │
│                             │                          │                      │
│  INMP441 ──► I2S ──► PCM   │   [4B len] + [PCM data]  │  Receive PCM         │
│                    ↓        │ ───────────────────────►  │  Save WAV            │
│              RAM / SD Card  │                          │  Google STT API      │
│                    ↓        │   [4B len] + [UTF-8]     │  Return transcript   │
│         ESP8285 ──► TCP     │ ◄───────────────────────  │                      │
│              ↓              │                          └──────────────────────┘
│         SSD1306 OLED        │
└─────────────────────────────┘
```

### 1.1 Client (Embedded)

| Component | Specification |
|---|---|
| MCU | RP2040 (Raspberry Pi Pico), dual-core ARM Cortex-M0+, 133 MHz |
| WiFi | ESP8285, 802.11 b/g/n, AT command interface via UART |
| Microphone | INMP441 MEMS, I2S digital output, SNR 61 dB |
| Display | SSD1306, 128×64 OLED, I2C interface |
| Storage | MicroSD card via SPI (optional, for extended recording) |
| Input | Momentary tactile switch (active-low with internal pull-up) |
| Power | 3.7V LiPo battery, TP4056 charge controller |

### 1.2 Server (Backend)

| Component | Specification |
|---|---|
| Runtime | Python 3.10+ |
| ASR Engine | Google Cloud Speech-to-Text v1 (`recognize()` synchronous method) |
| Audio Storage | WAV files with automatic rotation (max 5 retained) |
| Network | TCP socket server, single-threaded per connection |

## 2. Audio Pipeline

### 2.1 Capture

Audio is sampled via the INMP441 I2S MEMS microphone with the following parameters:

| Parameter | Value |
|---|---|
| Sample Rate | 16,000 Hz |
| Bit Depth | 16-bit signed integer (LINEAR16) |
| Channels | Mono |
| Data Rate | 32,000 bytes/sec |

The RP2040's hardware I2S peripheral reads samples into a DMA-backed internal buffer (`ibuf`), from which the application copies data into either a pre-allocated RAM buffer or an SD card file.

### 2.2 Storage Variants

**RAM Buffer** — Audio is accumulated in a contiguous `bytearray` in SRAM. Maximum recording duration is constrained by available memory (~160 KB free ≈ 5 seconds).

**SD Card** — Audio is written sequentially to a FAT32-formatted MicroSD card via SPI1. This extends the maximum recording duration to 60 seconds, which is the upper limit of the Google Cloud Speech-to-Text synchronous API.

### 2.3 Transmission

The ESP8285 WiFi module operates in AT command mode at 921,600 baud (with fallback to 115,200). Data is transmitted over a single TCP connection using the following binary protocol:

**Request (Pico → Server):**

| Field | Size | Encoding | Description |
|---|---|---|---|
| PCM Length | 4 bytes | uint32, little-endian | Total PCM payload size |
| PCM Data | Variable | Raw LINEAR16 | Audio samples |

**Response (Server → Pico):**

| Field | Size | Encoding | Description |
|---|---|---|---|
| Text Length | 4 bytes | uint32, little-endian | Transcript byte count |
| Transcript | Variable | UTF-8 | Recognized text |

### 2.4 Recognition

The server passes raw PCM data directly to the Google Cloud Speech-to-Text `recognize()` method with `LINEAR16` encoding. This synchronous API is suitable for audio clips under 60 seconds and returns the complete transcript in a single response.

## 3. Operational Flow

```
1. User presses and holds button
2. OLED displays "Recording..."
3. I2S microphone samples audio → RAM or SD card
4. User releases button
5. Pico establishes TCP connection to server
6. PCM data transmitted with length-prefixed protocol
7. Server saves WAV file to disk
8. Server calls Google STT API
9. Transcript returned to Pico
10. OLED displays word-wrapped transcript
11. System returns to idle state
```

## 4. Hardware Interface Summary

| Bus | Peripheral | Pico GPIO |
|---|---|---|
| I2S | INMP441 Microphone | SCK=16, WS=17, SD=18 |
| I2C | SSD1306 OLED | SCL=5, SDA=4 |
| SPI1 | MicroSD Card | SCK=10, MOSI=11, MISO=12, CS=13 |
| UART0 | ESP8285 WiFi | TX=0, RX=1 |
| GPIO | Push Button | GPIO 14 (pull-up, active-low) |

## 5. Constraints and Limitations

| Constraint | Value | Source |
|---|---|---|
| Max recording (RAM) | ~5 seconds | RP2040 SRAM (~160 KB free) |
| Max recording (SD) | 60 seconds | Google `recognize()` API limit |
| UART throughput | ~50–80 KB/s effective | AT command framing overhead |
| Upload time (60s audio) | ~25–30 seconds | UART bottleneck |
| API latency | ~2–8 seconds | Network RTT + Google processing |
| Recording retention | 5 files | Server-side automatic rotation |

## 6. File Structure

```
New_Not_Realtime/
├── server_speech_recognition.py   # TCP server + Google STT
├── pico_i2s_oled.py               # Pico client (RAM buffer, max ~5s)
├── pico_i2s_oled_sdcard.py        # Pico client (SD card, max 60s)
├── test_server.py                 # Server test script (no hardware needed)
└── recordings/                    # Saved WAV files (auto-rotated)
```

## 7. Dependencies

### Pico (MicroPython)

| Library | Purpose |
|---|---|
| `ssd1306` | SSD1306 OLED display driver |
| `sdcard` | MicroSD card SPI driver (SD card variant only) |

### Server (Python 3.10+)

| Package | Purpose |
|---|---|
| `google-cloud-speech` | Google Cloud Speech-to-Text client |
| `google-api-core` | API client options (for API key auth) |
