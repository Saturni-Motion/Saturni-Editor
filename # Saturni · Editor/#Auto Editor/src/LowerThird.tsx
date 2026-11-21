import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const LowerThird = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame, fps, config: { damping: 200 } });
  const out = interpolate(frame, [80, 100], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const x = interpolate(p, [0, 1], [-600, 0]);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", padding: 120 }}>
      <div style={{ transform: `translateX(${x}px)`, opacity: out, display: "flex", gap: 24, alignItems: "center" }}>
        <div style={{ width: 12, height: 110, background: "#ff3d5a", borderRadius: 6 }} />
        <div style={{ color: "white", fontFamily: "sans-serif", textShadow: "0 4px 20px rgba(0,0,0,.6)" }}>
          <div style={{ fontSize: 72, fontWeight: 800 }}>Тестовая плашка</div>
          <div style={{ fontSize: 36, opacity: 0.8 }}>Remotion → Premiere</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
