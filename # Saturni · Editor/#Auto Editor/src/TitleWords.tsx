import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

// Точная копия анимации титра из «#1. Человек-нарциссизм» (вложенная секвенция `t`):
//  слово 1: 0–0.8 с, прозрачность 0→100 (0.04–0.24), держим до 0.56, → 0 к 0.76; масштаб 100→110 за 0.6 с
//  слово 2: 0.8–1.8 с, прозрачность 0→100 (0.04–0.24), держим до 0.56, → 0 к 0.92; масштаб 95→107 за 0.8 с
// Текст ровный белый без свечения — Wonder Glow / Gaussian Blur остаются на клипах V7/V8 в Премьере, как у автора.
// Шрифт по метрике совпал с Arial Bold ~109 px (ширина «НАРЦИССИЗМ» = 784 px), базовая линия y=577, центр x=957.
export type TitleWordsProps = { line1: string; line2: string };
const FPS = 25;
const FONT = '"Arial", "Helvetica Neue", sans-serif';

const Word: React.FC<{ text: string; start: number; opKeys: number[][]; sc: number[]; scDur: number }> = ({ text, start, opKeys, sc, scDur }) => {
	const f = useCurrentFrame();
	const t = f / FPS - start;
	if (t < 0) return null;
	const op = interpolate(t, opKeys.map((k) => k[0]), opKeys.map((k) => k[1]), { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) / 100;
	const s = interpolate(t, [0, scDur], sc, { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) / 100;
	if (op <= 0) return null;
	return (
		<AbsoluteFill style={{ opacity: op, transform: `scale(${s})`, transformOrigin: "50% 50%" }}>
			<svg width="1920" height="1080" viewBox="0 0 1920 1080">
				<text x="957" y="577" textAnchor="middle" fontFamily={FONT} fontWeight={700} fontSize={109} fill="white">
					{text}
				</text>
			</svg>
		</AbsoluteFill>
	);
};

export const TitleWords: React.FC<TitleWordsProps> = ({ line1, line2 }) => {
	return (
		<AbsoluteFill>
			<Word text={line1} start={0} opKeys={[[0, 0], [0.04, 0], [0.24, 100], [0.56, 100], [0.76, 0]]} sc={[100, 110]} scDur={0.6} />
			<Word text={line2} start={0.8} opKeys={[[0, 0], [0.04, 0], [0.24, 100], [0.56, 100], [0.92, 0]]} sc={[95, 107]} scDur={0.8} />
		</AbsoluteFill>
	);
};
