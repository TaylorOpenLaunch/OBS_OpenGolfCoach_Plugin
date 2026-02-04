"""
Test Sender for OBS Open Golf Coach Plugin
==========================================
Simulates sending golf shot data to the OBS plugin for testing purposes.

Usage:
    python test_sender.py                    # Send single test shot
    python test_sender.py --continuous       # Send shots every 5 seconds
    python test_sender.py --port 921         # Specify custom port
"""

import socket
import json
import argparse
import time
import random

DEFAULT_PORT = 921
DEFAULT_HOST = "127.0.0.1"

def generate_shot_data(use_calculated: bool = True) -> dict:
    """Generate realistic golf shot data."""
    # Randomize input parameters within realistic ranges
    ball_speed_mps = random.uniform(50, 80)  # 112-179 mph
    launch_angle_v = random.uniform(8, 18)
    launch_angle_h = random.uniform(-5, 5)
    total_spin = random.uniform(2000, 4000)
    spin_axis = random.uniform(-20, 20)

    shot_data = {
        "ball_speed_meters_per_second": round(ball_speed_mps, 1),
        "vertical_launch_angle_degrees": round(launch_angle_v, 1),
        "horizontal_launch_angle_degrees": round(launch_angle_h, 1),
        "total_spin_rpm": round(total_spin, 0),
        "spin_axis_degrees": round(spin_axis, 1),
        "us_customary_units": {
            "ball_speed_mph": round(ball_speed_mps * 2.237, 1)
        }
    }

    if use_calculated:
        # Simulate calculated values (in reality, Open Golf Coach calculates these)
        carry = ball_speed_mps * 2.5 + launch_angle_v * 2 - abs(spin_axis) * 0.5
        total = carry * 1.05
        offline = launch_angle_h * 2 + spin_axis * 0.3
        peak_height = launch_angle_v * 2.2
        hang_time = launch_angle_v * 0.5

        # Determine shot shape
        if launch_angle_h < -3:
            direction = "Pull"
        elif launch_angle_h > 3:
            direction = "Push"
        else:
            direction = ""

        if spin_axis < -10:
            shape = "Hook"
        elif spin_axis < -3:
            shape = "Draw"
        elif spin_axis > 10:
            shape = "Slice"
        elif spin_axis > 3:
            shape = "Fade"
        else:
            shape = "Straight"

        shot_name = f"{direction} {shape}".strip() if direction else shape

        # Determine shot rank
        if abs(offline) < 5 and carry > 180:
            rank = "S"
        elif abs(offline) < 10 and carry > 160:
            rank = "A"
        elif abs(offline) < 15:
            rank = "B"
        else:
            rank = "C"

        shot_data["open_golf_coach"] = {
            "carry_distance_meters": round(carry, 1),
            "total_distance_meters": round(total, 1),
            "offline_distance_meters": round(offline, 1),
            "peak_height_meters": round(peak_height, 1),
            "hang_time_seconds": round(hang_time, 2),
            "backspin_rpm": round(total_spin * abs(random.gauss(0.95, 0.05)), 1),
            "sidespin_rpm": round(total_spin * spin_axis / 90, 1),
            "shot_name": shot_name,
            "shot_rank": rank,
            "shot_color_rgb": "0x00B3FF",
            "us_customary_units": {
                "ball_speed_mph": round(ball_speed_mps * 2.237, 1),
                "carry_distance_yards": round(carry * 1.094, 1),
                "total_distance_yards": round(total * 1.094, 1),
                "offline_distance_yards": round(offline * 1.094, 1),
                "peak_height_yards": round(peak_height * 1.094, 1)
            }
        }

    return shot_data

def send_shot(host: str, port: int, shot_data: dict) -> bool:
    """Send shot data to the OBS plugin."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))
            message = json.dumps(shot_data) + "\n"
            sock.sendall(message.encode('utf-8'))
            print(f"Sent shot data:")
            print(f"  Ball Speed: {shot_data['us_customary_units']['ball_speed_mph']:.1f} mph")
            print(f"  Launch Angle: {shot_data['vertical_launch_angle_degrees']:.1f}°")
            if 'open_golf_coach' in shot_data:
                ogc = shot_data['open_golf_coach']
                print(f"  Carry: {ogc['us_customary_units']['carry_distance_yards']:.1f} yds")
                print(f"  Total: {ogc['us_customary_units']['total_distance_yards']:.1f} yds")
                print(f"  Shot: {ogc['shot_name']} ({ogc['shot_rank']})")
            return True
    except ConnectionRefusedError:
        print(f"Error: Could not connect to {host}:{port}")
        print("Make sure OBS is running with the Open Golf Coach plugin loaded.")
        return False
    except Exception as e:
        print(f"Error sending data: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Send test golf shot data to OBS")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Host address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port number (default: {DEFAULT_PORT})")
    parser.add_argument("--continuous", action="store_true", help="Send shots continuously")
    parser.add_argument("--interval", type=float, default=5.0, help="Interval between shots in continuous mode (default: 5s)")
    parser.add_argument("--raw", action="store_true", help="Send only raw input data (no calculated values)")

    args = parser.parse_args()

    print(f"Open Golf Coach Test Sender")
    print(f"Sending to {args.host}:{args.port}")
    print("-" * 40)

    if args.continuous:
        print(f"Continuous mode: sending every {args.interval}s")
        print("Press Ctrl+C to stop")
        print("-" * 40)
        shot_count = 0
        try:
            while True:
                shot_count += 1
                print(f"\nShot #{shot_count}")
                shot_data = generate_shot_data(use_calculated=not args.raw)
                send_shot(args.host, args.port, shot_data)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"\nStopped after {shot_count} shots")
    else:
        shot_data = generate_shot_data(use_calculated=not args.raw)
        send_shot(args.host, args.port, shot_data)

if __name__ == "__main__":
    main()
