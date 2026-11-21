import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";

// Титр в стиле «#1. Человек-нарциссизм»: два слова подряд по центру,
// белый жирный гротеск, мягкий блюр-глоу под текстом, вход/выход через размытие.
export type TitleProps = { line1: string; line2: string };

const FONT = '"Arial", "Helvetica Neue", sans-serif';

const Word: React.FC<{ text: string; from: number; to: number }> = ({ text, from, to }) => {
	const frame = useCurrentFrame();
	const fade = 5; // кадров на вход/выход (0.2 с при 25 fps)
	const inP = interpolate(frame, [from, from + fade], [0, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
		easing: Easing.out(Easing.cubic),
	});
	const outP = interpolate(frame, [to - fade, to], [1, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
		easing: Easing.in(Easing.cubic),
	});
	const p = Math.min(inP, outP);
	if (frame < from || frame > to) return null;
	const blur = (1 - p) * 14;
	const scale = 1 + (1 - p) * 0.04;
	const base: React.CSSProperties = {
		position: "absolute",
		left: 0,
		right: 0,
		top: 0,
		bottom: 0,
		display: "flex",
		alignItems: "center",
		justifyContent: "center",
		fontFamily: FONT,
		fontWeight: 700,
		fontSize: 104,
		letterSpacing: 4,
		color: "white",
		transform: `translateY(330px) scale(${scale})`,
	};
	return (
		<AbsoluteFill>
			{/* блюр-глоу (в оригинале — дубль на V8 с Gaussian Blur + Wonder Glow) */}
			<div style={{ ...base, filter: "blur(16px)", opacity: 0.55 * p }}>{text}</div>
			<div style={{ ...base, filter: `blur(${blur}px)`, opacity: p, textShadow: "0 0 24px rgba(255,255,255,0.3), 0 4px 18px rgba(0,0,0,0.35)" }}>
				{text}
			</div>
		</AbsoluteFill>
	);
};

export const Title: React.FC<TitleProps> = ({ line1, line2 }) => {
	return (
		<AbsoluteFill>
			<Word text={line1} from={0} to={20} />
			<Word text={line2} from={20} to={45} />
		</AbsoluteFill>
	);
};
