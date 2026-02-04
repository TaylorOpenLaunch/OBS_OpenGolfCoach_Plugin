"""
Test Sender for OBS Open Golf Coach Plugin
==========================================
Simulates launch monitor data for testing the OpenAPI service and OBS plugin.

Usage:
    python test_sender.py                      # Send to OpenAPI service (port 921)
    python test_sender.py --direct             # Send directly to OBS plugin (port 9211)
    python test_sender.py --continuous         # Send shots every 5 seconds
    python test_sender.py --port 921           # Specify custom port
"""

import socket
import json
import argparse
import time
import random

OPENAPI_PORT = 921    # OpenAPI service port
OBS_PORT = 9211       # Direct to OBS plugin port

def generate_openapi_shot() -> dict:
    """Generate shot data in OpenAPI format (what Nova sends)."""
    # Randomize input parameters within realistic ranges
    ball_speed_mph = random.uniform(100, 175)  # mph
    launch_angle_v = random.uniform(8, 18)
    launch_angle_h = random.uniform(-5, 5)
    total_spin = random.uniform(2000, 4000)
    spin_axis = random.uniform(-20, 20)

    return {
        "BallData": {
            "Speed": round(ball_speed_mph, 1),
            "VLA": round(launch_angle_v, 1),
            "HLA": round(launch_angle_h, 1),
            "TotalSpin": round(total_spin, 0),
            "SpinAxis": round(spin_axis, 1)
        },
        "Units": "Yards"
    }

def generate_ogc_shot() -> dict:
    """Generate shot data in OGC format with calculated values."""
    # This simulates what the OpenAPI service would send to OBS
    ball_speed_mps = random.uniform(50, 80)
    launch_angle_v = random.uniform(8, 18)
    launch_angle_h = random.uniform(-5, 5)
    total_spin = random.uniform(2000, 4000)
    spin_axis = random.uniform(-20, 20)

    # Simulate calculated values
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

    # Determine rank
    if abs(offline) < 5 and carry > 180:
        rank = "S"
    elif abs(offline) < 10 and carry > 160:
        rank = "A"
    elif abs(offline) < 15:
        rank = "B"
    else:
        rank = "C"

    return {
        "ball_speed_meters_per_second": round(ball_speed_mps, 1),
        "vertical_launch_angle_degrees": round(launch_angle_v, 1),
        "horizontal_launch_angle_degrees": round(launch_angle_h, 1),
        "total_spin_rpm": round(total_spin, 0),
        "spin_axis_degrees": round(spin_axis, 1),
        "open_golf_coach": {
            "carry_distance_meters": round(carry, 1),
            "total_distance_meters": round(total, 1),
            "offline_distance_meters": round(offline, 1),
            "peak_height_meters": round(peak_height, 1),
            "hang_time_seconds": round(hang_time, 2),
            "backspin_rpm": round(total_spin * 0.95, 1),
            "sidespin_rpm": round(total_spin * spin_axis / 90, 1),
            "shot_name": shot_name,
            "shot_rank": rank,
            "us_customary_units": {
                "ball_speed_mph": round(ball_speed_mps * 2.237, 1),
                "carry_distance_yards": round(carry * 1.094, 1),
                "total_distance_yards": round(total * 1.094, 1),
                "offline_distance_yards": round(offline * 1.094, 1),
                "peak_height_yards": round(peak_height * 1.094, 1)
            }
        }
    }

def send_to_openapi(host: str, port: int, shot_data: dict) -> bool:
    """Send OpenAPI format data (simulating Nova)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5.0)
            sock.connect((host, port))

            # Receive handshake
            handshake = sock.recv(1024).decode('utf-8')
            print(f"Received handshake: {handshake.strip()}")

            # Send shot data
            message = json.dumps(shot_data) + "\n"
            sock.sendall(message.encode('utf-8'))

            ball = shot_data.get("BallData", {})
            print(f"Sent OpenAPI shot:")
            print(f"  Ball Speed: {ball.get('Speed', 'N/A')} mph")
            print(f"  Launch Angle: {ball.get('VLA', 'N/A')}°")
            print(f"  Total Spin: {ball.get('TotalSpin', 'N/A')} rpm")
            return True

    except ConnectionRefusedError:
        print(f"Error: Could not connect to {host}:{port}")
        print("Make sure ogc_openapi_service.py is running.")
        return False
    except socket.timeout:
        print(f"Error: Connection timed out")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def send_to_obs(host: str, port: int, shot_data: dict) -> bool:
    """Send OGC format data directly to OBS plugin."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5.0)
            sock.connect((host, port))

            message = json.dumps(shot_data) + "\n"
            sock.sendall(message.encode('utf-8'))

            ogc = shot_data.get("open_golf_coach", {})
            us = ogc.get("us_customary_units", {})
            print(f"Sent to OBS:")
            print(f"  Ball Speed: {us.get('ball_speed_mph', 'N/A')} mph")
            print(f"  Carry: {us.get('carry_distance_yards', 'N/A')} yds")
            print(f"  Shot: {ogc.get('shot_name', 'N/A')} ({ogc.get('shot_rank', 'N/A')})")
            return True

    except ConnectionRefusedError:
        print(f"Error: Could not connect to {host}:{port}")
        print("Make sure OBS is running with the Open Golf Coach plugin loaded.")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Send test golf shot data")
    parser.add_argument("--host", default="127.0.0.1", help="Host address")
    parser.add_argument("--port", type=int, help="Port number (default depends on mode)")
    parser.add_argument("--direct", action="store_true",
                        help="Send directly to OBS plugin (port 9211) instead of OpenAPI service")
    parser.add_argument("--continuous", action="store_true",
                        help="Send shots continuously")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Interval between shots in continuous mode (default: 5s)")

    args = parser.parse_args()

    # Determine port based on mode
    if args.port:
        port = args.port
    else:
        port = OBS_PORT if args.direct else OPENAPI_PORT

    mode = "direct to OBS" if args.direct else "via OpenAPI service"
    print(f"Open Golf Coach Test Sender")
    print(f"Mode: {mode}")
    print(f"Sending to {args.host}:{port}")
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

                if args.direct:
                    shot_data = generate_ogc_shot()
                    send_to_obs(args.host, port, shot_data)
                else:
                    shot_data = generate_openapi_shot()
                    send_to_openapi(args.host, port, shot_data)

                time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"\nStopped after {shot_count} shots")
    else:
        if args.direct:
            shot_data = generate_ogc_shot()
            send_to_obs(args.host, port, shot_data)
        else:
            shot_data = generate_openapi_shot()
            send_to_openapi(args.host, port, shot_data)

if __name__ == "__main__":
    main()
