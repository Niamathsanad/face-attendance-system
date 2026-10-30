/* camera.js - tiny wrapper around getUserMedia with friendly error messages. */
class Camera {
  constructor(videoEl) { this.video = videoEl; this.stream = null; }

  async start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("This browser cannot access the camera here. Open the site as http://127.0.0.1:5000 or http://localhost:5000 (not a network IP address) and use Chrome, Edge or Firefox.");
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }, audio: false });
    } catch (e) {
      const map = {
        NotAllowedError: "Camera permission was denied. Click the camera icon in the address bar and allow access.",
        NotFoundError: "No camera was found on this computer.",
        NotReadableError: "The camera is in use by another application. Close it (Zoom, Teams, etc.) and retry.",
        OverconstrainedError: "The camera does not support the requested settings."
      };
      throw new Error(map[e.name] || ("Camera error: " + e.message));
    }
    this.video.srcObject = this.stream;
    await this.video.play();
    return this;
  }

  stop() {
    if (this.stream) this.stream.getTracks().forEach(t => t.stop());
    this.stream = null; this.video.srcObject = null;
  }

  get running() { return !!this.stream; }

  /* Grab the current frame as a JPEG data URL (kept in memory only - never saved). */
  capture(maxWidth = 640, quality = 0.85) {
    const vw = this.video.videoWidth, vh = this.video.videoHeight;
    if (!vw || !vh) return null;
    const scale = Math.min(1, maxWidth / vw);
    const c = document.createElement("canvas");
    c.width = Math.round(vw * scale); c.height = Math.round(vh * scale);
    c.getContext("2d").drawImage(this.video, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", quality);
  }
}
window.Camera = Camera;
