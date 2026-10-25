// WebXR controller conducting input. The controller's position is mapped into
// the shared normalized trajectory space and sent to the SAME analysis
// pipeline as webcam and mouse input. Requires a WebXR-capable headset and
// browser; it has not been verified on hardware in this project.
import * as THREE from "three";

// Controller space (metres, local-floor) -> normalized 0..1 trajectory space.
const SPAN_M = 1.0;          // a 1 m movement box maps to the full [0, 1] range
const CENTER_Y_M = 1.3;      // typical chest height

export class XRConductingInput {
  constructor(link) {
    this.link = link;
    this.session = null;
    this.buf = [];
    this.flash = 0;
  }

  async checkSupport() {
    if (!window.isSecureContext) return { supported: false, message: "WebXR needs a secure context (https or localhost)." };
    if (!navigator.xr) return { supported: false, message: "WebXR is not available in this browser. Use Mouse or Webcam input on a laptop." };
    try {
      const ok = await navigator.xr.isSessionSupported("immersive-vr");
      return ok
        ? { supported: true, message: "Headset detected. Select VR input, press Start, then enter VR." }
        : { supported: false, message: "No immersive VR runtime/headset detected." };
    } catch (e) {
      return { supported: false, message: `WebXR check failed: ${e.message}` };
    }
  }

  async enter() {
    const session = await navigator.xr.requestSession("immersive-vr", { optionalFeatures: ["local-floor"] });
    this.session = session;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.xr.enabled = true;
    renderer.xr.setReferenceSpaceType("local-floor");
    await renderer.xr.setSession(session);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0e1014);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x222233, 1.2));
    const grid = new THREE.GridHelper(10, 20, 0x333a47, 0x1f242d);
    scene.add(grid);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.6, 0.015, 8, 64),
      new THREE.MeshBasicMaterial({ color: 0x5cc8c2 }));
    ring.position.set(0, CENTER_Y_M, -1.5);
    scene.add(ring);
    const controller = renderer.xr.getController(0);
    controller.add(new THREE.Mesh(new THREE.SphereGeometry(0.02), new THREE.MeshBasicMaterial({ color: 0xd8a24a })));
    scene.add(controller);
    const camera = new THREE.PerspectiveCamera(70, 1, 0.05, 50);
    const flush = setInterval(() => {
      if (this.buf.length) this.link.samples("webxr", this.buf.splice(0, 200));
    }, 33);

    renderer.setAnimationLoop((time) => {
      const p = controller.position;
      if (controller.visible !== false && (p.x !== 0 || p.y !== 0 || p.z !== 0)) {
        this.buf.push([time / 1000, 0.5 + p.x / SPAN_M, 0.5 + (p.y - CENTER_Y_M) / SPAN_M, 1]);
      }
      this.flash = Math.max(0, this.flash - 0.05);
      ring.material.color.setRGB(0.36 + this.flash * 0.6, 0.78, 0.76);
      ring.scale.setScalar(1 + this.flash * 0.15);
      renderer.render(scene, camera);
    });
    session.addEventListener("end", () => {
      clearInterval(flush);
      renderer.setAnimationLoop(null);
      renderer.dispose();
      this.session = null;
    });
  }

  /** Visual + haptic beat cue. Haptics only when the controller reports an actuator. */
  onBeat() {
    this.flash = 1;
    if (!this.session) return;
    for (const src of this.session.inputSources) {
      const act = src.gamepad && src.gamepad.hapticActuators && src.gamepad.hapticActuators[0];
      if (act && typeof act.pulse === "function") act.pulse(0.5, 35).catch(() => {});
    }
  }
}
