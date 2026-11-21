import { Composition } from "remotion";
import { LowerThird } from "./LowerThird";
import { Title } from "./Title";
import { Edit } from "./Edit";
import { TitleWords } from "./TitleWords";
import edl from "./edl.json";

export const RemotionRoot: React.FC = () => {
	return (
		<>
			<Composition id="LowerThird" component={LowerThird} durationInFrames={120} fps={30} width={1920} height={1080} />
			<Composition
				id="Title"
				component={Title}
				durationInFrames={45}
				fps={25}
				width={1920}
				height={1080}
				defaultProps={{ line1: "ЧЕЛОВЕК", line2: "АВТОРИТЕТ" }}
			/>
			<Composition id="Edit" component={Edit} durationInFrames={Math.round(edl.TOTAL * 25)} fps={25} width={1920} height={1080} />
			<Composition id="TitleWords" component={TitleWords} durationInFrames={45} fps={25} width={1920} height={1080} defaultProps={{ line1: "ШКОЛЬНЫЙ", line2: "АВТОРИТЕТ" }} />
		</>
	);
};
