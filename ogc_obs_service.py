"""
Open Golf Coach OBS Service (Standalone)
========================================
A standalone Windows service that:
1. Listens for golf shot data on a TCP port
2. Connects to OBS via obs-websocket (built into OBS 28+)
3. Creates and updates text sources for each data point

This is an alternative to the OBS script - it runs as a separate process
and is more robust for production use.

Requirements:
    pip install obsws-python

Usage:
    python ogc_obs_service.py                    # Start service
    python ogc_obs_service.py --port 921         # Custom data port
    python ogc_obs_service.py --obs-port 4455    # Custom OBS WebSocket port
"""

import socket
import json
import threading
import queue
import time
import argparse
import signal
import sys
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable
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

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_DATA_PORT = 921
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

    # Metric alternatives
    "ball_speed_mps": ("ball_speed_meters_per_second", "Ball Speed", "{:.1f}", "m/s"),
    "carry_meters": ("open_golf_coach.carry_distance_meters", "Carry", "{:.1f}", "m"),
    "total_meters": ("open_golf_coach.total_distance_meters", "Total", "{:.1f}", "m"),
    "offline_meters": ("open_golf_coach.offline_distance_meters", "Offline", "{:+.1f}", "m"),
    "peak_height_meters": ("open_golf_coach.peak_height_meters", "Peak Height", "{:.1f}", "m"),
}

# Default enabled sources (Imperial preferred)
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
        logger.info("Disconnected from OBS")

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
            # Check if source already exists
            if self.source_exists(source_name):
                self.created_sources.add(source_name)
                logger.info(f"Source already exists: {source_name}")
                return True

            # Create new text source (GDI+ on Windows)
            settings = {
                "text": initial_text,
                "font": {
                    "face": "Arial",
                    "size": 48,
                    "style": "Bold"
                },
                "color": 0xFFFFFFFF,  # White
                "outline": True,
                "outline_color": 0xFF000000,  # Black outline
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
            # Source might not exist yet
            if source_name not in self.created_sources:
                if self.create_text_source(key, text):
                    return True
            logger.debug(f"Failed to update source {source_name}: {e}")
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
# TCP Server
# =============================================================================

class DataServer:
    """TCP server that receives golf shot data."""

    def __init__(self, port: int = DEFAULT_DATA_PORT, host: str = "0.0.0.0"):
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

            logger.info(f"Data server listening on {self.host}:{self.port}")

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
            logger.info("Data server stopped")

    def _handle_client(self, client_socket: socket.socket, address):
        """Handle incoming client connection."""
        logger.info(f"Client connected: {address}")
        buffer = ""

        try:
            while self.running:
                data = client_socket.recv(4096)
                if not data:
                    break

                buffer += data.decode('utf-8')

                # Process complete JSON messages (newline-delimited)
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if line:
                        try:
                            json_data = json.loads(line)
                            self.data_queue.put(json_data)
                            logger.debug("Received shot data")
                        except json.JSONDecodeError as e:
                            logger.warning(f"Invalid JSON: {e}")
        except Exception as e:
            logger.warning(f"Client error: {e}")
        finally:
            client_socket.close()
            logger.info(f"Client disconnected: {address}")

    def get_data(self, timeout: float = 0.1) -> Optional[dict]:
        """Get data from the queue."""
        try:
            return self.data_queue.get(timeout=timeout)
        except queue.Empty:
            return None

# =============================================================================
# Main Service
# =============================================================================

class OGCService:
    """Main service that coordinates data server and OBS updates."""

    def __init__(self, data_port: int, obs_host: str, obs_port: int, obs_password: str,
                 enabled_keys: list, show_label: bool = True, show_unit: bool = True):
        self.data_server = DataServer(port=data_port)
        self.obs_manager = OBSManager(host=obs_host, port=obs_port, password=obs_password)
        self.enabled_keys = enabled_keys
        self.show_label = show_label
        self.show_unit = show_unit
        self.running = False

    def start(self):
        """Start the service."""
        self.running = True

        # Connect to OBS
        while self.running and not self.obs_manager.connect():
            logger.info("Retrying OBS connection in 5 seconds...")
            time.sleep(5)

        if not self.running:
            return

        # Create sources
        logger.info("Creating OBS sources...")
        created = self.obs_manager.create_all_sources(self.enabled_keys)
        logger.info(f"Created {created} sources")

        # Start data server
        self.data_server.start()

        # Main loop
        logger.info("Service running. Press Ctrl+C to stop.")
        try:
            while self.running:
                data = self.data_server.get_data(timeout=0.1)
                if data:
                    logger.info("Processing shot data")
                    self.obs_manager.update_all_sources(
                        data, self.enabled_keys,
                        self.show_label, self.show_unit
                    )
        except KeyboardInterrupt:
            logger.info("Shutting down...")

        self.stop()

    def stop(self):
        """Stop the service."""
        self.running = False
        self.data_server.stop()
        self.obs_manager.disconnect()

# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Open Golf Coach OBS Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python ogc_obs_service.py
    python ogc_obs_service.py --port 921 --obs-port 4455
    python ogc_obs_service.py --obs-password mypassword
    python ogc_obs_service.py --no-labels --no-units
        """
    )

    parser.add_argument("--port", type=int, default=DEFAULT_DATA_PORT,
                        help=f"Port to receive golf data (default: {DEFAULT_DATA_PORT})")
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
    parser.add_argument("--metric", action="store_true",
                        help="Use metric units instead of imperial")
    parser.add_argument("--list-sources", action="store_true",
                        help="List available data sources and exit")

    args = parser.parse_args()

    if args.list_sources:
        print("\nAvailable data sources:")
        print("-" * 50)
        for key, (path, label, fmt, unit) in DATA_POINTS.items():
            print(f"  {key:20} - {label} ({unit or 'text'})")
        print()
        return

    # Determine enabled keys based on unit preference
    if args.metric:
        enabled_keys = [k for k in DEFAULT_ENABLED
                        if not k.endswith('_mph') and not k.endswith('_yards')]
        # Add metric equivalents
        enabled_keys = [k.replace('_mph', '_mps').replace('_yards', '_meters')
                        if k.endswith('_mph') or k.endswith('_yards') else k
                        for k in DEFAULT_ENABLED]
    else:
        enabled_keys = DEFAULT_ENABLED

    print("""
╔═══════════════════════════════════════════════════════════════╗
║           Open Golf Coach OBS Service                        ║
╠═══════════════════════════════════════════════════════════════╣
║  Receives golf shot data and displays it in OBS              ║
╚═══════════════════════════════════════════════════════════════╝
    """)

    service = OGCService(
        data_port=args.port,
        obs_host=args.obs_host,
        obs_port=args.obs_port,
        obs_password=args.obs_password,
        enabled_keys=enabled_keys,
        show_label=not args.no_labels,
        show_unit=not args.no_units
    )

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\nShutting down...")
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    service.start()

if __name__ == "__main__":
    main()
