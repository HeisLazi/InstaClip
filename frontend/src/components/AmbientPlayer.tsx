/**
 * Ambient-mode video player.
 * Periodically samples the current frame onto a hidden canvas, averages the
 * pixels to a dominant colour, and projects a soft glow behind the player.
 * Doc reference: "Ambient Mode and Subconscious Visual Flourishes".
 */

import { useEffect, useRef, useState } from "react";

interface AmbientPlayerProps {
  src: string;
  /** Forwarded to <video>. */
  videoKey?: string;
  className?: string;
  autoPlay?: boolean;
  onEnded?: () => void;
}

export function AmbientPlayer({ src, videoKey, className, autoPlay = false, onEnded }: AmbientPlayerProps) {
  const videoRef  = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [glow, setGlow] = useState<string>("rgba(0,0,0,0)");

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (!canvasRef.current) {
      canvasRef.current = document.createElement("canvas");
      canvasRef.current.width = 32;
      canvasRef.current.height = 18;
    }
    const ctx = canvasRef.current.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;

    let raf: number | null = null;
    let timer: number | null = null;
    let lastSampleAt = 0;
    const INTERVAL_MS = 300;  // sample at ~3 fps — plenty for glow

    function sample() {
      const v = videoRef.current;
      if (!v || v.paused || v.ended || !ctx || !canvasRef.current) {
        return;
      }
      const now = performance.now();
      if (now - lastSampleAt < INTERVAL_MS) return;
      lastSampleAt = now;

      try {
        ctx.drawImage(v, 0, 0, canvasRef.current.width, canvasRef.current.height);
        const { data } = ctx.getImageData(0, 0, canvasRef.current.width, canvasRef.current.height);
        // Skip near-black pixels so very dark scenes don't kill the glow.
        let r = 0, g = 0, b = 0, count = 0;
        for (let i = 0; i < data.length; i += 4) {
          const pr = data[i], pg = data[i + 1], pb = data[i + 2];
          const lum = pr + pg + pb;
          if (lum < 60) continue;
          r += pr; g += pg; b += pb; count += 1;
        }
        if (count > 0) {
          r = Math.floor(r / count);
          g = Math.floor(g / count);
          b = Math.floor(b / count);
          setGlow(`rgb(${r}, ${g}, ${b})`);
        }
      } catch {
        // Cross-origin canvas read can throw — backend sets explicit headers
        // and we hit it same-origin via 127.0.0.1, so we shouldn't hit this.
      }
    }

    function loop() {
      sample();
      raf = requestAnimationFrame(loop);
    }
    function onPlay() {
      if (raf == null) loop();
    }
    function onPauseOrEnd() {
      if (raf != null) { cancelAnimationFrame(raf); raf = null; }
    }
    video.addEventListener("play",  onPlay);
    video.addEventListener("pause", onPauseOrEnd);
    video.addEventListener("ended", onPauseOrEnd);

    // Sample once immediately so a paused video also gets coloured.
    timer = window.setTimeout(sample, 250);

    return () => {
      if (raf != null) cancelAnimationFrame(raf);
      if (timer != null) clearTimeout(timer);
      video.removeEventListener("play",  onPlay);
      video.removeEventListener("pause", onPauseOrEnd);
      video.removeEventListener("ended", onPauseOrEnd);
    };
  }, [src]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !autoPlay) return;
    void video.play().catch(() => {
      // Browser autoplay policies may still require one click outside Tauri.
    });
  }, [autoPlay, src]);

  return (
    <div className={"relative flex items-center justify-center min-h-[280px] " + (className ?? "")}>
      {/* Glow */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background: `radial-gradient(60% 80% at 50% 50%, ${glow}55 0%, ${glow}1a 50%, transparent 78%)`,
          filter: "blur(48px) saturate(140%)",
          transition: "background 600ms ease-out",
        }}
      />
      <video
        ref={videoRef}
        key={videoKey ?? src}
        src={src}
        controls
        autoPlay={autoPlay}
        onEnded={onEnded}
        preload="auto"
        crossOrigin="anonymous"
        className="relative z-10 max-w-full max-h-[60vh] object-contain rounded-md shadow-[0_0_40px_rgba(0,0,0,0.6)]"
      />
    </div>
  );
}
