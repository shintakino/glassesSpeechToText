"""
Test 3: I2S Microphone
----------------------
Tests the I2S microphone (INMP441 or similar).
Records audio and shows audio levels.
"""

from machine import Pin, I2S
import time
import struct

# PINS - adjust if needed
SCK_PIN = 16   # I2S Serial Clock (BCLK)
WS_PIN = 17    # I2S Word Select (LRCLK/WS)
SD_PIN = 18    # I2S Serial Data (DOUT)

# Audio settings
SAMPLE_RATE = 16000
BITS_PER_SAMPLE = 16
BUFFER_SIZE = 1600  # 100ms at 16kHz

print("I2S Microphone Test")
print(f"Pins: SCK={SCK_PIN}, WS={WS_PIN}, SD={SD_PIN}")
print(f"Sample Rate: {SAMPLE_RATE}Hz, Bits: {BITS_PER_SAMPLE}")
print("-" * 40)

try:
    print("Initializing I2S...")
    audio_in = I2S(
        0,
        sck=Pin(SCK_PIN),
        ws=Pin(WS_PIN),
        sd=Pin(SD_PIN),
        mode=I2S.RX,
        bits=BITS_PER_SAMPLE,
        format=I2S.MONO,
        rate=SAMPLE_RATE,
        ibuf=20000
    )
    print("I2S initialized successfully!")
    
    audio_buffer = bytearray(BUFFER_SIZE * 2)  # 16-bit = 2 bytes per sample
    
    print("\nRecording audio... Speak into the microphone!")
    print("Audio levels (higher = louder):")
    print("-" * 40)
    
    for i in range(50):  # Record for ~5 seconds
        n = audio_in.readinto(audio_buffer)
        
        if n > 0:
            # Calculate RMS (root mean square) for audio level
            samples = struct.unpack('<' + 'h' * (n // 2), audio_buffer[:n])
            sum_sq = sum(s * s for s in samples)
            rms = int((sum_sq / len(samples)) ** 0.5)
            
            # Create visual meter
            meter_len = min(rms // 100, 40)
            meter = '#' * meter_len
            
            print(f"Level: {rms:5d} |{meter}")
        
        time.sleep_ms(100)
    
    audio_in.deinit()
    print("\nMicrophone test complete!")
    
except Exception as e:
    print(f"ERROR: {e}")
    print("\nCheck wiring:")
    print("  INMP441 VDD  -> 3.3V")
    print("  INMP441 GND  -> GND")
    print(f"  INMP441 SCK  -> GPIO {SCK_PIN}")
    print(f"  INMP441 WS   -> GPIO {WS_PIN}")
    print(f"  INMP441 SD   -> GPIO {SD_PIN}")
    print("  INMP441 L/R  -> GND (for left channel)")
