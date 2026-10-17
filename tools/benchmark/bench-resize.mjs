function antialiasedBilinearContributions(sourceLength, destinationLength) {
    const scale = sourceLength / destinationLength;
    const filterScale = Math.max(1, scale);
    const support = filterScale;
    return Array.from({ length: destinationLength }, (_, outputIndex) => {
        const center = (outputIndex + 0.5) * scale;
        const first = Math.max(0, Math.ceil(center - support - 0.5));
        const last = Math.min(sourceLength - 1, Math.floor(center + support - 0.5));
        const entries = [];
        let total = 0;
        for (let sourceIndex = first; sourceIndex <= last; sourceIndex += 1) {
            const distance = Math.abs(((sourceIndex + 0.5) - center) / filterScale);
            const weight = Math.max(0, 1 - distance);
            if (weight > 0) {
                entries.push([sourceIndex, weight]);
                total += weight;
            }
        }
        return entries.map(([sourceIndex, weight]) => [sourceIndex, weight / total]);
    });
}
function yieldToBrowser() {
    if (typeof MessageChannel !== 'function') {
        return new Promise((resolve) => setTimeout(resolve, 0));
    }
    return new Promise((resolve) => {
        const channel = new MessageChannel();
        channel.port1.onmessage = () => {
            channel.port1.close();
            resolve();
        };
        channel.port2.postMessage(0);
    });
}

async function resizeRgbAntialiased(rgba, sourceWidth, sourceHeight, destinationWidth, destinationHeight) {
    const horizontalWeights = antialiasedBilinearContributions(sourceWidth, destinationWidth);
    const verticalWeights = antialiasedBilinearContributions(sourceHeight, destinationHeight);
    const horizontal = new Float32Array(sourceHeight * destinationWidth * 3);

    for (let y = 0; y < sourceHeight; y += 1) {
        horizontalWeights.forEach((entries, outputX) => {
            entries.forEach(([sourceX, weight]) => {
                const sourceOffset = ((y * sourceWidth) + sourceX) * 4;
                const destinationOffset = ((y * destinationWidth) + outputX) * 3;
                horizontal[destinationOffset] += rgba[sourceOffset] * weight;
                horizontal[destinationOffset + 1] += rgba[sourceOffset + 1] * weight;
                horizontal[destinationOffset + 2] += rgba[sourceOffset + 2] * weight;
            });
        });
        if (y > 0 && y % 64 === 0) await yieldToBrowser();
    }

    const result = new Float32Array(destinationWidth * destinationHeight * 3);
    for (let outputY = 0; outputY < verticalWeights.length; outputY += 1) {
        const entries = verticalWeights[outputY];
        for (let x = 0; x < destinationWidth; x += 1) {
            const destinationOffset = ((outputY * destinationWidth) + x) * 3;
            entries.forEach(([sourceY, weight]) => {
                const sourceOffset = ((sourceY * destinationWidth) + x) * 3;
                result[destinationOffset] += horizontal[sourceOffset] * weight;
                result[destinationOffset + 1] += horizontal[sourceOffset + 1] * weight;
                result[destinationOffset + 2] += horizontal[sourceOffset + 2] * weight;
            });
        }
        if (outputY > 0 && outputY % 32 === 0) await yieldToBrowser();
    }
    return result;
}

for (const side of [720, 1024]) {
  const rgba = new Uint8ClampedArray(side * side * 4); for (let i = 0; i < rgba.length; i++) rgba[i] = (i * 2654435761) & 255;
  for (let i = 0; i < 3; i++) await resizeRgbAntialiased(rgba, side, side, 224, 224);
  const ts = [];
  for (let i = 0; i < 20; i++) { const t0 = performance.now(); await resizeRgbAntialiased(rgba, side, side, 224, 224); ts.push(performance.now() - t0); }
  ts.sort((a, b) => a - b);
  console.log(`JS resize ${side}x${side} -> 224: median=${((ts[9] + ts[10]) / 2).toFixed(2)} ms`);
}
