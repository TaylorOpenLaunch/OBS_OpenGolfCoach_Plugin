"""
Open Golf Coach OpenAPI Service
===============================
This service acts as a bridge between launch monitors (Nova) and OBS.

It implements the OpenAPI protocol that launch monitors use:
1. Listens on port 921 for launch monitor connections (like Nova)
2. Sends OpenAPI handshake: {"Code":201,"GameId":"OpenGolfCoach"}
3. Receives shot data in OpenAPI format (BallData.Speed, BallData.VLA, etc.)
4. Converts to Open Golf Coach format and calculates derived values
5. Sends processed results to OBS plugin on port 9211

Data Flow:
    Nova (port 921) --> This Service --> opengolfcoach library --> OBS Plugin (port 9211)

Usage:
    python ogc_openapi_service.py
    python ogc_openapi_service.py --openapi-port 921 --obs-port 9211

Requirements:
    pip install opengolfcoach
"""

import socket
import json
import threading
import time
import argparse
import signal
import sys
from typing import Optional, Dict, Any
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import opengolfcoach
try:
    import opengolfcoach
    HAS_OGC = True
    logger.info("opengolfcoach library loaded successfully")
except ImportError:
    HAS_OGC = False
    logger.error("opengolfcoach not installed! Run: pip install opengolfcoach")
    sys.exit(1)

# =============================================================================
# Configuration
# =============================================================================

OPENAPI_PORT = 921           # Port for OpenAPI protocol (Nova connects here)
OBS_PORT = 9211              # Port for sending data to OBS plugin
OPENAPI_HANDSHAKE = '{"Code":201,"GameId":"OpenGolfCoach"}'

# =============================================================================
# OpenAPI to OGC Format Conversion
# =============================================================================

def convert_openapi_to_ogc(openapi_data: dict) -> dict:
    """Convert OpenAPI format (from Nova) to Open Golf Coach format."""
    ogc_input = {}

    # Extract BallData
    ball_data = openapi_data.get("BallData", {})

    # Determine units
    units = openapi_data.get("Units", "Yards")
    is_imperial = "Yards" in units or "MPH" in units

    # Speed -> ball_speed_meters_per_second
    speed = ball_data.get("Speed")
    if speed is not None:
        if is_imperial:
            # Convert mph to m/s
            ogc_input["ball_speed_meters_per_second"] = speed * 0.44704
        else:
            ogc_input["ball_speed_meters_per_second"] = speed

    # VLA -> vertical_launch_angle_degrees
    vla = ball_data.get("VLA")
    if vla is not None:
        ogc_input["vertical_launch_angle_degrees"] = vla

    # HLA -> horizontal_launch_angle_degrees
    hla = ball_data.get("HLA")
    if hla is not None:
        ogc_input["horizontal_launch_angle_degrees"] = hla

    # TotalSpin -> total_spin_rpm
    total_spin = ball_data.get("TotalSpin")
    if total_spin is not None:
        ogc_input["total_spin_rpm"] = total_spin

    # SpinAxis -> spin_axis_degrees
    spin_axis = ball_data.get("SpinAxis")
    if spin_axis is not None:
        ogc_input["spin_axis_degrees"] = spin_axis

    # BackSpin and SideSpin (alternative to TotalSpin + SpinAxis)
    backspin = ball_data.get("BackSpin")
    sidespin = ball_data.get("SideSpin")
    if backspin is not None:
        ogc_input["backspin_rpm"] = backspin
    if sidespin is not None:
        ogc_input["sidespin_rpm"] = sidespin

    return ogc_input

def process_shot(openapi_data: dict) -> Optional[dict]:
    """Process shot data through Open Golf Coach."""
    # Convert OpenAPI format to OGC format
    ogc_input = convert_openapi_to_ogc(openapi_data)

    if not ogc_input:
        logger.warning("No valid ball data found in OpenAPI message")
        return None

    logger.info(f"Processing shot: ball_speed={ogc_input.get('ball_speed_meters_per_second', 'N/A')} m/s")

    try:
        # Process through opengolfcoach library
        result_json = opengolfcoach.calculate_derived_values(json.dumps(ogc_input))
        result = json.loads(result_json)
        return result
    except Exception as e:
        logger.error(f"Error processing shot: {e}")
        return None

# =============================================================================
# OBS Client
# =============================================================================

class OBSClient:
    """Client to send data to OBS plugin."""

    def __init__(self, host: str = "127.0.0.1", port: int = OBS_PORT):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.connected = False

    def connect(self) -> bool:
        """Connect to OBS plugin."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.connected = True
            logger.info(f"Connected to OBS plugin at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.warning(f"Could not connect to OBS plugin: {e}")
            self.connected = False
            return False

    def send(self, data: dict) -> bool:
        """Send data to OBS plugin."""
        if not self.connected:
            if not self.connect():
                return False

        try:
            message = json.dumps(data) + "\n"
            self.socket.sendall(message.encode('utf-8'))
            logger.debug("Sent data to OBS plugin")
            return True
        except Exception as e:
            logger.warning(f"Error sending to OBS: {e}")
            self.connected = False
            self.socket = None
            return False

    def disconnect(self):
        """Disconnect from OBS plugin."""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        self.connected = False

# =============================================================================
# OpenAPI Server
# =============================================================================

class OpenAPIServer:
    """Server that handles OpenAPI protocol from launch monitors."""

    def __init__(self, port: int = OPENAPI_PORT, obs_port: int = OBS_PORT):
        self.port = port
        self.obs_client = OBSClient(port=obs_port)
        self.server_socket: Optional[socket.socket] = None
        self.running = False
        self.last_shot: Optional[dict] = None

    def start(self):
        """Start the OpenAPI server."""
        self.running = True

        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(("0.0.0.0", self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)

            logger.info(f"OpenAPI server listening on port {self.port}")
            logger.info("Waiting for launch monitor connection (e.g., Nova)...")

            while self.running:
                try:
                    client_socket, address = self.server_socket.accept()
                    # Handle client in a new thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket, address),
                        daemon=True
                    )
                    client_thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        logger.warning(f"Accept error: {e}")

        except Exception as e:
            logger.error(f"Server error: {e}")
        finally:
            if self.server_socket:
                self.server_socket.close()
            logger.info("OpenAPI server stopped")

    def stop(self):
        """Stop the server."""
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        self.obs_client.disconnect()

    def _handle_client(self, client_socket: socket.socket, address):
        """Handle OpenAPI client connection."""
        logger.info(f"Launch monitor connected: {address}")

        try:
            # Send OpenAPI handshake
            handshake = OPENAPI_HANDSHAKE + "\n"
            client_socket.sendall(handshake.encode('utf-8'))
            logger.info(f"Sent handshake to {address}")

            # Keep connection alive and process shots
            buffer = ""
            while self.running:
                try:
                    client_socket.settimeout(1.0)
                    data = client_socket.recv(4096)
                except socket.timeout:
                    continue

                if not data:
                    break

                buffer += data.decode('utf-8')

                # Try to parse complete JSON messages
                while buffer:
                    buffer = buffer.strip()
                    if not buffer:
                        break

                    # Try to parse JSON
                    try:
                        openapi_data = json.loads(buffer)
                        buffer = ""  # Successfully parsed, clear buffer

                        logger.info(f"Received data from {address}")
                        logger.debug(f"OpenAPI data: {json.dumps(openapi_data, indent=2)}")

                        # Process the shot
                        result = process_shot(openapi_data)
                        if result:
                            self.last_shot = result

                            # Log key metrics
                            ogc = result.get("open_golf_coach", {})
                            us = ogc.get("us_customary_units", {})
                            logger.info(
                                f"Shot processed: "
                                f"{us.get('ball_speed_mph', 'N/A'):.1f} mph, "
                                f"{us.get('carry_distance_yards', 'N/A'):.1f} yds carry, "
                                f"{ogc.get('shot_name', 'N/A')} ({ogc.get('shot_rank', 'N/A')})"
                            )

                            # Send to OBS
                            if self.obs_client.send(result):
                                logger.info("Sent to OBS plugin")
                            else:
                                logger.warning("Could not send to OBS (is OBS running with the plugin?)")

                    except json.JSONDecodeError:
                        # Not complete yet, try to find newline
                        if '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            if line:
                                try:
                                    openapi_data = json.loads(line)
                                    # Process as above
                                    result = process_shot(openapi_data)
                                    if result:
                                        self.last_shot = result
                                        ogc = result.get("open_golf_coach", {})
                                        us = ogc.get("us_customary_units", {})
                                        logger.info(
                                            f"Shot: {us.get('ball_speed_mph', 0):.1f} mph, "
                                            f"{us.get('carry_distance_yards', 0):.1f} yds, "
                                            f"{ogc.get('shot_name', 'N/A')}"
                                        )
                                        self.obs_client.send(result)
                                except json.JSONDecodeError:
                                    pass
                        else:
                            break  # Wait for more data

        except Exception as e:
            logger.warning(f"Client error: {e}")
        finally:
            client_socket.close()
            logger.info(f"Launch monitor disconnected: {address}")

# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Open Golf Coach OpenAPI Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This service bridges launch monitors (Nova) to OBS.

Data Flow:
    Nova --> OpenAPI Service (port 921) --> opengolfcoach --> OBS Plugin (port 9211)

Usage:
    1. Start this service: python ogc_openapi_service.py
    2. Load OBS script (obs_open_golf_coach.py) in OBS
    3. Click "Create All Sources" in OBS script settings
    4. Connect Nova to localhost:921
    5. Take shots!
        """
    )

    parser.add_argument("--openapi-port", type=int, default=OPENAPI_PORT,
                        help=f"Port for OpenAPI protocol (default: {OPENAPI_PORT})")
    parser.add_argument("--obs-port", type=int, default=OBS_PORT,
                        help=f"Port for OBS plugin (default: {OBS_PORT})")

    args = parser.parse_args()

    print("""
╔═══════════════════════════════════════════════════════════════════╗
║           Open Golf Coach OpenAPI Service                         ║
╠═══════════════════════════════════════════════════════════════════╣
║  Bridges launch monitors (Nova) to OBS display                    ║
╚═══════════════════════════════════════════════════════════════════╝
    """)

    print(f"Configuration:")
    print(f"  OpenAPI Port (for Nova):    {args.openapi_port}")
    print(f"  OBS Plugin Port:            {args.obs_port}")
    print()
    print("Waiting for launch monitor connection...")
    print("Press Ctrl+C to stop")
    print()

    server = OpenAPIServer(port=args.openapi_port, obs_port=args.obs_port)

    # Handle Ctrl+C
    def signal_handler(sig, frame):
        print("\nShutting down...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    server.start()

if __name__ == "__main__":
    main()
