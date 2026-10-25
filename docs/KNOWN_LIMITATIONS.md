# Known Limitations

1. **Live webcam tracking has not been run end to end on this machine.** The camera-permission
   path was observed (the app reports "Camera unavailable" with instructions). Detection thresholds
   were tuned on synthetic trajectories and may need adjusting for real hands
   (Settings → Analysis: *Beat: min stroke speed*, *Beat: deceleration ratio*).
2. **Beat-reactive sound lags the gesture** by about 150–250 ms (detection lookahead + WebSocket +
   audio output). This is a reactive design, not predictive or sample-accurate synchronisation.
3. **The gesture-similarity estimate is uncalibrated.** `exp(-d/0.35)` was chosen by hand; it is not
   validated against expert ratings and is not a grade.
4. **The reference patterns are schematic** cubic-Bézier drawings of textbook shapes, not motion
   capture of real conductors. Only 4/4 is the supported exercise; 3/4 and 2/4 are included as data.
5. **The first ~2 s of each session are calibration**, and beats in that window are not reported.
6. **Beat-in-bar labels** need one full bar after calibration. Before that, labels are counted or missing.
7. **Instrument models are procedural placeholders** and the **audio is synthesized test audio**
   (no licensed samples). The articulations change the synthesis, but they are not realistic instrument recordings.
8. **HRTF quality depends on the browser's built-in HRTF set.** Localisation needs headphones;
   on laptop speakers, mainly level differences are audible.
9. **WebXR conducting is implemented but untested on hardware.** VR manipulation of Composer
   instruments and AR stage placement are not implemented.
10. **Only one input source is active at a time**, and the service handles a single active session (multiple
    browser tabs share it).
11. **WebXR needs a secure context.** It works on `localhost`, but a headset reaching the laptop over the
    network needs HTTPS, which is not set up.
12. **MediaPipe 0.10.21 pins NumPy < 2 and Python ≤ 3.12.**
13. **Leaving the Conductor screen ends the current session** and releases the camera.
