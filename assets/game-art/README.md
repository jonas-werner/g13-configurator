# Optional LCD artwork

These images and animations are editable examples for profile splash screens
and GIF views. The application does not require them; profiles may reference
compatible `160x43` PNG or GIF files from any location.

The required G13 device image is bundled separately inside `g13/gui/assets/`.

`splash-cyberpunk-2077-160x43.png` is a static, 1-bit Cyberpunk 2077 splash.
Its ready-to-use profile is in `../profiles/cyberpunk-2077.toml`; the keyboard
layout is also available in the configurator's game preset selector.

Artwork was generated with the built-in imagegen tool, then resized and
thresholded to the LCD's native resolution. Generation prompt:

> Use case: stylized-concept. Asset type: monochrome Logitech G13 LCD splash for Cyberpunk 2077. Create a very wide 160:43 composition, pure white on pure black, bold pixel-art shapes suitable for reduction to exactly 160x43 pixels. Large readable angular text "CYBERPUNK" with "2077" beneath, framed by a sparse futuristic Night City skyline silhouette and simple circuit traces. Keep text dominant, broad strokes, very few details, no grayscale shading, no gradients, no mockup, no border, no animation. Deliver a PNG.
