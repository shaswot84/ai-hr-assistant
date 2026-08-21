const { generateRandomGradientColors } = require('make-random-color');
const { interpolateRgb } = require('d3-interpolate');
const { easeQuadInOut } = require('d3-ease');
const { randomInt } = require('mathjs');

function createTrailElement(options) {
  const { trailSize, colorFormat, colorCount, colorSeed, trailEffect, trailShape, customTrailClass, zIndex } = options;

  const trailElement = document.createElement('div');
  trailElement.className = `mouse-trail ${customTrailClass}`;
  trailElement.style.width = `${trailSize}px`;
  trailElement.style.height = `${trailSize}px`;
  trailElement.style.position = 'fixed';
  trailElement.style.pointerEvents = 'none';
  trailElement.style.zIndex = zIndex;

  const colors = generateRandomGradientColors({
    format: colorFormat,
    count: colorCount,
    seed: colorSeed,
  });

  if (trailShape === 'circle') {
    trailElement.style.borderRadius = '50%';
  } else if (trailShape === 'square') {
    trailElement.style.borderRadius = '0';
  }

  if (trailEffect === 'gradient') {
    trailElement.style.background = `linear-gradient(${colors.join(', ')})`;
  } else if (trailEffect === 'sparkle') {
    const sparkleColor = colors[randomInt(0, colors.length - 1)];
    trailElement.style.backgroundColor = sparkleColor;
    trailElement.style.boxShadow = `0 0 5px ${sparkleColor}, 0 0 10px ${sparkleColor}, 0 0 15px ${sparkleColor}`;
  } else {
    trailElement.style.backgroundColor = colors[0];
  }

  return trailElement;
}

module.exports = {
  createTrailElement,
};
