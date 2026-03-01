#!/usr/bin/env python3
"""Poll for a file to appear, with timeout."""
import argparse
import os
import sys
import time


def main():
    parser = argparse.ArgumentParser(description="Wait for a file to appear")
    parser.add_argument("--file", required=True, help="File path to wait for")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout in seconds")
    parser.add_argument("--interval", type=int, default=5, help="Poll interval in seconds")
    args = parser.parse_args()

    elapsed = 0
    while not os.path.exists(args.file) and elapsed < args.timeout:
        time.sleep(args.interval)
        elapsed += args.interval

    if os.path.exists(args.file):
        print(f"Found: {args.file} (after {elapsed}s)")
    else:
        print(f"TIMEOUT after {args.timeout}s — {args.file} not found")
        sys.exit(1)


if __name__ == "__main__":
    main()
