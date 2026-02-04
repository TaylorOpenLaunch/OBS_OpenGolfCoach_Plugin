"""
OBS Open Golf Coach Plugin
==========================
Receives golf shot data and displays each data point as a separate,
moveable text source in OBS.

This plugin can work in two modes:
1. Standalone: Receives processed OGC JSON data
2. With OpenAPI service: Receives data from ogc_openapi_service.py

Author: Open Golf Coach Community
License: MIT
"""

import obspython as obs
import json
import socket
import threading
import queue
from typing import Optional, Dict, Any
import time

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_PORT = 9211  # Port for receiving processed OGC data
DEFAULT_HOST = "0.0.0.0"
SOURCE_PREFIX = "OGC_"

# Data point definitions: (json_path, display_name, format_string, unit)
DATA_POINTS = {
    # Input metrics (Imperial)
    "ball_speed": ("open_golf_coach.us_customary_units.ball_speed_mph", "Ball Speed", "{:.1f}", "mph"),
    "launch_angle": ("vertical_launch_angle_degrees", "Launch Angle", "{:.1f}", "°"),
    "total_spin": ("total_spin_rpm", "Total Spin", "{:.0f}", "rpm"),

    # Calculated metrics (Imperial)
    "carry": ("open_golf_coach.us_customary_units.carry_distance_yards", "Carry", "{:.1f}", "yds"),
    "total": ("open_golf_coach.us_customary_units.total_distance_yards", "Total", "{:.1f}", "yds"),
    "offline": ("open_golf_coach.us_customary_units.offline_distance_yards", "Offline", "{:+.1f}", "yds"),
    "peak_height": ("open_golf_coach.us_customary_units.peak_height_yards", "Peak Height", "{:.1f}", "yds"),
    "hang_time": ("open_golf_coach.hang_time_seconds", "Hang Time", "{:.2f}", "s"),

    # Spin breakdown
    "backspin": ("open_golf_coach.backspin_rpm", "Backspin", "{:.0f}", "rpm"),
    "sidespin": ("open_golf_coach.sidespin_rpm", "Sidespin", "{:+.0f}", "rpm"),

    # Shot classification
    "shot_name": ("open_golf_coach.shot_name", "Shot", "{}", ""),
    "shot_rank": ("open_golf_coach.shot_rank", "Grade", "{}", ""),
}

# =============================================================================
# Global State
# =============================================================================

class PluginState:
    """Holds the global state of the plugin."""
    def __init__(self):
        self.server_thread: Optional[threading.Thread] = None
        self.server_socket: Optional[socket.socket] = None
        self.running: bool = False
        self.data_queue: queue.Queue = queue.Queue()
        self.current_data: Dict[str, Any] = {}
        self.enabled_sources: Dict[str, bool] = {key: True for key in DATA_POINTS.keys()}
        self.port: int = DEFAULT_PORT
        self.host: str = DEFAULT_HOST
        self.show_units: bool = True
        self.show_labels: bool = True
        self.created_sources: set = set()

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

def create_text_source(key: str, initial_text: str = "---") -> bool:
    """Create a text source and add it to the current scene."""
    source_name = get_source_name(key)

    # Check if source already exists
    existing_source = obs.obs_get_source_by_name(source_name)
    if existing_source:
        obs.obs_source_release(existing_source)
        obs.script_log(obs.LOG_INFO, f"Source already exists: {source_name}")
        state.created_sources.add(source_name)
        return True

    # Get current scene
    current_scene = obs.obs_frontend_get_current_scene()
    if not current_scene:
        obs.script_log(obs.LOG_WARNING, "No scene available - please select a scene first")
        return False

    scene = obs.obs_scene_from_source(current_scene)
    if not scene:
        obs.obs_source_release(current_scene)
        obs.script_log(obs.LOG_WARNING, "Could not get scene object")
        return False

    # Create settings for text source
    settings = obs.obs_data_create()
    obs.obs_data_set_string(settings, "text", initial_text)

    # Font settings - use simple approach that works across OBS versions
    font_obj = obs.obs_data_create()
    obs.obs_data_set_string(font_obj, "face", "Arial")
    obs.obs_data_set_int(font_obj, "size", 48)
    obs.obs_data_set_obj(settings, "font", font_obj)
    obs.obs_data_release(font_obj)

    # Try different text source types (OBS version compatibility)
    source = None
    for source_type in ["text_gdiplus", "text_gdiplus_v2", "text_gdiplus_v3"]:
        source = obs.obs_source_create(source_type, source_name, settings, None)
        if source:
            obs.script_log(obs.LOG_INFO, f"Using source type: {source_type}")
            break

    obs.obs_data_release(settings)

    if not source:
        obs.script_log(obs.LOG_ERROR, f"Failed to create text source (tried all types): {source_name}")
        obs.obs_source_release(current_scene)
        return False

    # Add source to scene
    scene_item = obs.obs_scene_add(scene, source)
    if scene_item:
        # Position sources in a column
        pos = obs.vec2()
        idx = list(DATA_POINTS.keys()).index(key) if key in DATA_POINTS else 0
        pos.x = 50
        pos.y = 50 + (idx * 70)
        obs.obs_sceneitem_set_pos(scene_item, pos)
        obs.script_log(obs.LOG_INFO, f"SUCCESS: Added {source_name} to scene at ({pos.x}, {pos.y})")
        state.created_sources.add(source_name)
    else:
        obs.script_log(obs.LOG_ERROR, f"FAILED: Could not add {source_name} to scene")

    obs.obs_source_release(source)
    obs.obs_source_release(current_scene)
    return scene_item is not None

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

        formatted = format_data_point(key, data)
        if formatted:
            update_text_source(key, formatted)

def create_all_sources():
    """Create all enabled text sources."""
    created_count = 0
    for key in DATA_POINTS.keys():
        if state.enabled_sources.get(key, False):
            if create_text_source(key, "---"):
                created_count += 1
    return created_count

# =============================================================================
# Network Server
# =============================================================================

def handle_client(client_socket: socket.socket, address):
    """Handle incoming client connection."""
    obs.script_log(obs.LOG_INFO, f"Client connected: {address}")
    buffer = ""

    try:
        while state.running:
            try:
                client_socket.settimeout(1.0)
                data = client_socket.recv(4096)
            except socket.timeout:
                continue

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
                        obs.script_log(obs.LOG_INFO, "Received shot data")
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
    return """<h2>Open Golf Coach OBS Plugin</h2>
<p>Displays golf shot data as individual moveable text sources.</p>
<p><b>Setup:</b></p>
<ol>
<li>Click "Create All Sources" to generate text sources in your current scene</li>
<li>Position the sources where you want them on your stream</li>
<li>Run the OpenAPI service: <code>python ogc_openapi_service.py</code></li>
<li>Connect your launch monitor (Nova) to port 921</li>
</ol>
<p>The OpenAPI service processes data and sends it to this plugin on port 9211.</p>
"""

def script_properties():
    """Define the properties/settings UI for the script."""
    props = obs.obs_properties_create()

    # Server settings
    obs.obs_properties_add_int(props, "port", "Listening Port", 1, 65535, 1)

    # Display settings
    obs.obs_properties_add_bool(props, "show_labels", "Show Labels (e.g., 'Carry:')")
    obs.obs_properties_add_bool(props, "show_units", "Show Units (e.g., 'yds')")

    # Data point toggles
    p = obs.obs_properties_add_bool(props, "enable_ball_speed", "Ball Speed")
    obs.obs_properties_add_bool(props, "enable_launch_angle", "Launch Angle")
    obs.obs_properties_add_bool(props, "enable_total_spin", "Total Spin")
    obs.obs_properties_add_bool(props, "enable_carry", "Carry Distance")
    obs.obs_properties_add_bool(props, "enable_total", "Total Distance")
    obs.obs_properties_add_bool(props, "enable_offline", "Offline Distance")
    obs.obs_properties_add_bool(props, "enable_peak_height", "Peak Height")
    obs.obs_properties_add_bool(props, "enable_hang_time", "Hang Time")
    obs.obs_properties_add_bool(props, "enable_backspin", "Backspin")
    obs.obs_properties_add_bool(props, "enable_sidespin", "Sidespin")
    obs.obs_properties_add_bool(props, "enable_shot_name", "Shot Shape")
    obs.obs_properties_add_bool(props, "enable_shot_rank", "Shot Grade")

    # Action buttons
    obs.obs_properties_add_button(props, "create_sources_btn", "Create All Sources", create_sources_clicked)
    obs.obs_properties_add_button(props, "test_data_btn", "Test with Sample Data", send_test_data_clicked)

    return props

def script_defaults(settings):
    """Set default values for script settings."""
    obs.obs_data_set_default_int(settings, "port", DEFAULT_PORT)
    obs.obs_data_set_default_bool(settings, "show_labels", True)
    obs.obs_data_set_default_bool(settings, "show_units", True)

    # Enable all data points by default
    for key in DATA_POINTS.keys():
        obs.obs_data_set_default_bool(settings, f"enable_{key}", True)

def script_update(settings):
    """Called when settings are changed."""
    new_port = obs.obs_data_get_int(settings, "port")
    state.show_labels = obs.obs_data_get_bool(settings, "show_labels")
    state.show_units = obs.obs_data_get_bool(settings, "show_units")

    # Update enabled sources
    for key in DATA_POINTS.keys():
        state.enabled_sources[key] = obs.obs_data_get_bool(settings, f"enable_{key}")

    # Restart server if port changed
    if new_port != state.port:
        state.port = new_port
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
    count = create_all_sources()
    obs.script_log(obs.LOG_INFO, f"Created {count} sources")
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
        }
    }
    state.data_queue.put(test_data)
    obs.script_log(obs.LOG_INFO, "Test data queued - sources should update")
    return True
