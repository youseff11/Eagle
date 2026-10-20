import { useEffect, useRef, useState } from "react";
import { usePreferences } from "../i18n/Preferences";
import { CELEBRATE_EVENT, type CelebrateDetail } from "../lib/celebrate";
import { cheer } from "../lib/chime";
import { Icon } from "./Icon";

/** How long the card stays: the confetti is down by then. */
const SHOW_MS = 5500;
const PIECES = 160;
const COLOURS = ["#d9a441", "#e8b45a", "#4ec9a0", "#6e8bff", "#e5484d", "#f5d76e", "#ffffff"];

interface Piece {
  x: number;
  y: number;
  vx: number;
  vy: number;
  spin: number;
  turn: number;
  w: number;
  h: number;
  colour: string;
}

/** Confetti thrown up from the two bottom corners, falling with a little drag. Stops by itself. */
function throwConfetti(canvas: HTMLCanvasElement): () => void {
  const draw = canvas.getContext("2d");
  if (!draw) return () => undefined;
  const width = (canvas.width = window.innerWidth);
  const height = (canvas.height = window.innerHeight);
  const pieces: Piece[] = Array.from({ length: PIECES }, (_, i) => {
    const left = i % 2 === 0;
    return {
      x: left ? width * 0.05 : width * 0.95,
      y: height,
      vx: (left ? 1 : -1) * (4 + Math.random() * 9),
      vy: -(14 + Math.random() * 12),
      spin: Math.random() * Math.PI,
      turn: (Math.random() - 0.5) * 0.3,
      w: 6 + Math.random() * 6,
      h: 10 + Math.random() * 8,
      colour: COLOURS[i % COLOURS.length],
    };
  });
  let frame = 0;
  const step = () => {
    draw.clearRect(0, 0, width, height);
    let alive = 0;
    for (const piece of pieces) {
      piece.vy += 0.35;
      piece.vx *= 0.985;
      piece.vy *= 0.985;
      piece.x += piece.vx;
      piece.y += piece.vy;
      piece.spin += piece.turn;
      if (piece.y < height + 20) alive += 1;
      draw.save();
      draw.translate(piece.x, piece.y);
      draw.rotate(piece.spin);
      draw.fillStyle = piece.colour;
      draw.fillRect(-piece.w / 2, -piece.h / 2, piece.w, piece.h * Math.abs(Math.cos(piece.spin)));
      draw.restore();
    }
    if (alive > 0) frame = requestAnimationFrame(step);
  };
  frame = requestAnimationFrame(step);
  return () => cancelAnimationFrame(frame);
}

/** The party for a contract won on this screen (`lib/celebrate`): over every page, gone by itself or on a click. */
export function Celebration() {
  const { t } = usePreferences();
  const [company, setCompany] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const on = (event: Event) => {
      setCompany((event as CustomEvent<CelebrateDetail>).detail?.company ?? "");
      setRound((n) => n + 1);
      cheer();
    };
    window.addEventListener(CELEBRATE_EVENT, on);
    return () => window.removeEventListener(CELEBRATE_EVENT, on);
  }, []);

  useEffect(() => {
    if (company === null) return;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const stop = canvas.current && !still ? throwConfetti(canvas.current) : () => undefined;
    const done = window.setTimeout(() => setCompany(null), SHOW_MS);
    return () => {
      stop();
      window.clearTimeout(done);
    };
  }, [company, round]);

  if (company === null) return null;
  return (
    <div className="celebrate" role="status" onClick={() => setCompany(null)}>
      <canvas ref={canvas} className="celebrate__confetti" aria-hidden="true" />
      <div className="celebrate__card" key={round}>
        <Icon name="sparkles" size="xl" />
        <strong className="celebrate__title">{t("مبروك! تعاقد جديد", "Congratulations! A new contract")}</strong>
        {company && <span className="celebrate__company">{company}</span>}
        <span className="celebrate__line">{t("شغل عظيم، كمّل كده", "Great work, keep it up")}</span>
      </div>
    </div>
  );
}
