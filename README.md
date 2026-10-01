# bat-pulse
gui for checking bat respiration during surgery

1. plug in arduino and upload respiration-monitor.ino to the board. ensure that baud rate is set to 115200.
2. make sure serial monitor is open
3. run `respiration_gui.py` to open gui. this will allow you to see respiration info live and save your recording.
4. your saved recording auto saves as ```breathing_YYYY-MM-DD_HH-MM-SS.csv``` at your designated directory.
5. you can analyze your data wherever or run `respiration-analysis.ipynb` to get started.

important notes:
- `bpm` is the rate calculated at the most recent breath, so it stays the same until the next breath is detected.
- `bpm_live` is calculated at every sample. it usually equals `bpm`, but once the gap since the last breath is longer than the previous breath interval, it will drop steadily (either it shows a slowdown or a stop in breathing right away).