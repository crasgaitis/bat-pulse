const int PIEZO_PIN = A0;
const int THRESHOLD = 60;      // Adjust this until "value 2" spikes on a breath
const int SAMPLE_DELAY = 10;   // 10ms = 100Hz (200 samples = 2 seconds)

unsigned long lastPeakTime = 0;
float respiratoryRate = 0;
bool isPeak = false;

void setup() {
  Serial.begin(115200);
}

void loop() {
  int rawValue = analogRead(PIEZO_PIN);
  unsigned long now = millis();

  // Peak detection with a 'cooldown' to avoid double-counting one breath
  if (rawValue > THRESHOLD && !isPeak) {
    unsigned long interval = now - lastPeakTime;
   
    if (interval > 400) { // Ignores noise faster than 150 breaths/min
      respiratoryRate = 60000.0 / interval;
      lastPeakTime = now;
      isPeak = true;
    }
  }
 
  if (rawValue < (THRESHOLD * 0.7)) {
    isPeak = false; // Reset when signal drops
  }

  // Printing for Plotter: Waveform(Blue), Rate(Orange)
  Serial.print(rawValue);
  Serial.print(",");
  Serial.println(respiratoryRate);

  delay(SAMPLE_DELAY);
}