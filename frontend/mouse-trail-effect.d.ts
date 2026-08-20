declare module "mouse-trail-effect" {
  interface MouseTrailOptions {
    trailLength?: number;
    trailSize?: number;
    trailDuration?: number;
    colorFormat?: string;
    colorCount?: number;
    colorSeed?: number | null;
    trailEffect?: string;
    trailShape?: string;
    customTrailClass?: string;
    zIndex?: number;
  }

  interface MouseTrailInstance {
    start: () => void;
    stop: () => void;
  }

  function createMouseTrailEffect(options?: MouseTrailOptions): MouseTrailInstance;
  export default createMouseTrailEffect;
}
