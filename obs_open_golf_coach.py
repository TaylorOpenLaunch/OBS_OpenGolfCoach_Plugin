"""
OBS Open Golf Coach Plugin
==========================
Receives golf shot data from Open Golf Coach via WebSocket/TCP and displays
each data point as a separate, moveable text source in OBS.

Author: Open Golf Coach Community
License: MIT
"""

import obspython as obs
import json
import socket
import threading
import queue
from dataclasses import dataclass
from typing import Optional, Dict, Any
import time

# =============================================================================
# Configuration
# =============================================================================

# Default settings
DEFAULT_PORT = 921
DEFAULT_HOST = "0.0.0.0"
SOURCE_PREFIX = "OGC_"

# Data point definitions: (json_path, display_name, format_string, unit)
DATA_POINTS = {
    # Input metrics
    "ball_speed_mph": ("us_customary_units.ball_speed_mph", "Ball Speed", "{:.1f}", "mph"),
    "ball_speed_mps": ("ball_speed_meters_per_second", "Ball Speed", "{:.1f}", "m/s"),
    "launch_angle_v": ("vertical_launch_angle_degrees", "Launch Angle", "{:.1f}", "°"),
    "launch_angle_h": ("horizontal_launch_angle_degrees", "Horizontal Angle", "{:.1f}", "°"),
    "total_spin": ("total_spin_rpm", "Total Spin", "{:.0f}", "rpm"),
    "spin_axis": ("spin_axis_degrees", "Spin Axis", "{:.1f}", "°"),

    # Calculated metrics (from open_golf_coach key)
    "carry_yards": ("open_golf_coach.us_customary_units.carry_distance_yards", "Carry Distance", "{:.1f}", "yds"),
    "carry_meters": ("open_golf_coach.carry_distance_meters", "Carry Distance", "{:.1f}", "m"),
    "total_yards": ("open_golf_coach.us_customary_units.total_distance_yards", "Total Distance", "{:.1f}", "yds"),
    "total_meters": ("open_golf_coach.total_distance_meters", "Total Distance", "{:.1f}", "m"),
    "offline_yards": ("open_golf_coach.us_customary_units.offline_distance_yards", "Offline", "{:+.1f}", "yds"),
    "offline_meters": ("open_golf_coach.offline_distance_meters", "Offline", "{:+.1f}", "m"),
    "peak_height_yards": ("open_golf_coach.us_customary_units.peak_height_yards", "Peak Height", "{:.1f}", "yds"),
    "peak_height_meters": ("open_golf_coach.peak_height_meters", "Peak Height", "{:.1f}", "m"),
    "hang_time": ("open_golf_coach.hang_time_seconds", "Hang Time", "{:.2f}", "s"),
    "backspin": ("open_golf_coach.backspin_rpm", "Backspin", "{:.0f}", "rpm"),
    "sidespin": ("open_golf_coach.sidespin_rpm", "Sidespin", "{:+.0f}", "rpm"),
    "shot_name": ("open_golf_coach.shot_name", "Shot Shape", "{}", ""),
    "shot_rank": ("open_golf_coach.shot_rank", "Shot Grade", "{}", ""),
}

# =============================================================================
# Global State
# =============================================================================

@dataclass
class PluginState:
    """Holds the global state of the plugin."""
    server_thread: Optional[threading.Thread] = None
    server_socket: Optional[socket.socket] = None
    running: bool = False
    data_queue: queue.Queue = None
    current_data: Dict[str, Any] = None
    enabled_sources: Dict[str, bool] = None
    port: int = DEFAULT_PORT
    host: str = DEFAULT_HOST
    show_units: bool = True
    show_labels: bool = True
    use_imperial: bool = True

    def __post_init__(self):
        self.data_queue = queue.Queue()
        self.current_data = {}
        self.enabled_sources = {key: True for key in DATA_POINTS.keys()}

state = PluginState()

# =============================================================================
# JSON Data Extraction
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

def format_data_point(key: str, data: dict) -> Optional[str]:
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

    # Build display string
    parts = []
    if state.show_labels:
        parts.append(f"{label}:")
    parts.append(formatted_value)
    if state.show_units and unit:
        parts.append(unit)

    return " ".join(parts)

# =============================================================================
# OBS Source Management
# =============================================================================

def get_source_name(key: str) -> str:
    """Get the OBS source name for a data point key."""
    return f"{SOURCE_PREFIX}{key}"

def create_text_source(key: str) -> bool:
    """Create a text source for a data point if it doesn't exist."""
    source_name = get_source_name(key)

    # Check if source already exists
    source = obs.obs_get_source_by_name(source_name)
    if source:
        obs.obs_source_release(source)
        return True

    # Create new text source
    settings = obs.obs_data_create()
    obs.obs_data_set_string(settings, "text", "Waiting for data...")

    # Create the source
    source = obs.obs_source_create("text_gdiplus", source_name, settings, None)
    obs.obs_data_release(settings)

    if source:
        obs.obs_source_release(source)
        obs.script_log(obs.LOG_INFO, f"Created source: {source_name}")
        return True

    obs.script_log(obs.LOG_WARNING, f"Failed to create source: {source_name}")
    return False

def update_text_source(key: str, text: str):
    """Update the text content of a source."""
    source_name = get_source_name(key)
    source = obs.obs_get_source_by_name(source_name)

    if source:
        settings = obs.obs_data_create()
        obs.obs_data_set_string(settings, "text", text)
        obs.obs_source_update(source, settings)
        obs.obs_data_release(settings)
        obs.obs_source_release(source)

def update_all_sources(data: dict):
    """Update all enabled sources with new data."""
    for key in DATA_POINTS.keys():
        if not state.enabled_sources.get(key, False):
            continue

        # Filter based on unit preference
        if state.use_imperial:
            if key.endswith('_meters') or key.endswith('_mps'):
                continue
        else:
            if key.endswith('_yards') or key.endswith('_mph'):
                continue

        formatted = format_data_point(key, data)
        if formatted:
            update_text_source(key, formatted)

def create_all_sources():
    """Create all enabled text sources."""
    for key in DATA_POINTS.keys():
        if state.enabled_sources.get(key, False):
            # Filter based on unit preference
            if state.use_imperial:
                if key.endswith('_meters') or key.endswith('_mps'):
                    continue
            else:
                if key.endswith('_yards') or key.endswith('_mph'):
                    continue
            create_text_source(key)

# =============================================================================
# Network Server
# =============================================================================

def handle_client(client_socket: socket.socket, address):
    """Handle incoming client connection."""
    obs.script_log(obs.LOG_INFO, f"Client connected: {address}")
    buffer = ""

    try:
        while state.running:
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
                        state.data_queue.put(json_data)
                        obs.script_log(obs.LOG_DEBUG, f"Received shot data")
                    except json.JSONDecodeError as e:
                        obs.script_log(obs.LOG_WARNING, f"Invalid JSON: {e}")
    except Exception as e:
        obs.script_log(obs.LOG_WARNING, f"Client error: {e}")
    finally:
        client_socket.close()
        obs.script_log(obs.LOG_INFO, f"Client disconnected: {address}")

def server_thread_func():
    """Main server thread function."""
    obs.script_log(obs.LOG_INFO, f"Starting server on {state.host}:{state.port}")

    try:
        state.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        state.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        state.server_socket.bind((state.host, state.port))
        state.server_socket.listen(5)
        state.server_socket.settimeout(1.0)

        obs.script_log(obs.LOG_INFO, f"Server listening on port {state.port}")

        while state.running:
            try:
                client_socket, address = state.server_socket.accept()
                client_thread = threading.Thread(
                    target=handle_client,
                    args=(client_socket, address),
                    daemon=True
                )
                client_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if state.running:
                    obs.script_log(obs.LOG_WARNING, f"Accept error: {e}")
    except Exception as e:
        obs.script_log(obs.LOG_ERROR, f"Server error: {e}")
    finally:
        if state.server_socket:
            state.server_socket.close()
            state.server_socket = None
        obs.script_log(obs.LOG_INFO, "Server stopped")

def start_server():
    """Start the TCP server."""
    if state.running:
        return

    state.running = True
    state.server_thread = threading.Thread(target=server_thread_func, daemon=True)
    state.server_thread.start()

def stop_server():
    """Stop the TCP server."""
    state.running = False
    if state.server_socket:
        try:
            state.server_socket.close()
        except:
            pass
    if state.server_thread:
        state.server_thread.join(timeout=2.0)
        state.server_thread = None

# =============================================================================
# OBS Script Interface
# =============================================================================

def script_description():
    """Return the script description shown in OBS."""
    return """<h2>Open Golf Coach Plugin</h2>
<p>Displays golf shot data from Open Golf Coach as individual text sources.</p>
<p>Each data point (ball speed, carry distance, spin, etc.) appears as a
separate, moveable text element that you can position anywhere on your stream.</p>
<p><b>Usage:</b></p>
<ol>
<li>Configure the listening port (default: 921)</li>
<li>Click "Create Sources" to generate text sources</li>
<li>Add the sources to your scene and position them</li>
<li>Send data from Open Golf Coach to this port</li>
</ol>
<p>Data format: JSON objects, one per line (newline-delimited)</p>
"""

def script_properties():
    """Define the properties/settings UI for the script."""
    props = obs.obs_properties_create()

    # Server settings
    obs.obs_properties_add_int(props, "port", "Listening Port", 1, 65535, 1)

    # Display settings
    obs.obs_properties_add_bool(props, "show_labels", "Show Labels")
    obs.obs_properties_add_bool(props, "show_units", "Show Units")
    obs.obs_properties_add_bool(props, "use_imperial", "Use Imperial Units (yards/mph)")

    # Data point toggles
    obs.obs_properties_add_text(props, "separator1", "─── Enable/Disable Data Points ───", obs.OBS_TEXT_INFO)

    # Group: Input metrics
    obs.obs_properties_add_bool(props, "enable_ball_speed_mph", "Ball Speed (mph)")
    obs.obs_properties_add_bool(props, "enable_launch_angle_v", "Launch Angle (vertical)")
    obs.obs_properties_add_bool(props, "enable_launch_angle_h", "Launch Angle (horizontal)")
    obs.obs_properties_add_bool(props, "enable_total_spin", "Total Spin")
    obs.obs_properties_add_bool(props, "enable_spin_axis", "Spin Axis")

    # Group: Distance metrics
    obs.obs_properties_add_bool(props, "enable_carry_yards", "Carry Distance")
    obs.obs_properties_add_bool(props, "enable_total_yards", "Total Distance")
    obs.obs_properties_add_bool(props, "enable_offline_yards", "Offline Distance")
    obs.obs_properties_add_bool(props, "enable_peak_height_yards", "Peak Height")
    obs.obs_properties_add_bool(props, "enable_hang_time", "Hang Time")

    # Group: Spin breakdown
    obs.obs_properties_add_bool(props, "enable_backspin", "Backspin")
    obs.obs_properties_add_bool(props, "enable_sidespin", "Sidespin")

    # Group: Shot classification
    obs.obs_properties_add_bool(props, "enable_shot_name", "Shot Shape")
    obs.obs_properties_add_bool(props, "enable_shot_rank", "Shot Grade")

    # Action buttons
    obs.obs_properties_add_button(props, "create_sources_btn", "Create Sources", create_sources_clicked)
    obs.obs_properties_add_button(props, "test_data_btn", "Send Test Data", send_test_data_clicked)

    return props

def script_defaults(settings):
    """Set default values for script settings."""
    obs.obs_data_set_default_int(settings, "port", DEFAULT_PORT)
    obs.obs_data_set_default_bool(settings, "show_labels", True)
    obs.obs_data_set_default_bool(settings, "show_units", True)
    obs.obs_data_set_default_bool(settings, "use_imperial", True)

    # Enable all data points by default
    for key in DATA_POINTS.keys():
        obs.obs_data_set_default_bool(settings, f"enable_{key}", True)

def script_update(settings):
    """Called when settings are changed."""
    state.port = obs.obs_data_get_int(settings, "port")
    state.show_labels = obs.obs_data_get_bool(settings, "show_labels")
    state.show_units = obs.obs_data_get_bool(settings, "show_units")
    state.use_imperial = obs.obs_data_get_bool(settings, "use_imperial")

    # Update enabled sources
    for key in DATA_POINTS.keys():
        state.enabled_sources[key] = obs.obs_data_get_bool(settings, f"enable_{key}")

    # Restart server if port changed
    if state.running:
        stop_server()
        start_server()

def script_load(settings):
    """Called when the script is loaded."""
    obs.script_log(obs.LOG_INFO, "Open Golf Coach Plugin loaded")
    script_update(settings)
    start_server()

    # Register timer for processing queue
    obs.timer_add(process_data_queue, 100)

def script_unload():
    """Called when the script is unloaded."""
    obs.timer_remove(process_data_queue)
    stop_server()
    obs.script_log(obs.LOG_INFO, "Open Golf Coach Plugin unloaded")

# =============================================================================
# Callbacks and Helpers
# =============================================================================

def process_data_queue():
    """Process any pending data in the queue (called from main thread)."""
    try:
        while not state.data_queue.empty():
            data = state.data_queue.get_nowait()
            state.current_data = data
            update_all_sources(data)
    except queue.Empty:
        pass

def create_sources_clicked(props, prop):
    """Button callback to create all sources."""
    create_all_sources()
    obs.script_log(obs.LOG_INFO, "Sources created")
    return True

def send_test_data_clicked(props, prop):
    """Button callback to send test data."""
    test_data = {
        "ball_speed_meters_per_second": 70.0,
        "vertical_launch_angle_degrees": 12.5,
        "horizontal_launch_angle_degrees": -2.0,
        "total_spin_rpm": 2800.0,
        "spin_axis_degrees": 15.0,
        "open_golf_coach": {
            "carry_distance_meters": 185.4,
            "total_distance_meters": 195.2,
            "offline_distance_meters": -6.2,
            "peak_height_meters": 28.5,
            "hang_time_seconds": 7.2,
            "backspin_rpm": 2700.5,
            "sidespin_rpm": 724.8,
            "shot_name": "Fade",
            "shot_rank": "A",
            "us_customary_units": {
                "ball_speed_mph": 156.6,
                "carry_distance_yards": 202.9,
                "total_distance_yards": 213.3,
                "offline_distance_yards": -6.8,
                "peak_height_yards": 31.2
            }
        },
        "us_customary_units": {
            "ball_speed_mph": 156.6
        }
    }
    state.data_queue.put(test_data)
    obs.script_log(obs.LOG_INFO, "Test data sent")
    return True
