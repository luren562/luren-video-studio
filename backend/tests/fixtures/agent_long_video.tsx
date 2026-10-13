import React from 'react';
import {AbsoluteFill, Composition, registerRoot, useCurrentFrame} from 'remotion';
import {AgentScene} from './__agent__/Scene';

const SceneContent: React.FC<{scene: number}> = ({scene}) => {
  const frame = useCurrentFrame();
  const progress = (frame % 450) / 450;
  return <AbsoluteFill style={{background: '#11223b', color: '#f2f7ff', padding: 120, fontFamily: 'Arial'}}>
    <div style={{fontSize: 32, color: '#83bbff'}}>OFFLINE PIPELINE VERIFICATION</div>
    <div style={{fontSize: 100, marginTop: 150}}>Scene {scene + 1} / 20</div>
    <div style={{fontSize: 40, marginTop: 48}}>300 seconds · 9000 frames · 30 fps</div>
    <div style={{height: 24, marginTop: 100, background: '#263f5f', width: '100%'}}>
      <div style={{height: '100%', width: `${progress * 100}%`, background: '#83bbff'}} />
    </div>
    <div style={{marginTop: 70, width: 80, height: 80, borderRadius: 40,
      background: '#fdc674', transform: `translateX(${progress * 1400}px)`}} />
  </AbsoluteFill>;
};

const Film: React.FC = () => <>{Array.from({length: 20}, (_, i) =>
  <AgentScene index={i} key={i}><SceneContent scene={i} /></AgentScene>)}</>;

registerRoot(() => <Composition id="LongVideoCheck" component={Film}
  width={1920} height={1080} fps={30} durationInFrames={9000} />);
