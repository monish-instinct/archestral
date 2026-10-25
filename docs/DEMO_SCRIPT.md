# 5-Minute Demo Script

**Before the demo (once):** run `./run.sh`, open Conductor → Webcam → Start, and allow camera
access when macOS asks. Close the app again with Ctrl+C. Bring headphones for the Composer part.

## 0. Launch (20 s)
```bash
./run.sh
```
The browser opens at `http://127.0.0.1:8765`. Point out the three status chips (Service, Input,
Audio) and say that everything runs locally: no cloud, no GPU, no headset required.

## 1. Conductor with test data: show the pipeline works (60 s)
1. **Conductor** → input **Test data** → *Reference 4/4 at 90 BPM* → **Start**.
2. Narrate: the first 2 s are calibration. Then beats appear on the pad as numbered rings
   (1 = downbeat, gold), the beat dots light up, and the chorale plays on each detected beat.
3. Point at the metrics: *Estimated tempo ≈ 90 BPM*, *Tempo deviation ≈ 0%*, *Gesture similarity
   ≈ 0.86 (prototype)*. **Stop**, choose *Faster 4/4 at 120 BPM*, **Start** again: the deviation reads about +33%.
4. Mention the yellow banner: this input is **synthetic test data**, clearly separated from live tracking.

## 2. Conductor with your hand (90 s)
1. Input **Webcam** → **Start**. Hold your right hand up so the wrist is visible (turn on *Show camera preview* to show the landmarks).
2. Conduct 4/4 (down, left, right, up) at a steady tempo for a few bars.
3. Show that tempo follows your speed, the chorale follows your beats, and bigger gestures play louder (the
   *p / mp / mf / f* marking next to the beat dots).
4. Drop your hand out of view: the "Tracking lost" banner appears and the confidence bar falls.
5. **Stop** → the Results page: tempo over time, timing error, beats per position.
   *(No camera? Use **Mouse** input and draw the pattern in the pad.)*

## 3. Composer: spatial orchestration (90 s)
1. **Composer**, headphones on, **Play**. *Standard seating* loads: violins left, cellos right,
   woodwinds and brass behind, timpani at the back. The listener is on the podium.
2. Click the **Violin** → **Solo** → open **Audio diagnostics**. Drag the violin from the left to the
   right of the stage: the measured L/R meters swap and the azimuth readout changes.
3. Change the articulation to **Pizzicato**: you hear a plucked sound (a different synthesis, not just a label).
   *Col legno* is disabled and explains why.
4. Rotate the **French Horn** to 180° (Q/E keys): its directional cone now points away and it gets quieter.
5. Switch *Listen from* to **Audience**: everything sounds more distant and reverberant.

## 4. A/B comparison (40 s)
1. **A/B compare** → A = *Standard seating*, B = *Antiphonal seating*. The table lists the measured
   differences (moved metres, volume dB, articulation, listener).
2. **Listen A/B**, then switch between A and B while playing. Note that the tool reports differences;
   it does not claim one arrangement is better.

## 5. Close (20 s)
- Diagnostics page: live service/input/audio state and the event log.
- Engineering: 87 Python + 12 JS automated tests, a versioned protocol, and validated persistence.
- Honest limitations: placeholder models, synthesized audio, an uncalibrated similarity estimate, and VR not tested on hardware.
