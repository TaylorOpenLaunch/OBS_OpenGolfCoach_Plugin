# OBS Open Golf Coach Plugin

Display real-time golf shot data from Open Golf Coach in OBS Studio. Each data point (ball speed, carry distance, spin, shot shape, etc.) appears as a separate, moveable text source you can position anywhere on your stream.

## Quick Start

### 1. Install the OBS Script

1. Download `obs_open_golf_coach.py` from this repository

2. Open **OBS Studio** → `Tools` → `Scripts`

3. **First time only** - Configure Python:
   - Click `Python Settings` tab
   - Set Python install path (e.g., `C:\Users\YourName\AppData\Local\Programs\Python\Python311`)

4. Click `+` and select `obs_open_golf_coach.py`

### 2. Create Sources

1. **Select a scene** in OBS (important!)
2. In the script settings, click **"Create All Sources"**
3. Text sources prefixed with `OGC_` will appear in your scene
4. Position them where you want on your stream

### 3. Connect Open Golf Coach

Configure Open Golf Coach to send data to:
- **Host**: `127.0.0.1`
- **Port**: `9211` (or whatever port is shown in the script settings)

When shots are received, the text sources update automatically.

## Available Data Points

| Source Name | Data | Example |
|-------------|------|---------|
| OGC_ball_speed | Ball velocity | 156.6 mph |
| OGC_launch_angle | Launch angle | 12.5° |
| OGC_total_spin | Spin rate | 2800 rpm |
| OGC_carry | Carry distance | 202.9 yds |
| OGC_total | Total distance | 213.3 yds |
| OGC_offline | Left/right deviation | -6.8 yds |
| OGC_peak_height | Max height | 31.2 yds |
| OGC_hang_time | Time in air | 7.2 s |
| OGC_backspin | Backspin | 2700 rpm |
| OGC_sidespin | Sidespin | +725 rpm |
| OGC_shot_name | Shot shape | Fade |
| OGC_shot_rank | Quality grade | A |

## Script Settings

| Setting | Description | Default |
|---------|-------------|---------|
| Listening Port | Port for receiving data | 9211 |
| Show Labels | Display "Carry:", "Total:", etc. | Yes |
| Show Units | Display "yds", "mph", etc. | Yes |

You can enable/disable individual data points in the script settings.

## Testing

Click **"Test with Sample Data"** in the script settings to verify sources update correctly.

Or use the included test sender:
```bash
python test_sender.py --direct --port 9211
```

## Data Format

The plugin expects JSON with Open Golf Coach format:
```json
{
  "vertical_launch_angle_degrees": 12.5,
  "total_spin_rpm": 2800,
  "open_golf_coach": {
    "carry_distance_meters": 185.4,
    "hang_time_seconds": 7.2,
    "shot_name": "Fade",
    "shot_rank": "A",
    "us_customary_units": {
      "ball_speed_mph": 156.6,
      "carry_distance_yards": 202.9,
      "total_distance_yards": 213.3
    }
  }
}
```

## Troubleshooting

**Sources not appearing:**
- Make sure a scene is selected before clicking "Create All Sources"
- Check `Tools` → `Scripts` → `Script Log` for errors

**Data not updating:**
- Verify the port matches between sender and script settings
- Check script log for "Received shot data" messages

**Script won't load:**
- Ensure Python path is configured in `Python Settings` tab
- Use Python 3.10 or 3.11 for best compatibility

## Files

| File | Description |
|------|-------------|
| `obs_open_golf_coach.py` | Main OBS script |
| `test_sender.py` | Test utility for simulating shots |

## License

MIT License
