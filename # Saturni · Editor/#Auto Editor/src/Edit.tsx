import React from "react";
import { AbsoluteFill, Audio, Easing, Freeze, interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame } from "remotion";
import edl from "./edl.json";

// «#2» — эдит по мотивам «Человек-нарциссизм», собранный кодом: склейки по онсетам музыки,
// цвет по дуге (холодное интро → полный цвет после дропа), «punch» от лица героя, RGB-сплит/тряска/вспышки на ударах.
const FPS = 25;
const T_DROP = edl.T_DROP, T_C0 = edl.T_C0, T_F = edl.T_F, T_END = edl.T_END;
type Clip = { id: string; file: string; at: number; dur: number; zone: string; face?: number[]; freeze?: number; click?: boolean; tag?: string; videoless?: boolean; strobe?: boolean; slow?: number };
const clips = (edl.clips as Clip[]).filter((c) => !c.videoless);

// В групповых кадрах детектор находил чужие лица — центр «punch» задаём руками.
const FACE_OVERRIDE: Record<string, [number, number]> = { a02: [0.4, 0.38], c04: [0.45, 0.3], c05: [0.5, 0.36], c07: [0.47, 0.28], c08: [0.73, 0.28] };

// Удары, на которых включаются вспышка / тряска / RGB-сплит (секунды на таймлайне).
const CLICK_T = (() => {
	const c = clips.find((x) => x.click)!;
	return c.at + c.dur - (c.freeze ?? 0);
})();
const HITS: { t: number; flash: number; shake: number; rgb: number }[] = [
	{ t: T_DROP, flash: 0.9, shake: 26, rgb: 14 },
	{ t: T_C0, flash: 0.45, shake: 16, rgb: 9 },
	{ t: CLICK_T, flash: 0.9, shake: 6, rgb: 5 },
	{ t: T_F, flash: 0.0, shake: 8, rgb: 5 },
];
const decay = (t: number, h: number, k: number) => (t < h ? 0 : Math.exp(-(t - h) / k));

const Shot: React.FC<{ c: Clip; idx: number }> = ({ c, idx }) => {
	const f = useCurrentFrame();
	const n = Math.max(1, Math.round(c.dur * FPS));
	const [fx0, fy0] = FACE_OVERRIDE[c.id] ?? [c.face?.[0] ?? 0.5, c.face?.[1] ?? 0.4];
	let scale = 1,
		rot = 0;
	if (c.zone === "intro") {
		scale = 1 + 0.045 * (f / n); // медленный подъезд
	} else if (c.zone === "final") {
		scale = 1 + 0.09 * Easing.inOut(Easing.quad)(f / n);
	} else {
		const amp = c.tag === "hero" ? 0.13 : c.dur < 0.6 ? 0.07 : 0.1;
		const p = interpolate(f, [0, 7], [1, 0], { extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
		scale = 1.02 + amp * p + 0.03 * (f / n);
		rot = (idx % 2 ? 1 : -1) * 1.1 * p;
		if (c.tag === "line") {
			scale = 1.0 + 0.05 * (f / n);
			rot = 0;
		}
	}
	const freezeFrames = c.freeze ? Math.round(c.freeze * FPS) : 0;
	const style: React.CSSProperties = {
		width: "100%",
		height: "100%",
		objectFit: "cover",
		transform: `scale(${scale}) rotate(${rot}deg)`,
		transformOrigin: `${fx0 * 100}% ${fy0 * 100}%`,
	};
	const vid = <OffthreadVideo src={staticFile(c.file)} muted style={style} />;
	return (
		<AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
			{freezeFrames > 0 && f >= n - freezeFrames ? <Freeze frame={n - freezeFrames - 1}>{vid}</Freeze> : vid}
		</AbsoluteFill>
	);
};

const FONT = '"Arial", "Helvetica Neue", sans-serif';
const TitleSmall: React.FC<{ text: string; from: number; to: number }> = ({ text, from, to }) => {
	const f = useCurrentFrame();
	const fade = 5;
	const p = Math.min(
		interpolate(f, [from, from + fade], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }),
		interpolate(f, [to - fade, to], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
	);
	if (f < from || f > to) return null;
	const base: React.CSSProperties = {
		position: "absolute",
		inset: 0,
		display: "flex",
		alignItems: "center",
		justifyContent: "center",
		fontFamily: FONT,
		fontWeight: 700,
		fontSize: 104,
		letterSpacing: 4,
		color: "white",
		transform: `translateY(330px) scale(${1 + (1 - p) * 0.04})`,
	};
	return (
		<AbsoluteFill>
			<div style={{ ...base, filter: "blur(16px)", opacity: 0.55 * p }}>{text}</div>
			<div style={{ ...base, filter: `blur(${(1 - p) * 14}px)`, opacity: p, textShadow: "0 0 24px rgba(255,255,255,0.3), 0 4px 18px rgba(0,0,0,0.35)" }}>{text}</div>
		</AbsoluteFill>
	);
};

const TitleSlam: React.FC<{ text: string; at: number; hold: number }> = ({ text, at, hold }) => {
	const f = useCurrentFrame();
	const t0 = Math.round(at * FPS),
		t1 = t0 + Math.round(hold * FPS);
	if (f < t0 || f > t1 + 5) return null;
	const inP = interpolate(f, [t0, t0 + 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.exp) });
	const outP = interpolate(f, [t1, t1 + 5], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
	const p = Math.min(inP, outP);
	const base: React.CSSProperties = {
		position: "absolute",
		inset: 0,
		display: "flex",
		alignItems: "center",
		justifyContent: "center",
		fontFamily: FONT,
		fontWeight: 900,
		fontSize: 176,
		letterSpacing: 18 - 10 * inP,
		color: "white",
		transform: `translateY(330px) scale(${1 + (1 - inP) * 0.55})`,
	};
	return (
		<AbsoluteFill>
			<div style={{ ...base, filter: `blur(${18 + (1 - p) * 20}px)`, opacity: 0.6 * p }}>{text}</div>
			<div style={{ ...base, filter: `blur(${(1 - inP) * 26}px)`, opacity: p, textShadow: "0 0 36px rgba(255,255,255,0.35), 0 6px 24px rgba(0,0,0,0.55)" }}>{text}</div>
		</AbsoluteFill>
	);
};

export const Edit: React.FC = () => {
	const f = useCurrentFrame();
	const t = f / FPS;
	// --- дуга цвета ---
	const k = interpolate(t, [T_DROP - 0.04, T_DROP + 0.12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
	const fin = interpolate(t, [T_F - 0.1, T_F + 0.2], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
	const sat = 0.78 + 0.34 * k - 0.12 * fin,
		con = 1.06 + 0.11 * k + 0.05 * fin,
		bri = 0.92 + 0.1 * k - 0.05 * fin;
	// --- удары ---
	let shx = 0,
		shy = 0,
		rgb = 0,
		flash = 0;
	for (const h of HITS) {
		rgb += h.rgb * decay(t, h.t, 0.09);
		const ds = decay(t, h.t, 0.12);
		shx += Math.sin((t - h.t) * 70) * h.shake * ds;
		shy += Math.cos((t - h.t) * 53) * h.shake * 0.7 * ds;
		flash = Math.max(flash, h.flash * decay(t, h.t, 0.06));
	}
	const useRgb = rgb > 0.4;
	const filter = `saturate(${sat.toFixed(3)}) contrast(${con.toFixed(3)}) brightness(${bri.toFixed(3)})${useRgb ? " url(#rgb)" : ""}`;
	const vig = 0.62 - 0.22 * k;
	const fadeIn = interpolate(t, [0, 0.4], [1, 0], { extrapolateRight: "clamp" });
	const fadeOut = interpolate(t, [T_END - 0.8, T_END], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
	const toBlack = Math.max(fadeIn, fadeOut, t >= T_END ? 1 : 0);
	return (
		<AbsoluteFill style={{ background: "#000" }}>
			<svg width="0" height="0" style={{ position: "absolute" }}>
				<defs>
					<filter id="rgb" colorInterpolationFilters="sRGB" x="-5%" y="-5%" width="110%" height="110%">
						<feColorMatrix in="SourceGraphic" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="r" />
						<feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="g" />
						<feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="b" />
						<feOffset in="r" dx={rgb} dy={0} result="ro" />
						<feOffset in="b" dx={-rgb} dy={0} result="bo" />
						<feBlend in="ro" in2="g" mode="screen" result="rg" />
						<feBlend in="rg" in2="bo" mode="screen" />
					</filter>
				</defs>
			</svg>
			<AbsoluteFill style={{ transform: `translate(${shx}px, ${shy}px) scale(${1 + Math.hypot(shx, shy) * 0.0006})`, filter }}>
				{clips.map((c, i) => (
					<Sequence key={c.id} from={Math.round(c.at * FPS)} durationInFrames={Math.max(1, Math.round(c.dur * FPS))} layout="none">
						<AbsoluteFill>
							<Shot c={c} idx={i} />
						</AbsoluteFill>
					</Sequence>
				))}
			</AbsoluteFill>
			<AbsoluteFill style={{ background: `radial-gradient(ellipse at center, rgba(0,0,0,0) 48%, rgba(0,0,0,${vig}) 100%)` }} />
			<AbsoluteFill style={{ transform: `translate(${shx * 0.6}px, ${shy * 0.6}px)`, filter: useRgb ? "url(#rgb)" : undefined }}>
				<TitleSmall text="ЧЕЛОВЕК" from={Math.round(0.6 * FPS)} to={Math.round(1.9 * FPS)} />
				<TitleSlam text="АВТОРИТЕТ" at={T_DROP} hold={1.55} />
			</AbsoluteFill>
			{/* зерно плёнки */}
			<AbsoluteFill style={{ mixBlendMode: "overlay", opacity: 0.16 }}>
				<svg width="100%" height="100%">
					<filter id="grain">
						<feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={f % 97} stitchTiles="stitch" />
						<feColorMatrix type="saturate" values="0" />
					</filter>
					<rect width="100%" height="100%" filter="url(#grain)" />
				</svg>
			</AbsoluteFill>
			<AbsoluteFill style={{ background: "#fff", opacity: flash }} />
			<AbsoluteFill style={{ background: "#000", opacity: toBlack }} />
			<Audio src={staticFile("audio/mix.wav")} />
		</AbsoluteFill>
	);
};
