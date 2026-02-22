# Speed & Performance — Non-Realtime

Estimated timings for the push-to-talk speech recognition implementations.

## Audio Data Rates

| Audio Format | Value |
|---|---|
| Sample Rate | 16,000 Hz |
| Bit Depth | 16-bit (2 bytes) |
| Channels | Mono (1) |
| **Data Rate** | **32,000 bytes/sec** |

## RAM Buffer Version (`pico_i2s_oled.py`)

| Recording Length | Data Size | Upload | Google API | **Total Wait** |
|---|---|---|---|---|
| 1s | 32 KB | ~0.5s | ~1s | ~2s |
| 3s | 96 KB | ~1.5s | ~2s | ~4s |
| **5s (MAX)** | **160 KB** | **~2.5s** | **~2s** | **~5s** |

> ⚠️ **Limited to ~5 seconds** by Pico W RAM (~160KB free)

---

## SD Card Version (`pico_i2s_oled_sdcard.py`)

| Recording Length | Data Size | SD Read | Upload | Google API | **Total Wait** |
|---|---|---|---|---|---|
| 5s | 160 KB | ~0.2s | ~2.5s | ~2s | ~5s |
| 15s | 480 KB | ~0.5s | ~6s | ~3s | ~10s |
| 30s | 960 KB | ~1s | ~12s | ~5s | ~18s |
| **60s (MAX)** | **1.83 MB** | **~2s** | **~25s** | **~8s** | **~35s** |

> ⚠️ **Limited to 60 seconds** by Google `recognize()` sync API

---

## Timeline (5-second recording)

```
RAM Version:
[RECORD 5s][UPLOAD 2.5s][API 2s][✓ text appears]

SD Card Version:
[RECORD 5s][READ+UPLOAD 3s][API 2s][✓ text appears]
```

## Bottlenecks

| Bottleneck | Cause | Impact |
|---|---|---|
| **UART throughput** | AT+CIPSEND overhead limits to ~50-80 KB/s | Slow uploads for large recordings |
| **Google API latency** | Network round-trip + processing | ~1-2s minimum for any recording |
| **Pico RAM** | ~192KB total, ~160KB free | Limits RAM version to ~5s |
| **Google sync API** | 60s max for `recognize()` | Limits SD card version to ~60s |

## Which Version to Use

| Use Case | Best Version |
|---|---|
| Quick commands (< 5s) | **RAM** — simplest, most reliable |
| Longer dictation (< 60s) | **SD Card** — more storage |
| No SD card hardware | **RAM** — works without extra parts |
