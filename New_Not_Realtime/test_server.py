"""
Test script for Push-to-Talk Speech Recognition Server
------------------------------------------------------
Tests the server by sending a sample WAV file or generated tone.

Usage:
  python test_server.py                     # Generate test tone
  python test_server.py recording.wav       # Send existing WAV file
"""

import socket
import struct
import sys
import wave
import math
import io

SERVER_HOST = "192.168.1.101"
SERVER_PORT = 5000
TARGET_RATE = 16000


def generate_test_pcm(duration_s=2.0, freq=440, sample_rate=16000):
    """Generate a sine wave as raw PCM (16-bit mono)."""
    num_samples = int(sample_rate * duration_s)
    pcm = bytearray(num_samples * 2)
    for i in range(num_samples):
        value = int(16000 * math.sin(2 * math.pi * freq * i / sample_rate))
        struct.pack_into('<h', pcm, i * 2, value)
    return bytes(pcm)


def load_wav_as_pcm(filepath):
    """Load a WAV file, resample to 16kHz mono, and return raw PCM bytes."""
    import audioop

    with wave.open(filepath, 'rb') as wf:
        channels = wf.getnchannels()
        rate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
        print(f"WAV: {channels}ch, {rate}Hz, {sampwidth*8}-bit, {wf.getnframes()} frames")

    # Convert stereo to mono
    if channels == 2:
        frames = audioop.tomono(frames, sampwidth, 0.5, 0.5)
        print(f"  Converted stereo → mono")

    # Resample to 16kHz if needed
    if rate != TARGET_RATE:
        frames, _ = audioop.ratecv(frames, sampwidth, 1, rate, TARGET_RATE, None)
        print(f"  Resampled {rate}Hz → {TARGET_RATE}Hz")

    # Convert to 16-bit if needed
    if sampwidth != 2:
        frames = audioop.lin2lin(frames, sampwidth, 2)
        print(f"  Converted {sampwidth*8}-bit → 16-bit")

    print(f"  Final: {len(frames)} bytes ({len(frames) / (TARGET_RATE * 2):.1f}s)")
    return frames


def send_to_server(pcm_data):
    """Send PCM data to server and receive transcript."""
    print(f"\nConnecting to {SERVER_HOST}:{SERVER_PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect((SERVER_HOST, SERVER_PORT))

    # Send: [4-byte length] + [PCM data]
    print(f"Sending {len(pcm_data)} bytes of PCM "
          f"({len(pcm_data) / (16000 * 2):.1f}s audio)...")
    sock.sendall(struct.pack('<I', len(pcm_data)))
    sock.sendall(pcm_data)

    # Receive: [4-byte length] + [UTF-8 text]
    print("Waiting for transcript...")
    length_bytes = sock.recv(4)
    if len(length_bytes) < 4:
        print("ERROR: No response from server")
        sock.close()
        return None

    text_len = struct.unpack('<I', length_bytes)[0]
    text_data = b""
    while len(text_data) < text_len:
        chunk = sock.recv(text_len - len(text_data))
        if not chunk:
            break
        text_data += chunk

    sock.close()
    return text_data.decode('utf-8', 'ignore')


if __name__ == "__main__":
    print("=" * 50)
    print("Push-to-Talk Server Test")
    print("=" * 50)

    if len(sys.argv) > 1:
        # Load WAV file
        filepath = sys.argv[1]
        print(f"\nLoading: {filepath}")
        pcm_data = load_wav_as_pcm(filepath)
    else:
        # Generate test tone
        print("\nGenerating 2-second test tone (440Hz)...")
        print("(Note: speech recognition may return empty for tones)")
        pcm_data = generate_test_pcm(2.0, 440)

    transcript = send_to_server(pcm_data)

    if transcript:
        print(f"\n{'='*50}")
        print(f"TRANSCRIPT: {transcript}")
        print(f"{'='*50}")
    else:
        print("\nERROR: No transcript received")
