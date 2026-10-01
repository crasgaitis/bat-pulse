const int PIEZO_PIN = A0;
const int THRESHOLD = 60;      // Adjust this until "value 2" spikes on a breath
const int SAMPLE_DELAY = 10;   // 10ms = 100Hz (200 samples = 2 seconds)

unsigned long lastPeakTime = 0;
unsigned long lastSampleTime = 0;
float respiratoryRate = 0;
bool isPeak = false;

void setup() {
  Serial.begin(115200);
}

void loop() {
  int rawValue = analogRead(PIEZO_PIN);
  unsigned long now = millis();
  unsigned long interval = 0;
  bool newPeak = false;

  // Peak detection with a 'cooldown' to avoid double-counting one breath
  if (rawValue > THRESHOLD && !isPeak) {
    interval = now - lastPeakTime;
   
    if (interval > 400) { // Ignores noise faster than 150 breaths/min
      respiratoryRate = 60000.0 / interval;
      lastPeakTime = now;
      isPeak = true;
      newPeak = true;
    }
  }
 
  if (rawValue < (THRESHOLD * 0.7)) {
    isPeak = false; // Reset when signal drops
  }

  // ms since previous sample, so Python can rebuild exact timestamps
  unsigned long dt = now - lastSampleTime;
  lastSampleTime = now;
  if (dt > 127) dt = 127;

  // Binary packet: 3 bytes per sample, +3 bytes (interval) on a new peak
  uint8_t pkt[6];
  uint8_t n = 0;
  pkt[n++] = 0x80 | (newPeak << 6) | (rawValue >> 5);
  pkt[n++] = rawValue & 0x1F;
  pkt[n++] = dt;
  if (newPeak) {
    if (interval > 0x1FFFFF) interval = 0x1FFFFF;
    pkt[n++] = (interval >> 14) & 0x7F;
    pkt[n++] = (interval >> 7) & 0x7F;
    pkt[n++] = interval & 0x7F;
  }
  Serial.write(pkt, n);

  delay(SAMPLE_DELAY);
}
