# OBS Open Golf Coach Plugin

Display real-time golf shot data from your launch monitor (Nova, etc.) in OBS Studio. Each data point (ball speed, carry distance, spin, shot shape, etc.) appears as a separate, moveable text source that you can position anywhere on your stream.

## Architecture

```
┌─────────────────┐      ┌──────────────────────┐      ┌─────────────┐
│  Launch Monitor │      │  OpenAPI Service     │      │ OBS Studio  │
│  (Nova)         │─────>│  (ogc_openapi_       │─────>│ Plugin      │
│                 │ 921  │   service.py)        │ 9211 │             │
└─────────────────┘      │                      │      └─────────────┘
                         │  Uses opengolfcoach  │
                         │  pip package for     │
                         │  calculations        │
                         └──────────────────────┘
```

**Port 921**: OpenAPI protocol (what Nova and launch monitors use)
**Port 9211**: Internal communication to OBS plugin

## Features

- **Individual Text Sources**: Each metric is a separate OBS source you can move, resize, and style independently
- **Real-time Updates**: Shot data updates instantly when received
- **OpenAPI Compatible**: Works with Nova and other launch monitors that use the OpenAPI protocol
- **Headless Processing**: Uses the `opengolfcoach` pip package for all physics calculations

## Available Data Points

| Data Point | Description | Example |
|------------|-------------|---------|
| Ball Speed | Ball velocity at launch | 156.6 mph |
| Launch Angle | Vertical launch angle | 12.5° |
| Total Spin | Combined spin rate | 2800 rpm |
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

- **OBS Studio 28+** (Windows 11)
- **Python 3.10+** (Python 3.11 recommended for OBS compatibility)
- **opengolfcoach** pip package

### Step 1: Install Python Dependencies

```bash
pip install opengolfcoach
```

### Step 2: Set Up OBS Script

1. **Download** `obs_open_golf_coach.py` from this repository

2. **Open OBS Studio** and go to `Tools` > `Scripts`

3. **Configure Python** (first time only):
   - Click `Python Settings` tab
   - Set the Python install path (e.g., `C:\Users\YourName\AppData\Local\Programs\Python\Python311`)

4. **Add the Script**:
   - Click the `+` button
   - Select `obs_open_golf_coach.py`

5. **Create Sources**:
   - In the script settings, click **"Create All Sources"**
   - This adds text sources (prefixed with `OGC_`) to your current scene
   - Position them where you want on your stream

### Step 3: Run the OpenAPI Service

Open a terminal and run:

```bash
python ogc_openapi_service.py
```

You should see:
```
╔═══════════════════════════════════════════════════════════════════╗
║           Open Golf Coach OpenAPI Service                         ║
╚═══════════════════════════════════════════════════════════════════╝

Configuration:
  OpenAPI Port (for Nova):    921
  OBS Plugin Port:            9211

Waiting for launch monitor connection...
```

### Step 4: Connect Your Launch Monitor

Configure Nova (or your launch monitor) to connect to:
- **Host**: `127.0.0.1` (or your PC's IP address)
- **Port**: `921`

When Nova connects, you'll see:
```
Launch monitor connected: ('127.0.0.1', 54321)
Sent handshake to ('127.0.0.1', 54321)
```

### Step 5: Take Shots!

When you hit a shot, the data flows:
1. Nova sends shot data to port 921
2. OpenAPI service processes it with `opengolfcoach`
3. Results are sent to OBS on port 9211
4. OBS text sources update with the new values

## Testing Without a Launch Monitor

Use the included test sender to simulate shots:

```bash
# Test the full flow (OpenAPI service must be running)
python test_sender.py

# Send continuous test shots every 5 seconds
python test_sender.py --continuous

# Test directly to OBS (bypassing OpenAPI service)
python test_sender.py --direct
```

## Configuration

### OBS Script Settings

| Setting | Description | Default |
|---------|-------------|---------|
| Listening Port | Port for receiving processed data | 9211 |
| Show Labels | Display "Carry:", "Total:", etc. | Yes |
| Show Units | Display "yds", "mph", etc. | Yes |

### OpenAPI Service Options

```bash
python ogc_openapi_service.py --help

Options:
  --openapi-port PORT   Port for launch monitor (default: 921)
  --obs-port PORT       Port for OBS plugin (default: 9211)
```

## Files

| File | Description |
|------|-------------|
| `obs_open_golf_coach.py` | OBS Python script - creates and updates text sources |
| `ogc_openapi_service.py` | OpenAPI server - receives data from Nova, processes with opengolfcoach |
| `test_sender.py` | Test utility - simulate shots for testing |
| `requirements.txt` | Python dependencies |

## Troubleshooting

### "Could not connect to OBS plugin"
- Make sure OBS is running with the script loaded
- Check that the OBS script shows "Server listening on port 9211" in the script log
- Verify no other application is using port 9211

### "Connection refused on port 921"
- Make sure `ogc_openapi_service.py` is running
- Check Windows Firewall isn't blocking the port

### Sources not appearing in OBS
- Make sure you clicked "Create All Sources" in the script settings
- Check the OBS script log for errors (`Tools` > `Scripts` > `Script Log`)
- Verify you have a scene selected before creating sources

### Data not updating
- Check that the OpenAPI service shows "Received data from..." messages
- Verify the test sender works: `python test_sender.py`
- Check OBS script log for "Received shot data" messages

### opengolfcoach import error
- Install the package: `pip install opengolfcoach`
- Make sure you're using the correct Python environment

## How It Works

1. **Nova** sends shot data in OpenAPI format:
   ```json
   {
     "BallData": {
       "Speed": 156.6,
       "VLA": 12.5,
       "HLA": -2.0,
       "TotalSpin": 2800,
       "SpinAxis": 15.0
     },
     "Units": "Yards"
   }
   ```

2. **OpenAPI Service** converts and processes:
   ```python
   import opengolfcoach
   result = opengolfcoach.calculate_derived_values(json_input)
   ```

3. **OBS Plugin** receives enriched data:
   ```json
   {
     "open_golf_coach": {
       "carry_distance_yards": 202.9,
       "shot_name": "Fade",
       "shot_rank": "A",
       ...
     }
   }
   ```

4. **Text sources** update with formatted values

## License

MIT License - See LICENSE file for details.

## Credits

- [Open Golf Coach](https://github.com/OpenLaunchLabs/open-golf-coach) - Golf shot calculations
- [OBS Studio](https://obsproject.com/) - Streaming software
