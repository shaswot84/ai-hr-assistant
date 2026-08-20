const defaultConfig = require('./config');
const { createTrailElement } = require('./utils');

function createMouseTrailEffect(options = {}) {
  const config = { ...defaultConfig, ...options };
  const { trailLength, trailDuration } = config;

  const trail = [];
  let mouseX = 0;
  let mouseY = 0;
  let animationFrameId = null;

  function updateMousePosition(event) {
    mouseX = event.clientX;
    mouseY = event.clientY;
  }

  function animateTrail() {
    const trailElement = createTrailElement(config);
    trailElement.style.left = `${mouseX - config.trailSize / 2}px`;
    trailElement.style.top = `${mouseY - config.trailSize / 2}px`;
    document.body.appendChild(trailElement);
    trail.push(trailElement);

    if (trail.length > trailLength) {
      const expiredTrail = trail.shift();
      expiredTrail.remove();
    }

    const ease = easeQuadInOut;
    const duration = trailDuration;
    const start = performance.now();

    function step(timestamp) {
      const elapsed = timestamp - start;
      const t = Math.min(elapsed / duration, 1);
      const eased = ease(t);
      trailElement.style.opacity = interpolateRgb(1, 0)(eased);

      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        trailElement.remove();
        trail.splice(trail.indexOf(trailElement), 1);
      }
    }

    requestAnimationFrame(step);
    animationFrameId = requestAnimationFrame(animateTrail);
  }

  function startMouseTrailEffect() {
    document.addEventListener('mousemove', updateMousePosition);
    animationFrameId = requestAnimationFrame(animateTrail);
  }

  function stopMouseTrailEffect() {
    document.removeEventListener('mousemove', updateMousePosition);
    cancelAnimationFrame(animationFrameId);
    trail.forEach((trailElement) => trailElement.remove());
    trail.length = 0;
  }

  return {
    start: startMouseTrailEffect,
    stop: stopMouseTrailEffect,
  };
}

module.exports = createMouseTrailEffect;
