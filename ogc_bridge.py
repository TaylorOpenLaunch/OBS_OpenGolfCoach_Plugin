"""
Open Golf Coach Bridge Service
==============================
A bridge that:
1. Receives raw launch monitor data on a configurable port (default: 9210)
2. Sends it to Open Golf Coach for processing (port 921)
3. Displays the results in OBS

This handles the full integration flow from launch monitor to OBS display.

Usage:
    python ogc_bridge.py                          # Start bridge
    python ogc_bridge.py --listen-port 9210       # Custom input port
    python ogc_bridge.py --ogc-port 921           # Open Golf Coach port
"""

import socket
import json
import threading
import queue
import time
import argparse
import signal
import sys
from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import obs-websocket library
try:
    import obsws_python as obsws
    HAS_OBSWS = True
except ImportError:
    HAS_OBSWS = False
    logger.warning("obsws-python not installed. Run: pip install obsws-python")

# Try to import opengolfcoach for direct processing
try:
    import opengolfcoach
    HAS_OGC = True
except ImportError:
    HAS_OGC = False
    logger.info("opengolfcoach not installed. Will use TCP client to connect to OGC server.")

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_LISTEN_PORT = 9210  # Port we listen on for launch monitor data
DEFAULT_OGC_HOST = "127.0.0.1"
DEFAULT_OGC_PORT = 921  # Port Open Golf Coach listens on
DEFAULT_OBS_HOST = "localhost"
DEFAULT_OBS_PORT = 4455
SOURCE_PREFIX = "OGC_"

# Data point definitions: (json_path, display_name, format_string, unit)
DATA_POINTS = {
    # Input metrics (Imperial)
    "ball_speed_mph": ("us_customary_units.ball_speed_mph", "Ball Speed", "{:.1f}", "mph"),
    "launch_angle_v": ("vertical_launch_angle_degrees", "Launch Angle", "{:.1f}", "°"),
    "launch_angle_h": ("horizontal_launch_angle_degrees", "Horizontal", "{:.1f}", "°"),
    "total_spin": ("total_spin_rpm", "Total Spin", "{:.0f}", "rpm"),
    "spin_axis": ("spin_axis_degrees", "Spin Axis", "{:.1f}", "°"),

    # Calculated metrics (Imperial)
    "carry_yards": ("open_golf_coach.us_customary_units.carry_distance_yards", "Carry", "{:.1f}", "yds"),
    "total_yards": ("open_golf_coach.us_customary_units.total_distance_yards", "Total", "{:.1f}", "yds"),
    "offline_yards": ("open_golf_coach.us_customary_units.offline_distance_yards", "Offline", "{:+.1f}", "yds"),
    "peak_height_yards": ("open_golf_coach.us_customary_units.peak_height_yards", "Peak Height", "{:.1f}", "yds"),
    "hang_time": ("open_golf_coach.hang_time_seconds", "Hang Time", "{:.2f}", "s"),

    # Spin breakdown
    "backspin": ("open_golf_coach.backspin_rpm", "Backspin", "{:.0f}", "rpm"),
    "sidespin": ("open_golf_coach.sidespin_rpm", "Sidespin", "{:+.0f}", "rpm"),

    # Shot classification
    "shot_name": ("open_golf_coach.shot_name", "Shot Shape", "{}", ""),
    "shot_rank": ("open_golf_coach.shot_rank", "Grade", "{}", ""),
}

# Default enabled sources
DEFAULT_ENABLED = [
    "ball_speed_mph", "launch_angle_v", "total_spin",
    "carry_yards", "total_yards", "offline_yards",
    "peak_height_yards", "hang_time",
    "backspin", "sidespin",
    "shot_name", "shot_rank"
]

# =============================================================================
# Data Processing
# =============================================================================

def get_nested_value(data: dict, path: str) -> Any:
    """Extract a value from nested dict using dot notation path."""
    keys = path.split('.')
    value = data
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value

def format_data_point(key: str, data: dict, show_label: bool = True, show_unit: bool = True) -> Optional[str]:
    """Format a data point for display."""
    if key not in DATA_POINTS:
        return None

    json_path, label, fmt, unit = DATA_POINTS[key]
    value = get_nested_value(data, json_path)

    if value is None:
        return None

    try:
        formatted_value = fmt.format(value)
    except (ValueError, TypeError):
        formatted_value = str(value)

    parts = []
    if show_label:
        parts.append(f"{label}:")
    parts.append(formatted_value)
    if show_unit and unit:
        parts.append(unit)

    return " ".join(parts)

# =============================================================================
# Open Golf Coach Client
# =============================================================================

class OGCClient:
    """Client to communicate with Open Golf Coach server."""

    def __init__(self, host: str = DEFAULT_OGC_HOST, port: int = DEFAULT_OGC_PORT):
        self.host = host
        self.port = port

    def process_shot(self, shot_data: dict) -> Optional[dict]:
        """Send shot data to OGC and get enriched response."""
        # First try local library if available
        if HAS_OGC:
            return self._process_local(shot_data)

        # Fall back to TCP client
        return self._process_tcp(shot_data)

    def _process_local(self, shot_data: dict) -> Optional[dict]:
        """Process shot data using local opengolfcoach library."""
        try:
            result_json = opengolfcoach.calculate_derived_values(json.dumps(shot_data))
            return json.loads(result_json)
        except Exception as e:
            logger.error(f"Local OGC processing failed: {e}")
            return None

    def _process_tcp(self, shot_data: dict) -> Optional[dict]:
        """Send shot data to OGC server via TCP."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5.0)
                sock.connect((self.host, self.port))

                # Send shot data (newline-delimited JSON)
                message = json.dumps(shot_data) + "\n"
                sock.sendall(message.encode('utf-8'))

                # Receive response
                response = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                    if b'\n' in response:
                        break

                if response:
                    return json.loads(response.decode('utf-8').strip())
                return None

        except socket.timeout:
            logger.error(f"Timeout connecting to OGC at {self.host}:{self.port}")
            return None
        except ConnectionRefusedError:
            logger.error(f"Connection refused to OGC at {self.host}:{self.port}")
            return None
        except Exception as e:
            logger.error(f"OGC TCP error: {e}")
            return None

# =============================================================================
# OBS WebSocket Manager
# =============================================================================

class OBSManager:
    """Manages connection to OBS via WebSocket."""

    def __init__(self, host: str = DEFAULT_OBS_HOST, port: int = DEFAULT_OBS_PORT, password: str = ""):
        self.host = host
        self.port = port
        self.password = password
        self.client: Optional[obsws.ReqClient] = None
        self.connected = False
        self.created_sources = set()

    def connect(self) -> bool:
        """Connect to OBS WebSocket."""
        if not HAS_OBSWS:
            logger.error("obsws-python not installed")
            return False

        try:
            self.client = obsws.ReqClient(
                host=self.host,
                port=self.port,
                password=self.password,
                timeout=5
            )
            self.connected = True
            logger.info(f"Connected to OBS at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to OBS: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from OBS."""
        if self.client:
            try:
                self.client.disconnect()
            except:
                pass
            self.client = None
        self.connected = False

    def get_source_name(self, key: str) -> str:
        """Get the OBS source name for a data point key."""
        return f"{SOURCE_PREFIX}{key}"

    def source_exists(self, source_name: str) -> bool:
        """Check if a source exists in OBS."""
        if not self.connected:
            return False
        try:
            self.client.get_input_settings(source_name)
            return True
        except:
            return False

    def create_text_source(self, key: str, initial_text: str = "Waiting...") -> bool:
        """Create a text source in OBS."""
        if not self.connected:
            return False

        source_name = self.get_source_name(key)

        if source_name in self.created_sources:
            return True

        try:
            if self.source_exists(source_name):
                self.created_sources.add(source_name)
                return True

            settings = {
                "text": initial_text,
                "font": {"face": "Arial", "size": 48, "style": "Bold"},
                "color": 0xFFFFFFFF,
                "outline": True,
                "outline_color": 0xFF000000,
                "outline_size": 2
            }

            self.client.create_input(
                sceneName=self._get_current_scene(),
                inputName=source_name,
                inputKind="text_gdiplus_v3",
                inputSettings=settings,
                sceneItemEnabled=True
            )

            self.created_sources.add(source_name)
            logger.info(f"Created source: {source_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create source {source_name}: {e}")
            return False

    def update_text_source(self, key: str, text: str) -> bool:
        """Update the text content of a source."""
        if not self.connected:
            return False

        source_name = self.get_source_name(key)

        try:
            self.client.set_input_settings(
                inputName=source_name,
                inputSettings={"text": text},
                overlay=True
            )
            return True
        except Exception as e:
            if source_name not in self.created_sources:
                if self.create_text_source(key, text):
                    return True
            return False

    def _get_current_scene(self) -> str:
        """Get the current scene name."""
        try:
            response = self.client.get_current_program_scene()
            return response.scene_name
        except:
            return "Scene"

    def create_all_sources(self, enabled_keys: list) -> int:
        """Create all enabled sources."""
        created = 0
        for key in enabled_keys:
            if self.create_text_source(key):
                created += 1
        return created

    def update_all_sources(self, data: dict, enabled_keys: list, show_label: bool = True, show_unit: bool = True):
        """Update all enabled sources with new data."""
        for key in enabled_keys:
            formatted = format_data_point(key, data, show_label, show_unit)
            if formatted:
                self.update_text_source(key, formatted)

# =============================================================================
# Data Listener Server
# =============================================================================

class DataListener:
    """TCP server that receives launch monitor data."""

    def __init__(self, port: int = DEFAULT_LISTEN_PORT, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self.socket: Optional[socket.socket] = None
        self.running = False
        self.data_queue = queue.Queue()
        self.server_thread: Optional[threading.Thread] = None

    def start(self):
        """Start the TCP server."""
        if self.running:
            return

        self.running = True
        self.server_thread = threading.Thread(target=self._server_loop, daemon=True)
        self.server_thread.start()

    def stop(self):
        """Stop the TCP server."""
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        if self.server_thread:
            self.server_thread.join(timeout=2.0)

    def _server_loop(self):
        """Main server loop."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(5)
            self.socket.settimeout(1.0)

            logger.info(f"Listening for launch monitor data on {self.host}:{self.port}")

            while self.running:
                try:
                    client_socket, address = self.socket.accept()
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
            if self.socket:
                self.socket.close()

    def _handle_client(self, client_socket: socket.socket, address):
        """Handle incoming client connection."""
        logger.info(f"Launch monitor connected: {address}")
        buffer = ""

        try:
            while self.running:
                data = client_socket.recv(4096)
                if not data:
                    break

                buffer += data.decode('utf-8')

                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if line:
                        try:
                            json_data = json.loads(line)
                            self.data_queue.put(json_data)
                            logger.debug("Received launch monitor data")
                        except json.JSONDecodeError as e:
                            logger.warning(f"Invalid JSON: {e}")
        except Exception as e:
            logger.warning(f"Client error: {e}")
        finally:
            client_socket.close()
            logger.info(f"Launch monitor disconnected: {address}")

    def get_data(self, timeout: float = 0.1) -> Optional[dict]:
        """Get data from the queue."""
        try:
            return self.data_queue.get(timeout=timeout)
        except queue.Empty:
            return None

# =============================================================================
# Main Bridge Service
# =============================================================================

class OGCBridge:
    """Bridge service that coordinates launch monitor -> OGC -> OBS."""

    def __init__(self, listen_port: int, ogc_host: str, ogc_port: int,
                 obs_host: str, obs_port: int, obs_password: str,
                 enabled_keys: list, show_label: bool = True, show_unit: bool = True):
        self.listener = DataListener(port=listen_port)
        self.ogc_client = OGCClient(host=ogc_host, port=ogc_port)
        self.obs_manager = OBSManager(host=obs_host, port=obs_port, password=obs_password)
        self.enabled_keys = enabled_keys
        self.show_label = show_label
        self.show_unit = show_unit
        self.running = False
        self.last_shot = None

    def start(self):
        """Start the bridge service."""
        self.running = True

        # Connect to OBS
        retry_count = 0
        while self.running and not self.obs_manager.connect():
            retry_count += 1
            if retry_count > 10:
                logger.warning("Could not connect to OBS. Running without OBS output.")
                break
            logger.info("Retrying OBS connection in 5 seconds...")
            time.sleep(5)

        # Create OBS sources
        if self.obs_manager.connected:
            logger.info("Creating OBS sources...")
            created = self.obs_manager.create_all_sources(self.enabled_keys)
            logger.info(f"Created {created} sources")

        # Start data listener
        self.listener.start()

        # Main loop
        logger.info("Bridge running. Press Ctrl+C to stop.")
        try:
            while self.running:
                raw_data = self.listener.get_data(timeout=0.1)
                if raw_data:
                    self._process_shot(raw_data)
        except KeyboardInterrupt:
            pass

        self.stop()

    def _process_shot(self, raw_data: dict):
        """Process a shot through OGC and update OBS."""
        logger.info("Processing shot data...")

        # Check if data already has OGC results
        if 'open_golf_coach' in raw_data:
            enriched_data = raw_data
            logger.info("Data already contains OGC calculations")
        else:
            # Send to Open Golf Coach for processing
            enriched_data = self.ogc_client.process_shot(raw_data)
            if not enriched_data:
                logger.warning("Failed to get OGC response, using raw data")
                enriched_data = raw_data

        self.last_shot = enriched_data

        # Log key metrics
        ball_speed = get_nested_value(enriched_data, "us_customary_units.ball_speed_mph")
        carry = get_nested_value(enriched_data, "open_golf_coach.us_customary_units.carry_distance_yards")
        shot_name = get_nested_value(enriched_data, "open_golf_coach.shot_name")

        if ball_speed and carry:
            logger.info(f"Shot: {ball_speed:.1f} mph, {carry:.1f} yds carry, {shot_name or 'N/A'}")

        # Update OBS
        if self.obs_manager.connected:
            self.obs_manager.update_all_sources(
                enriched_data, self.enabled_keys,
                self.show_label, self.show_unit
            )

    def stop(self):
        """Stop the bridge service."""
        self.running = False
        self.listener.stop()
        self.obs_manager.disconnect()
        logger.info("Bridge stopped")

# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Open Golf Coach Bridge - Launch Monitor to OBS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Architecture:
    Launch Monitor --> Bridge (this) --> Open Golf Coach --> OBS
         |                                    |
         +-- Port 9210 (input)               +-- Port 921

Examples:
    python ogc_bridge.py
    python ogc_bridge.py --listen-port 9210 --ogc-port 921
    python ogc_bridge.py --obs-password mypassword
        """
    )

    parser.add_argument("--listen-port", type=int, default=DEFAULT_LISTEN_PORT,
                        help=f"Port to receive launch monitor data (default: {DEFAULT_LISTEN_PORT})")
    parser.add_argument("--ogc-host", default=DEFAULT_OGC_HOST,
                        help=f"Open Golf Coach host (default: {DEFAULT_OGC_HOST})")
    parser.add_argument("--ogc-port", type=int, default=DEFAULT_OGC_PORT,
                        help=f"Open Golf Coach port (default: {DEFAULT_OGC_PORT})")
    parser.add_argument("--obs-host", default=DEFAULT_OBS_HOST,
                        help=f"OBS WebSocket host (default: {DEFAULT_OBS_HOST})")
    parser.add_argument("--obs-port", type=int, default=DEFAULT_OBS_PORT,
                        help=f"OBS WebSocket port (default: {DEFAULT_OBS_PORT})")
    parser.add_argument("--obs-password", default="",
                        help="OBS WebSocket password (if configured)")
    parser.add_argument("--no-labels", action="store_true",
                        help="Hide data point labels")
    parser.add_argument("--no-units", action="store_true",
                        help="Hide unit suffixes")
    parser.add_argument("--use-local-ogc", action="store_true",
                        help="Use local opengolfcoach library instead of TCP")

    args = parser.parse_args()

    print("""
╔═══════════════════════════════════════════════════════════════╗
║           Open Golf Coach Bridge                              ║
╠═══════════════════════════════════════════════════════════════╣
║  Launch Monitor --> OGC Processing --> OBS Display           ║
╚═══════════════════════════════════════════════════════════════╝
    """)

    print(f"Configuration:")
    print(f"  Listen port (for launch monitor): {args.listen_port}")
    print(f"  Open Golf Coach: {args.ogc_host}:{args.ogc_port}")
    print(f"  OBS WebSocket: {args.obs_host}:{args.obs_port}")
    print(f"  Using local OGC library: {HAS_OGC and args.use_local_ogc}")
    print()

    bridge = OGCBridge(
        listen_port=args.listen_port,
        ogc_host=args.ogc_host,
        ogc_port=args.ogc_port,
        obs_host=args.obs_host,
        obs_port=args.obs_port,
        obs_password=args.obs_password,
        enabled_keys=DEFAULT_ENABLED,
        show_label=not args.no_labels,
        show_unit=not args.no_units
    )

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\nShutting down...")
        bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    bridge.start()

if __name__ == "__main__":
    main()
