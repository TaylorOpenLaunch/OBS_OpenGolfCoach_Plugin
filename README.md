# OBS Open Golf Coach Plugin

Display real-time golf shot data from [Open Golf Coach](https://github.com/OpenLaunchLabs/open-golf-coach) in OBS Studio. Each data point (ball speed, carry distance, spin, shot shape, etc.) appears as a separate, moveable text source that you can position anywhere on your stream.

## Features

- **Individual Text Sources**: Each metric (ball speed, carry, spin, etc.) is a separate OBS source you can move, resize, and style independently
- **Real-time Updates**: Shot data updates instantly when received from Open Golf Coach
- **Customizable Display**: Show/hide labels, units, and choose between imperial or metric
- **Two Integration Options**:
  - **OBS Script**: Runs inside OBS (simpler setup)
  - **Standalone Service**: Runs as a separate process (more robust)

## Available Data Points

| Data Point | Description | Example |
|------------|-------------|---------|
| Ball Speed | Ball velocity at launch | 156.6 mph |
| Launch Angle | Vertical launch angle | 12.5° |
| Horizontal Angle | Side-to-side launch direction | -2.0° |
| Total Spin | Combined spin rate | 2800 rpm |
| Spin Axis | Tilt of spin axis | 15° |
| Carry Distance | Air distance | 202.9 yds |
| Total Distance | Carry + roll | 213.3 yds |
| Offline | Left/right deviation | -6.8 yds |
| Peak Height | Maximum ball height | 31.2 yds |
| Hang Time | Time in air | 7.2 s |
| Backspin | Backspin component | 2700 rpm |
| Sidespin | Sidespin component | +725 rpm |
| Shot Shape | Draw, Fade, Straight, etc. | Fade |
| Shot Grade | Quality rating | A |

## Installation

### Prerequisites

- **OBS Studio 28+** (for WebSocket support)
- **Python 3.10+** (for Windows, use 3.11 for best OBS compatibility)
- **Windows 11** (primary target OS)

### Option 1: OBS Script (Recommended for Simplicity)

1. **Download** `obs_open_golf_coach.py` from this repository

2. **Open OBS Studio** and go to `Tools` > `Scripts`

3. **Configure Python**:
   - Click `Python Settings` tab
   - Set the Python install path (e.g., `C:\Users\YourName\AppData\Local\Programs\Python\Python311`)

4. **Add the Script**:
   - Click the `+` button
   - Select `obs_open_golf_coach.py`

5. **Configure Settings**:
   - Set the listening port (default: 921)
   - Enable/disable data points as desired
   - Click "Create Sources" to generate the text sources

6. **Add Sources to Scene**:
   - The script creates sources prefixed with `OGC_`
   - Add them to your scene via `Add` > `Text (GDI+)` > select existing source

### Option 2: Bridge Service (Recommended for Full Integration)

Use this when you have a launch monitor sending raw data that needs processing by Open Golf Coach.

1. **Install Dependencies**:
   ```bash
   pip install obsws-python opengolfcoach
   ```

2. **Enable OBS WebSocket**:
   - In OBS, go to `Tools` > `WebSocket Server Settings`
   - Enable the WebSocket server
   - Note the port (default: 4455) and password if set

3. **Start Open Golf Coach** (if using TCP mode):
   - Open Golf Coach should be listening on port 921

4. **Run the Bridge**:
   ```bash
   python ogc_bridge.py --listen-port 9210 --ogc-port 921 --obs-port 4455
   ```

5. **Configure your launch monitor** to send data to port 9210

The bridge will:
- Receive raw launch monitor data on port 9210
- Send it to Open Golf Coach on port 921 for processing
- Display the enriched results in OBS

### Option 3: Standalone Service (For Pre-processed Data)

Use this when your application already produces Open Golf Coach formatted output.

1. **Install Dependencies**:
   ```bash
   pip install obsws-python
   ```

2. **Run the Service**:
   ```bash
   python ogc_obs_service.py --port 921 --obs-port 4455
   ```

The service will create text sources in your current scene automatically.

## Configuration

### OBS Script Settings

| Setting | Description | Default |
|---------|-------------|---------|
| Listening Port | TCP port for incoming data | 921 |
| Show Labels | Display "Ball Speed:", etc. | Yes |
| Show Units | Display "mph", "yds", etc. | Yes |
| Use Imperial | Use mph/yards vs m/s/meters | Yes |

### Standalone Service Options

```bash
python ogc_obs_service.py --help

Options:
  --port PORT           Port to receive golf data (default: 921)
  --obs-host HOST       OBS WebSocket host (default: localhost)
  --obs-port PORT       OBS WebSocket port (default: 4455)
  --obs-password PASS   OBS WebSocket password (if configured)
  --no-labels           Hide data point labels
  --no-units            Hide unit suffixes
  --metric              Use metric units instead of imperial
  --list-sources        List available data sources and exit
```

## Data Format

The plugin expects JSON data in the Open Golf Coach format, sent as newline-delimited JSON over TCP:

```json
{
  "ball_speed_meters_per_second": 70.0,
  "vertical_launch_angle_degrees": 12.5,
  "horizontal_launch_angle_degrees": -2.0,
  "total_spin_rpm": 2800.0,
  "spin_axis_degrees": 15.0,
  "us_customary_units": {
    "ball_speed_mph": 156.6
  },
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
      "carry_distance_yards": 202.9,
      "total_distance_yards": 213.3,
      "offline_distance_yards": -6.8,
      "peak_height_yards": 31.2
    }
  }
}
```

## Testing

Use the included test sender to simulate shot data:

```bash
# Send a single test shot
python test_sender.py

# Send continuous shots every 5 seconds
python test_sender.py --continuous

# Specify custom port
python test_sender.py --port 921
```

## Integration with Open Golf Coach

### Using the Python Library Directly

You can integrate Open Golf Coach calculations with your launch monitor data:

```python
import opengolfcoach
import json
import socket

# Your launch monitor data
shot = {
    "ball_speed_meters_per_second": 70.0,
    "vertical_launch_angle_degrees": 12.5,
    "horizontal_launch_angle_degrees": -2.0,
    "total_spin_rpm": 2800.0,
    "spin_axis_degrees": 15.0
}

# Calculate derived metrics
result_json = opengolfcoach.calculate_derived_values(json.dumps(shot))
result = json.loads(result_json)

# Send to OBS plugin
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.connect(("127.0.0.1", 921))
    sock.sendall((json.dumps(result) + "\n").encode())
```

### Architecture Diagram

**Option A: Bridge Mode (Recommended)**
```
┌─────────────────┐     ┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Launch Monitor │────>│   Bridge    │────>│  Open Golf Coach │────>│  OBS Studio │
│  (Hardware)     │     │  (Port 9210)│     │   (Port 921)     │     │ (WebSocket) │
└─────────────────┘     └─────────────┘     └──────────────────┘     └─────────────┘

Run: python ogc_bridge.py --listen-port 9210 --ogc-port 921
```

**Option B: Direct Mode (Pre-processed data)**
```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Your App with  │────>│    OBS Plugin    │────>│  OBS Studio │
│  OGC Processing │     │    (Port 921)    │     │             │
└─────────────────┘     └──────────────────┘     └─────────────┘

Run: python ogc_obs_service.py --port 921
```

## Troubleshooting

### "Could not connect to OBS"
- Ensure OBS is running
- Check that WebSocket server is enabled in OBS (`Tools` > `WebSocket Server Settings`)
- Verify the port number matches

### "Connection refused on port 921"
- Ensure the OBS script is loaded or standalone service is running
- Check Windows Firewall isn't blocking the port
- Verify no other application is using port 921

### Sources not appearing
- Click "Create Sources" in the script settings
- For standalone service, ensure OBS is running before starting the service
- Check the OBS script log for errors (`Tools` > `Scripts` > `Script Log`)

### Data not updating
- Verify data is being sent (use test_sender.py to confirm)
- Check that JSON is newline-terminated
- Review the script/service log for parsing errors

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions welcome! Please open an issue or pull request on GitHub.

## Credits

- [Open Golf Coach](https://github.com/OpenLaunchLabs/open-golf-coach) - Golf shot calculations
- [OBS Studio](https://obsproject.com/) - Streaming software
- [obs-websocket](https://github.com/obsproject/obs-websocket) - OBS WebSocket protocol
