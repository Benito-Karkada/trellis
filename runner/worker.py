"""Runner control-plane placeholder.

This process must eventually dispatch each attempt into a fresh sandbox with an
immutable image, no network, strict cgroup limits, and no application secrets.
It deliberately does not execute student code on the application host.
"""
import time

if __name__ == "__main__":
    print("Runner controller ready; sandbox execution is disabled until isolation is configured.", flush=True)
    while True:
        time.sleep(30)
