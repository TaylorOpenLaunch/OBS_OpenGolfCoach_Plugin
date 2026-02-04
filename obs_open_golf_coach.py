"""
OBS Open Golf Coach Plugin
==========================
Receives golf shot data directly from Nova launch monitor and displays
each data point as a separate, moveable text source in OBS.

Implements the OpenAPI protocol that Nova uses:
1. Sends handshake on connect: {"Code":201,"GameId":"OpenGolfCoach"}
2. Keeps connection alive for multiple shots
3. Converts OpenAPI format and calculates derived values

Author: Open Golf Coach Community
License: MIT
"""

import obspython as obs
import json
import socket
import threading
import queue
from typing import Optional, Dict, Any

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_PORT = 921  # OpenAPI port that Nova connects to
DEFAULT_HOST = "0.0.0.0"
SOURCE_PREFIX = "OGC_"
OPENAPI_HANDSHAKE = '{"Code":201,"GameId":"OpenGolfCoach"}'

# Try to import opengolfcoach for calculations
try:
    import opengolfcoach
    HAS_OGC = True
except ImportError:
    HAS_OGC = False

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
# OpenAPI Protocol Handling
# =============================================================================

def convert_openapi_to_ogc(openapi_data: dict) -> dict:
    """Convert OpenAPI format (from Nova) to Open Golf Coach format."""
    ogc_input = {}

    ball_data = openapi_data.get("BallData", {})
    units = openapi_data.get("Units", "Yards")
    is_imperial = "Yards" in units or "MPH" in units

    # Speed -> ball_speed_meters_per_second
    speed = ball_data.get("Speed")
    if speed is not None:
        if is_imperial:
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

    # BackSpin and SideSpin if provided
    backspin = ball_data.get("BackSpin")
    sidespin = ball_data.get("SideSpin")
    if backspin is not None:
        ogc_input["backspin_rpm"] = backspin
    if sidespin is not None:
        ogc_input["sidespin_rpm"] = sidespin

    return ogc_input

def process_shot(openapi_data: dict) -> Optional[dict]:
    """Process shot data - convert and calculate derived values."""
    # Check if this is OpenAPI format (has BallData) or already OGC format
    if "BallData" in openapi_data:
        ogc_input = convert_openapi_to_ogc(openapi_data)
        obs.script_log(obs.LOG_INFO, f"Converted OpenAPI data: speed={ogc_input.get('ball_speed_meters_per_second', 'N/A')}")
    elif "open_golf_coach" in openapi_data:
        # Already processed, return as-is
        return openapi_data
    else:
        ogc_input = openapi_data

    if not ogc_input:
        return None

    # Calculate derived values using opengolfcoach library
    if HAS_OGC:
        try:
            result_json = opengolfcoach.calculate_derived_values(json.dumps(ogc_input))
            result = json.loads(result_json)
            obs.script_log(obs.LOG_INFO, f"Calculated: {result.get('open_golf_coach', {}).get('shot_name', 'N/A')}")
            return result
        except Exception as e:
            obs.script_log(obs.LOG_WARNING, f"OGC calculation error: {e}")
            return ogc_input
    else:
        obs.script_log(obs.LOG_WARNING, "opengolfcoach not installed - showing raw data only")
        return ogc_input

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
    return f"{SOURCE_PREFIX}{key}"

def create_text_source(key: str, initial_text: str = "---") -> bool:
    """Create a text source and add it to the current scene."""
    source_name = get_source_name(key)

    existing_source = obs.obs_get_source_by_name(source_name)
    if existing_source:
        obs.obs_source_release(existing_source)
        obs.script_log(obs.LOG_INFO, f"Source already exists: {source_name}")
        state.created_sources.add(source_name)
        return True

    current_scene = obs.obs_frontend_get_current_scene()
    if not current_scene:
        obs.script_log(obs.LOG_WARNING, "No scene available - please select a scene first")
        return False

    scene = obs.obs_scene_from_source(current_scene)
    if not scene:
        obs.obs_source_release(current_scene)
        obs.script_log(obs.LOG_WARNING, "Could not get scene object")
        return False

    settings = obs.obs_data_create()
    obs.obs_data_set_string(settings, "text", initial_text)

    font_obj = obs.obs_data_create()
    obs.obs_data_set_string(font_obj, "face", "Arial")
    obs.obs_data_set_int(font_obj, "size", 48)
    obs.obs_data_set_obj(settings, "font", font_obj)
    obs.obs_data_release(font_obj)

    source = None
    for source_type in ["text_gdiplus", "text_gdiplus_v2", "text_gdiplus_v3"]:
        source = obs.obs_source_create(source_type, source_name, settings, None)
        if source:
            obs.script_log(obs.LOG_INFO, f"Using source type: {source_type}")
            break

    obs.obs_data_release(settings)

    if not source:
        obs.script_log(obs.LOG_ERROR, f"Failed to create text source: {source_name}")
        obs.obs_source_release(current_scene)
        return False

    scene_item = obs.obs_scene_add(scene, source)
    if scene_item:
        pos = obs.vec2()
        idx = list(DATA_POINTS.keys()).index(key) if key in DATA_POINTS else 0
        pos.x = 50
        pos.y = 50 + (idx * 70)
        obs.obs_sceneitem_set_pos(scene_item, pos)
        obs.script_log(obs.LOG_INFO, f"SUCCESS: Added {source_name} to scene")
        state.created_sources.add(source_name)
    else:
        obs.script_log(obs.LOG_ERROR, f"FAILED: Could not add {source_name} to scene")

    obs.obs_source_release(source)
    obs.obs_source_release(current_scene)
    return scene_item is not None

def update_text_source(key: str, text: str):
    source_name = get_source_name(key)
    source = obs.obs_get_source_by_name(source_name)
    if source:
        settings = obs.obs_data_create()
        obs.obs_data_set_string(settings, "text", text)
        obs.obs_source_update(source, settings)
        obs.obs_data_release(settings)
        obs.obs_source_release(source)

def update_all_sources(data: dict):
    for key in DATA_POINTS.keys():
        if not state.enabled_sources.get(key, False):
            continue
        formatted = format_data_point(key, data)
        if formatted:
            update_text_source(key, formatted)

def create_all_sources():
    created_count = 0
    for key in DATA_POINTS.keys():
        if state.enabled_sources.get(key, False):
            if create_text_source(key, "---"):
                created_count += 1
    return created_count

# =============================================================================
# Network Server - OpenAPI Protocol
# =============================================================================

def handle_client(client_socket: socket.socket, address):
    """Handle Nova connection with OpenAPI protocol."""
    obs.script_log(obs.LOG_INFO, f"Nova connected: {address}")

    try:
        # Send OpenAPI handshake immediately
        handshake = OPENAPI_HANDSHAKE + "\n"
        client_socket.sendall(handshake.encode('utf-8'))
        obs.script_log(obs.LOG_INFO, f"Sent handshake to {address}")

        # Keep connection alive for multiple shots
        buffer = b""
        while state.running:
            try:
                client_socket.settimeout(1.0)
                chunk = client_socket.recv(4096)
            except socket.timeout:
                continue

            if not chunk:
                obs.script_log(obs.LOG_INFO, f"Nova disconnected: {address}")
                break

            buffer += chunk

            # Try to parse complete JSON messages
            while buffer:
                # Try to decode and parse
                try:
                    text = buffer.decode('utf-8')
                except UnicodeDecodeError:
                    break

                text = text.strip()
                if not text:
                    buffer = b""
                    break

                # Try to parse as JSON
                try:
                    data = json.loads(text)
                    buffer = b""  # Clear buffer on successful parse

                    obs.script_log(obs.LOG_INFO, f"Received shot data from Nova")

                    # Process the shot
                    processed = process_shot(data)
                    if processed:
                        state.data_queue.put(processed)

                except json.JSONDecodeError:
                    # Check for newline-delimited messages
                    if b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        try:
                            text = line.decode('utf-8').strip()
                            if text:
                                data = json.loads(text)
                                obs.script_log(obs.LOG_INFO, f"Received shot data from Nova")
                                processed = process_shot(data)
                                if processed:
                                    state.data_queue.put(processed)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            pass
                    else:
                        break  # Wait for more data

    except Exception as e:
        obs.script_log(obs.LOG_WARNING, f"Client error: {e}")
    finally:
        client_socket.close()
        obs.script_log(obs.LOG_INFO, f"Connection closed: {address}")

def server_thread_func():
    """Main server thread."""
    obs.script_log(obs.LOG_INFO, f"Starting OpenAPI server on port {state.port}")

    try:
        state.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        state.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        state.server_socket.bind((state.host, state.port))
        state.server_socket.listen(5)
        state.server_socket.settimeout(1.0)

        obs.script_log(obs.LOG_INFO, f"Waiting for Nova on port {state.port}...")

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
    if state.running:
        return
    state.running = True
    state.server_thread = threading.Thread(target=server_thread_func, daemon=True)
    state.server_thread.start()

def stop_server():
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
    ogc_status = "installed" if HAS_OGC else "NOT INSTALLED - run: pip install opengolfcoach"
    return f"""<h2>Open Golf Coach OBS Plugin</h2>
<p>Receives shot data directly from Nova launch monitor.</p>
<p><b>opengolfcoach library:</b> {ogc_status}</p>
<p><b>Setup:</b></p>
<ol>
<li>Click "Create All Sources" to add text sources to your scene</li>
<li>Configure Nova to connect to this PC on port 921</li>
<li>Take shots!</li>
</ol>
"""

def script_properties():
    props = obs.obs_properties_create()

    obs.obs_properties_add_int(props, "port", "Listening Port (for Nova)", 1, 65535, 1)
    obs.obs_properties_add_bool(props, "show_labels", "Show Labels")
    obs.obs_properties_add_bool(props, "show_units", "Show Units")

    obs.obs_properties_add_bool(props, "enable_ball_speed", "Ball Speed")
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

    obs.obs_properties_add_button(props, "create_sources_btn", "Create All Sources", create_sources_clicked)
    obs.obs_properties_add_button(props, "test_data_btn", "Test with Sample Data", send_test_data_clicked)

    return props

def script_defaults(settings):
    obs.obs_data_set_default_int(settings, "port", DEFAULT_PORT)
    obs.obs_data_set_default_bool(settings, "show_labels", True)
    obs.obs_data_set_default_bool(settings, "show_units", True)
    for key in DATA_POINTS.keys():
        obs.obs_data_set_default_bool(settings, f"enable_{key}", True)

def script_update(settings):
    new_port = obs.obs_data_get_int(settings, "port")
    state.show_labels = obs.obs_data_get_bool(settings, "show_labels")
    state.show_units = obs.obs_data_get_bool(settings, "show_units")

    for key in DATA_POINTS.keys():
        state.enabled_sources[key] = obs.obs_data_get_bool(settings, f"enable_{key}")

    if new_port != state.port:
        state.port = new_port
        if state.running:
            stop_server()
            start_server()

def script_load(settings):
    obs.script_log(obs.LOG_INFO, "Open Golf Coach Plugin loaded")
    if HAS_OGC:
        obs.script_log(obs.LOG_INFO, "opengolfcoach library available")
    else:
        obs.script_log(obs.LOG_WARNING, "opengolfcoach NOT installed - pip install opengolfcoach")
    script_update(settings)
    start_server()
    obs.timer_add(process_data_queue, 100)

def script_unload():
    obs.timer_remove(process_data_queue)
    stop_server()
    obs.script_log(obs.LOG_INFO, "Open Golf Coach Plugin unloaded")

# =============================================================================
# Callbacks
# =============================================================================

def process_data_queue():
    try:
        while not state.data_queue.empty():
            data = state.data_queue.get_nowait()
            state.current_data = data
            update_all_sources(data)
    except:
        pass

def create_sources_clicked(props, prop):
    count = create_all_sources()
    obs.script_log(obs.LOG_INFO, f"Created {count} sources")
    return True

def send_test_data_clicked(props, prop):
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
    obs.script_log(obs.LOG_INFO, "Test data queued")
    return True
