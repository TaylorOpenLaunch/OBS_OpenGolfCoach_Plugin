# OBS Open Golf Coach Plugin

Display real-time golf shot data from Nova launch monitor directly in OBS Studio. Each data point appears as a separate, moveable text source.


## Requirements

- **OBS Studio** with Python scripting enabled
- **Python 3.10+** - [Download Python](https://www.python.org/downloads/) (use 3.11 for best OBS compatibility)
- **opengolfcoach** pip package (for calculating carry, shot shape, etc.)

## Quick Start

### 1. Install opengolfcoach

Install in the **same Python** that OBS uses:

```bash
pip install opengolfcoach
```

### 2. Add the OBS Script

1. Open **OBS Studio** → `Tools` → `Scripts`
2. Click `Python Settings` tab → set your Python path
3. Click `+` → select `obs_open_golf_coach.py`

### 3. Create Sources

1. Select a scene in OBS
2. Click **"Create All Sources"** in the script settings
3. Position the `OGC_` sources on your stream

## How It Works

```
Nova (launch monitor)
    │
    ▼ Port 921 (OpenAPI protocol)
┌─────────────────────────────┐
│  OBS Script                 │
│  - Sends handshake          │
│  - Keeps connection alive   │
│  - Converts OpenAPI format  │
│  - Calculates with OGC lib  │
│  - Updates text sources     │
└─────────────────────────────┘
    │
    ▼
OBS Text Sources (moveable)
```

## Data Points

| Source | Description |
|--------|-------------|
| OGC_ball_speed | Ball speed (mph) |
| OGC_launch_angle | Launch angle (°) |
| OGC_launch_direction | Launch direction (°) |
| OGC_total_spin | Spin rate (rpm) |
| OGC_carry | Carry distance (yds) |
| OGC_total | Total distance (yds) |
| OGC_offline | Left/right (yds) |
| OGC_peak_height | Max height (yds) |
| OGC_hang_time | Air time (s) |
| OGC_backspin | Backspin (rpm) |
| OGC_sidespin | Sidespin (rpm) |
| OGC_shot_name | Shot shape (Fade, Draw, etc.) |
| OGC_shot_rank | Quality grade (S, A, B, C, D) |

## Troubleshooting

**"opengolfcoach NOT installed"** in script description:
- Install with `pip install opengolfcoach`
- Make sure you're using the same Python that OBS is configured to use

**Connection drops after one shot:**
- Update to the latest script version (implements keep-alive)

**Sources not appearing:**
- Make sure a scene is selected before clicking "Create All Sources"

## License

MIT License
