"""
Test script for Realtime Streaming Speech Recognition Server
-------------------------------------------------------------
Simulates a Pico by sending audio in 50ms chunks with real-time pacing.

Usage:
  python test_server.py                     # Generate test tone
  python test_server.py recording.wav       # Send existing WAV file
"""

import socket
import struct
import sys
import wave
import math
import time
import threading

SERVER_HOST = "192.168.1.101"
SERVER_PORT = 5000
TARGET_RATE = 16000

# Protocol constants
MSG_AUDIO = 0x01
MSG_STOP  = 0x02
TRANSCRIPT_INTERIM = 0x01
TRANSCRIPT_FINAL   = 0x02

CHUNK_SAMPLES = 800   # 50ms at 16kHz
CHUNK_BYTES   = CHUNK_SAMPLES * 2


def generate_test_pcm(duration_s=3.0, freq=440, sample_rate=16000):
    """Generate a sine wave as raw PCM (16-bit mono)."""
    num_samples = int(sample_rate * duration_s)
    pcm = bytearray(num_samples * 2)
    for i in range(num_samples):
        value = int(16000 * math.sin(2 * math.pi * freq * i / sample_rate))
        struct.pack_into('<h', pcm, i * 2, value)
    return bytes(pcm)


def load_wav_as_pcm(filepath):
    """Load a WAV file, resample to 16kHz mono, return raw PCM bytes."""
    import audioop

    with wave.open(filepath, 'rb') as wf:
        channels = wf.getnchannels()
        rate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
        print(f"WAV: {channels}ch, {rate}Hz, {sampwidth*8}-bit, {wf.getnframes()} frames")

    if channels == 2:
        frames = audioop.tomono(frames, sampwidth, 0.5, 0.5)
        print(f"  Converted stereo → mono")

    if rate != TARGET_RATE:
        frames, _ = audioop.ratecv(frames, sampwidth, 1, rate, TARGET_RATE, None)
        print(f"  Resampled {rate}Hz → {TARGET_RATE}Hz")

    if sampwidth != 2:
        frames = audioop.lin2lin(frames, sampwidth, 2)
        print(f"  Converted {sampwidth*8}-bit → 16-bit")

    print(f"  Final: {len(frames)} bytes ({len(frames) / (TARGET_RATE * 2):.1f}s)")
    return frames


def receive_transcripts(sock, stop_event):
    """Background thread to receive and print transcript updates."""
    try:
        while not stop_event.is_set():
            try:
                data = sock.recv(4096)
                if not data:
                    break

                # Parse newline-delimited transcript messages
                for line in data.split(b'\n'):
                    if len(line) < 2:
                        continue
                    msg_type = line[0]
                    text = line[1:].decode('utf-8', 'ignore').strip()
                    if not text:
                        continue

                    if msg_type == TRANSCRIPT_FINAL:
                        print(f"  [FINAL]   {text}")
                    elif msg_type == TRANSCRIPT_INTERIM:
                        print(f"  [interim] {text}")
                    else:
                        print(f"  [?] {line}")

            except socket.timeout:
                continue
            except Exception as e:
                if not stop_event.is_set():
                    print(f"  Receive error: {e}")
                break
    except:
        pass


def stream_to_server(pcm_data):
    """Stream PCM data to server in chunks, simulating real-time Pico behavior."""
    print(f"\nConnecting to {SERVER_HOST}:{SERVER_PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect((SERVER_HOST, SERVER_PORT))

    # Send START handshake
    sock.sendall(b"START\n")
    print("Sent START handshake")
    time.sleep(0.2)

    # Start transcript receiver thread
    stop_event = threading.Event()
    rx_thread = threading.Thread(target=receive_transcripts, args=(sock, stop_event), daemon=True)
    rx_thread.start()

    # Stream audio in chunks with real-time pacing
    offset = 0
    chunk_count = 0
    total_chunks = len(pcm_data) // CHUNK_BYTES + 1
    print(f"Streaming {len(pcm_data)} bytes in ~{total_chunks} chunks...")
    print(f"Transcripts will appear as they arrive:\n")

    start_time = time.time()

    while offset < len(pcm_data):
        chunk = pcm_data[offset:offset + CHUNK_BYTES]
        chunk_len = len(chunk)

        # Build packet: [0x01][2-byte LE length][PCM]
        header = bytes([MSG_AUDIO]) + struct.pack('<H', chunk_len)
        sock.sendall(header + chunk)

        chunk_count += 1
        offset += CHUNK_BYTES

        # Real-time pacing: 50ms per chunk
        elapsed = time.time() - start_time
        expected = chunk_count * 0.05
        if expected > elapsed:
            time.sleep(expected - elapsed)

    # Send STOP
    print(f"\nSent {chunk_count} chunks, sending STOP...")
    sock.sendall(bytes([MSG_STOP]))

    # Wait for final transcripts
    print("Waiting for final transcript...\n")
    time.sleep(3)

    stop_event.set()
    sock.close()
    print("\nDone!")


if __name__ == "__main__":
    print("=" * 50)
    print("Realtime Streaming Server Test")
    print("=" * 50)

    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        print(f"\nLoading: {filepath}")
        pcm_data = load_wav_as_pcm(filepath)
    else:
        print("\nGenerating 3-second test tone (440Hz)...")
        print("(Note: speech recognition may return empty for tones)")
        pcm_data = generate_test_pcm(3.0, 440)

    stream_to_server(pcm_data)
