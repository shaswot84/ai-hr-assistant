# Mouse Trail Effect

A JavaScript package that creates a visually appealing mouse trail effect on web pages. It allows you to customize the appearance and behavior of the mouse trail, making it easy to add an engaging interactive element to your website.

## Features

- Customizable trail length, size, and duration
- Multiple color formats supported (hex, rgb, hsl)
- Random gradient color generation
- Different trail effects: solid color, gradient, and sparkle
- Circular and square trail shapes
- Smooth fading animation for trail elements
- Easy to integrate into any web project

## Installation

You can install the package using npm:

```bash
npm install mouse-trail-effect
```

## Usage

Import the `createMouseTrailEffect` function from the package and call it with desired options to create a mouse trail effect instance. Then, start the effect by calling the `start` method.

```javascript
const createMouseTrailEffect = require('mouse-trail-effect');

const options = {
  trailLength: 15,
  trailSize: 30,
  trailDuration: 600,
  colorFormat: 'rgb',
  colorCount: 3,
  colorSeed: 'myCustomSeed',
  trailEffect: 'sparkle',
  trailShape: 'square',
  customTrailClass: 'my-trail-class',
  zIndex: 10000,
};

const mouseTrailEffect = createMouseTrailEffect(options);
mouseTrailEffect.start();

// To stop the effect
mouseTrailEffect.stop();
```

## Options

| Option           | Type     | Default     | Description                                                    |
|------------------|----------|-------------|----------------------------------------------------------------|
| trailLength      | Number   | 10          | The number of trail elements following the mouse cursor        |
| trailSize        | Number   | 20          | The size of each trail element in pixels                       |
| trailDuration    | Number   | 500         | The duration of the trail animation in milliseconds            |
| colorFormat      | String   | 'hex'       | The color format of the trail elements ('hex', 'rgb', 'hsl')   |
| colorCount       | Number   | 2           | The number of colors used in the trail gradient or sparkle     |
| colorSeed        | String   | null        | A custom seed value for generating random colors               |
| trailEffect      | String   | 'default'   | The visual effect of the trail ('default', 'gradient', 'sparkle') |
| trailShape       | String   | 'circle'    | The shape of the trail elements ('circle', 'square')           |
| customTrailClass | String   | ''          | A custom CSS class name to be added to the trail elements      |
| zIndex           | Number   | 9999        | The z-index value of the trail elements                        |

## Methods

- `start()`: Starts the mouse trail effect.
- `stop()`: Stops the mouse trail effect and removes all trail elements.


## Dependencies

The package relies on the following dependencies:

- `make-random-color`: Generates random gradient colors.
- `d3-interpolate`: Interpolates values for smooth animations.
- `d3-ease`: Provides easing functions for animations.
- `mathjs`: Performs mathematical operations.

Make sure to install these dependencies along with the package.

## License

This package is open-source and available under the [MIT License](https://opensource.org/licenses/MIT).
