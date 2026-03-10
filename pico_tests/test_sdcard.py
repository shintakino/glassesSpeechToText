"""
SD Card Module Test Script
--------------------------
This script tests the MicroSD card module wired to SPI1 on the Pico.
It verifies that the card can be initialized, mounted, written to,
and read from.

Wiring:
-------
SCK  -> GPIO 10
MOSI -> GPIO 11
MISO -> GPIO 12
CS   -> GPIO 13
VCC  -> 3.3V
GND  -> GND

Pre-requisite:
--------------
You must copy `sdcard.py` to your Pico before running this test.
You can find it here: https://github.com/micropython/micropython-lib/blob/master/micropython/drivers/storage/sdcard/sdcard.py
"""

from machine import Pin, SPI, SoftI2C
import os
import time

try:
    import ssd1306
    HAS_OLED = True
except ImportError:
    print("WARNING: ssd1306 module not found. OLED disabled.")
    HAS_OLED = False

# SD Card SPI Pins (SPI1)
SCK_PIN  = 10
MOSI_PIN = 11
MISO_PIN = 12
CS_PIN   = 13

# OLED I2C Pins
SCL_PIN_OLED = 5
SDA_PIN_OLED = 4

TEST_FILE = "/sd/pico_test.txt"

def run_test():
    print("=" * 40)
    print("SD Card Hardware Test")
    print("=" * 40)
    
    oled = None
    if HAS_OLED:
        try:
            i2c = SoftI2C(scl=Pin(SCL_PIN_OLED), sda=Pin(SDA_PIN_OLED), freq=200000)
            if i2c.scan():
                oled = ssd1306.SSD1306_I2C(128, 64, i2c)
                oled.fill(0)
                oled.text("SD Card Test", 0, 0)
                oled.show()
        except Exception as e:
            print(f"OLED Init Error: {e}")

    def update_oled(step, status):
        if oled:
            oled.fill_rect(0, 20, 128, 44, 0) # clear bottom area
            oled.text(step, 0, 20)
            oled.text(status, 0, 40)
            oled.show()

    # 1. Check for the sdcard library
    try:
        import sdcard
        print("[OK] sdcard module found.")
        update_oled("1. sdcard.py", "OK")
    except ImportError:
        print("[FAIL] sdcard module missing!")
        print("Please copy `sdcard.py` to the root of your Pico.")
        update_oled("1. sdcard.py", "FAIL: Missing")
        return

    # 2. Initialize SPI
    print("\nInitializing SPI...")
    try:
        # Note: Some modules might prefer a lower baudrate initially, 
        # but the sdcard module handles that internally.
        spi = SPI(1, sck=Pin(SCK_PIN), mosi=Pin(MOSI_PIN), miso=Pin(MISO_PIN))
        cs = Pin(CS_PIN, Pin.OUT)
        print("[OK] SPI initialized (Pins: SCK=10, MOSI=11, MISO=12, CS=13).")
        update_oled("2. SPI init", "OK")
    except Exception as e:
        print(f"[FAIL] SPI initialization failed: {e}")
        update_oled("2. SPI init", "FAIL")
        return

    # 3. Mount the SD Card
    print("\nMounting SD Card...")
    try:
        sd = sdcard.SDCard(spi, cs)
        vfs = os.VfsFat(sd)
        os.mount(vfs, "/sd")
        print("[OK] SD Card mounted at /sd.")
        update_oled("3. Mount", "OK")
    except OSError as e:
        # If the SD card is already mounted, unmount and remount or ignore
        if e.args[0] == 16:  # EBUSY typically means already mounted
            print("[INFO] SD Card already mounted.")
            update_oled("3. Mount", "OK (already)")
        else:
            print(f"[FAIL] Could not mount SD card: {e}")
            print("Check wiring and ensure the card is formatted as FAT32.")
            update_oled("3. Mount", "FAIL: OSError")
            return
    except Exception as e:
        print(f"[FAIL] Error communicating with SD card: {e}")
        print("Check your wiring to SCK, MOSI, MISO, and CS.")
        update_oled("3. Mount", "FAIL: Comm")
        return

    # 4. Show free space
    try:
        stat = os.statvfs("/sd")
        block_size = stat[0]
        total_blocks = stat[2]
        free_blocks = stat[3]
        total_kb = (total_blocks * block_size) / 1024
        free_kb = (free_blocks * block_size) / 1024
        print(f"[OK] Capacity: {free_kb/1024:.2f} MB free out of {total_kb/1024:.2f} MB total.")
        update_oled("4. Capacity", f"{free_kb/1024:.0f}MB free")
    except Exception as e:
        print(f"[WARN] Could not retrieve filesystem stats: {e}")
        update_oled("4. Capacity", "WARN")

    # 5. Test File Write
    print(f"\nWriting to {TEST_FILE}...")
    try:
        with open(TEST_FILE, "w") as f:
            f.write("Hello from Raspberry Pi Pico!\n")
            f.write(f"Test run at {time.ticks_ms()}ms uptime.\n")
        print("[OK] File written successfully.")
        update_oled("5. Write", "OK")
    except Exception as e:
        print(f"[FAIL] Failed to write file: {e}")
        update_oled("5. Write", "FAIL")
        return

    # 6. Test File Read
    print(f"\nReading back from {TEST_FILE}...")
    try:
        with open(TEST_FILE, "r") as f:
            content = f.read()
            print("--- Content start ---")
            print(content.strip())
            print("--- Content end ---")
        print("[OK] File read successfully.")
        update_oled("6. Read", "OK")
    except Exception as e:
        print(f"[FAIL] Error reading file: {e}")
        update_oled("6. Read", "FAIL")
        return

    # 7. Cleanup
    print("\nCleaning up...")
    try:
        os.remove(TEST_FILE)
        print("[OK] Test file deleted.")
    except Exception as e:
        print(f"[WARN] Could not delete test file: {e}")

    try:
        os.umount("/sd")
        print("[OK] SD Card unmounted safely.")
    except Exception as e:
        print(f"[WARN] Could not unmount SD card: {e}")
        
    update_oled("ALL PASSED!", "SD Card OK")

    print("\n" + "=" * 40)
    print("SD Card Test Passed! 🎉")
    print("=" * 40)

if __name__ == "__main__":
    run_test()
