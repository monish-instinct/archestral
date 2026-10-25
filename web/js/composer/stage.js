// Procedural 3D stage and PLACEHOLDER instrument models (no external assets).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export class Stage {
  constructor(host, stageDef) {
    this.host = host;
    this.def = stageDef;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.append(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0e1014);
    this.scene.fog = new THREE.Fog(0x0e1014, 22, 45);
    this.camera = new THREE.PerspectiveCamera(48, 1, 0.1, 200);
    this.camera.position.set(0, 7.5, 12.5);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, 0.6, -1.2);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = 1.45;
    this.controls.minDistance = 4;
    this.controls.maxDistance = 32;
    this.controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
    this._build();
    this._resize = () => this.resize();
    window.addEventListener("resize", this._resize);
    this.resize();
  }

  _build() {
    const s = this.def;
    const scene = this.scene;
    scene.add(new THREE.HemisphereLight(0xdfe6ff, 0x1b1712, 0.9));
    const key = new THREE.DirectionalLight(0xfff1dc, 1.6);
    key.position.set(6, 12, 8);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12 });
    scene.add(key);
    const spot = new THREE.SpotLight(0xffd59a, 40, 30, 0.55, 0.6);
    spot.position.set(0, 10, 2);
    spot.target.position.set(0, 0, -1.5);
    scene.add(spot, spot.target);

    const floor = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.MeshStandardMaterial({ color: 0x121419, roughness: 1 }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.21;
    floor.receiveShadow = true;
    scene.add(floor);

    const depth = s.depth_front + s.depth_back + 1.6;
    const deck = new THREE.Mesh(new THREE.BoxGeometry(s.half_width * 2 + 1, 0.2, depth),
      new THREE.MeshStandardMaterial({ color: 0x3a2a1c, roughness: 0.75 }));
    deck.position.set(0, -0.1, (s.depth_front + 1.6 - s.depth_back) / 2);
    deck.receiveShadow = true;
    scene.add(deck);
    this.deck = deck;

    // Placement area outline + grid
    const area = new THREE.Group();
    const lineMat = new THREE.LineBasicMaterial({ color: 0x564431, transparent: true, opacity: 0.6 });
    const pts = [];
    const g = s.grid || 0.5;
    for (let x = -s.half_width; x <= s.half_width + 1e-6; x += g) pts.push(x, 0.005, -s.depth_back, x, 0.005, s.depth_front);
    for (let z = -s.depth_back; z <= s.depth_front + 1e-6; z += g) pts.push(-s.half_width, 0.005, z, s.half_width, 0.005, z);
    const gridGeo = new THREE.BufferGeometry();
    gridGeo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    area.add(new THREE.LineSegments(gridGeo, lineMat));
    const edge = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-s.half_width, 0.01, -s.depth_back), new THREE.Vector3(s.half_width, 0.01, -s.depth_back),
      new THREE.Vector3(s.half_width, 0.01, s.depth_front), new THREE.Vector3(-s.half_width, 0.01, s.depth_front),
    ]), new THREE.LineBasicMaterial({ color: 0xd8a24a, transparent: true, opacity: 0.55 }));
    area.add(edge);
    scene.add(area);
    this.gridArea = area;

    // Podium
    const [px, , pz] = s.podium;
    const podium = new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.75, 0.25, 32),
      new THREE.MeshStandardMaterial({ color: 0x2b2f38, roughness: 0.6 }));
    podium.position.set(px, 0.125, pz);
    podium.castShadow = podium.receiveShadow = true;
    scene.add(podium);
    scene.add(makeLabel("Podium", "#a9b0bf", 0.5)).position.set(px, 0.6, pz + 0.9);

    // Listener marker (head + facing cone)
    const listener = new THREE.Group();
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.16, 24, 16), new THREE.MeshStandardMaterial({ color: 0x5cc8c2, emissive: 0x0d3533 }));
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.22, 16), new THREE.MeshStandardMaterial({ color: 0x5cc8c2 }));
    nose.rotation.x = -Math.PI / 2;
    nose.position.z = -0.22;
    listener.add(head, nose);
    const llabel = makeLabel("Listener", "#5cc8c2", 0.45);
    llabel.position.y = 0.42;
    listener.add(llabel);
    scene.add(listener);
    this.listenerMarker = listener;

    // Audience seating
    const seatMat = new THREE.MeshStandardMaterial({ color: 0x2a1f24, roughness: 0.9 });
    const seatGeo = new THREE.BoxGeometry(0.5, 0.45, 0.5);
    const seats = new THREE.InstancedMesh(seatGeo, seatMat, 7 * 15);
    const m = new THREE.Matrix4();
    let i = 0;
    for (let r = 0; r < 7; r++) {
      for (let c = 0; c < 15; c++) {
        m.makeTranslation((c - 7) * 0.75, 0.0 + r * 0.12, 8.5 + r * 0.9);
        seats.setMatrixAt(i++, m);
      }
    }
    scene.add(seats);
  }

  resize() {
    const r = this.host.getBoundingClientRect();
    if (!r.width || !r.height) return;
    this.renderer.setSize(r.width, r.height, false);
    this.renderer.domElement.style.width = `${r.width}px`;
    this.renderer.domElement.style.height = `${r.height}px`;
    this.camera.aspect = r.width / r.height;
    this.camera.updateProjectionMatrix();
  }

  render() {
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  /** Ray from a pointer event; returns {hitUid, point} with point on the y=0 plane. */
  pick(ev, objects) {
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const hits = ray.intersectObjects(objects, true);
    let hitUid = null;
    for (const h of hits) {
      let o = h.object;
      while (o && !o.userData.uid) o = o.parent;
      if (o) { hitUid = o.userData.uid; break; }
    }
    const point = new THREE.Vector3();
    const ok = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), point);
    return { hitUid, point: ok ? point : null };
  }
}

// ---------------------------------------------------------------- labels
export function makeLabel(text, color = "#e7e9ee", height = 0.4, sub = null) {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  const font = "600 44px ui-sans-serif, -apple-system, system-ui";
  ctx.font = font;
  const w = Math.ceil(Math.max(ctx.measureText(text).width, sub ? ctx.measureText(sub).width * 0.6 : 0)) + 36;
  canvas.width = w;
  canvas.height = sub ? 100 : 64;
  ctx.font = font;
  ctx.fillStyle = "rgba(14,16,20,0.78)";
  roundRect(ctx, 0, 0, canvas.width, canvas.height, 14);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.textBaseline = "middle";
  ctx.fillText(text, 18, 32);
  if (sub) {
    ctx.font = "500 26px ui-sans-serif, system-ui";
    ctx.fillStyle = "#7c8496";
    ctx.fillText(sub, 18, 76);
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  sprite.scale.set((height * canvas.width) / 64, (height * canvas.height) / 64, 1);
  sprite.renderOrder = 10;
  return sprite;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

// ---------------------------------------------------------------- placeholder models
function mat(color, opts = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.05, ...opts });
}

function stand(height) {
  const g = new THREE.Group();
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, height, 8), mat(0x3a3f4a));
  pole.position.y = height / 2;
  const foot = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.2, 0.03, 16), mat(0x3a3f4a));
  g.add(pole, foot);
  return g;
}

function buildShape(kind, color) {
  const g = new THREE.Group();
  const c = new THREE.Color(color);
  switch (kind) {
    case "placeholder:violin": {
      g.add(stand(0.95));
      const body = new THREE.Group();
      const lower = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), mat(c));
      lower.scale.set(0.13, 0.04, 0.12);
      lower.position.z = 0.07;
      const upper = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), mat(c));
      upper.scale.set(0.11, 0.04, 0.1);
      upper.position.z = -0.08;
      const neck = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.03, 0.3), mat(0x1c1c1c));
      neck.position.z = -0.3;
      const scroll = new THREE.Mesh(new THREE.SphereGeometry(0.03, 12, 8), mat(c.clone().multiplyScalar(0.7)));
      scroll.position.z = -0.46;
      body.add(lower, upper, neck, scroll);
      body.rotation.x = -0.35;
      body.position.y = 1.05;
      g.add(body);
      break;
    }
    case "placeholder:cello": {
      const body = new THREE.Group();
      const lower = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), mat(c));
      lower.scale.set(0.27, 0.3, 0.1);
      lower.position.y = 0.45;
      const upper = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), mat(c));
      upper.scale.set(0.22, 0.24, 0.09);
      upper.position.y = 0.85;
      const neck = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.55, 0.04), mat(0x1c1c1c));
      neck.position.y = 1.3;
      const pin = new THREE.Mesh(new THREE.CylinderGeometry(0.01, 0.01, 0.25, 6), mat(0x888888));
      pin.position.y = 0.1;
      body.add(lower, upper, neck, pin);
      body.rotation.x = -0.15;
      g.add(body);
      break;
    }
    case "placeholder:flute": {
      g.add(stand(1.1));
      const tube = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.68, 12), mat(c, { metalness: 0.8, roughness: 0.25 }));
      tube.rotation.z = Math.PI / 2;
      tube.position.y = 1.18;
      g.add(tube);
      break;
    }
    case "placeholder:horn": {
      g.add(stand(0.9));
      const coil = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.03, 12, 32), mat(c, { metalness: 0.75, roughness: 0.3 }));
      coil.position.y = 1.08;
      const bell = new THREE.Mesh(new THREE.ConeGeometry(0.16, 0.32, 24, 1, true), mat(c, { metalness: 0.75, roughness: 0.3, side: THREE.DoubleSide }));
      bell.rotation.x = Math.PI / 2;          // opens toward +z (the facing direction)
      bell.position.set(0.12, 1.02, 0.2);
      g.add(coil, bell);
      break;
    }
    case "placeholder:timpani": {
      for (const [x, r] of [[-0.42, 0.36], [0.42, 0.31]]) {
        const kettle = new THREE.Mesh(new THREE.SphereGeometry(r, 24, 12, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), mat(0xa66b3a, { metalness: 0.6, roughness: 0.35 }));
        kettle.position.set(x, 0.72, 0);
        const head = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.02, 24), mat(0xe8dcc0));
        head.position.set(x, 0.72, 0);
        const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.05, 0.4, 8), mat(0x3a3f4a));
        leg.position.set(x, 0.2, 0);
        g.add(kettle, head, leg);
      }
      break;
    }
    default: {
      const box = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.8, 0.4), mat(c));
      box.position.y = 0.4;
      g.add(box);
    }
  }
  g.traverse((o) => { if (o.isMesh) o.castShadow = true; });
  return g;
}

/** Interactive instrument view: base disc, facing arrow, selection ring, model and label. */
export function buildInstrumentView(def, uid) {
  const root = new THREE.Group();
  root.userData.uid = uid;
  const base = new THREE.Mesh(new THREE.CircleGeometry(0.45, 40), new THREE.MeshStandardMaterial({ color: 0x232833, roughness: 0.9 }));
  base.rotation.x = -Math.PI / 2;
  base.position.y = 0.012;
  base.receiveShadow = true;
  const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.09, 0.2, 3), new THREE.MeshBasicMaterial({ color: 0x7c8496 }));
  arrow.rotation.x = Math.PI / 2;
  arrow.position.set(0, 0.03, 0.52);
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.48, 0.56, 48), new THREE.MeshBasicMaterial({ color: 0xd8a24a, transparent: true, opacity: 0, side: THREE.DoubleSide }));
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.02;
  const model = buildShape(def.model, def.color);
  const label = makeLabel(def.name, "#e7e9ee", 0.36, "placeholder model");
  label.position.y = 1.75;
  // invisible pick volume so thin models are easy to grab
  const hit = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 1.5, 12), new THREE.MeshBasicMaterial({ visible: false }));
  hit.position.y = 0.75;
  root.add(base, arrow, ring, model, label, hit);
  root.userData.parts = { ring, model, label, arrow };
  return root;
}

export function setRing(view, state) {
  const ring = view.userData.parts.ring;
  if (state === "selected") { ring.material.color.set(0xd8a24a); ring.material.opacity = 1; }
  else if (state === "invalid") { ring.material.color.set(0xe5675a); ring.material.opacity = 1; }
  else if (state === "playing") { ring.material.color.set(0x5cc8c2); ring.material.opacity = 0.5; }
  else ring.material.opacity = 0;
}
