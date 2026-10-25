# Known Limitations

1. **Beat-detection thresholds are tuned on synthetic webcam-like data, not yet on real recordings.**
   The webcam itself works on the dev Mac (the camera opened after permission was granted, and MediaPipe ran).
   Live sessions are now saved to `data/recordings/`, so the thresholds can be checked against real movement
   with `python -m archestral analyze data/recordings/<file>.json`.
   Remaining weak spots in simulation: sideways beats with almost no bounce are missed about 15% of the time,
   and a small, far-away hand at slow tempos (≈60 BPM) can give an unstable tempo. The app warns about the
   second case ("move closer or conduct bigger").
2. **Beat-reactive sound lags the gesture** by about 150–250 ms (detection lookahead + WebSocket +
   audio output). This is a reactive design, not predictive or sample-accurate synchronisation.
3. **The gesture-similarity estimate is not validated.** It is anchored between a textbook bar (1) and
   random hand motion (0), both measured on synthetic data, not against expert ratings, and it is not a grade.
   In the first real webcam sessions (one person), bars scored about as far from the template as random
   motion (d ≈ 0.6), so the template and/or the comparison window need real conductor data before this
   number means much.
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
