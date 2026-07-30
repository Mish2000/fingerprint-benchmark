package org.fpbench.sourceafisbridge;

import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.UncheckedIOException;
import javax.imageio.ImageIO;

/**
 * Deterministic, synthetic ridge patterns for tests.
 *
 * <p><b>These are not fingerprints.</b> They are procedurally generated whorl-like
 * patterns with roughly the ridge spacing of a real print, which is enough for
 * SourceAFIS to extract a template and produce a score. No conclusion about
 * biometric accuracy can be drawn from them, and none is attempted anywhere.
 *
 * <p>They exist because SD300 imagery is redistribution-restricted and cannot be
 * committed. Everything here is generated at test time from a seed, so the bytes are
 * reproducible without shipping any image.
 *
 * <p>The pattern scales with DPI so that the <em>physical</em> ridge period stays
 * about 0.45 mm at every resolution. That matters: passing a 500-ppi-shaped image and
 * claiming it is 2000 ppi would make SourceAFIS scale it to a ridge period of two
 * pixels and fail extraction for reasons that have nothing to do with the DPI being
 * accepted.
 */
final class SyntheticFingerprints {

    /** Ridge periods per inch, i.e. about 0.46 mm between ridges. */
    private static final double RIDGES_PER_INCH = 55.0;

    /** Roughly the size of a fingertip impression. */
    private static final double INCHES = 0.6;

    private SyntheticFingerprints() {
    }

    /** A PNG at the given resolution, whose pattern is determined by {@code seed}. */
    static byte[] whorlPng(int dpi, int seed) {
        int size = (int) Math.round(INCHES * dpi);
        double ridgePeriod = dpi / RIDGES_PER_INCH;
        BufferedImage image = new BufferedImage(size, size, BufferedImage.TYPE_BYTE_GRAY);

        double centreX = size * (0.5 + 0.03 * seed);
        double centreY = size * (0.5 - 0.02 * seed);

        for (int y = 0; y < size; y++) {
            for (int x = 0; x < size; x++) {
                double dx = x - centreX;
                double dy = y - centreY;
                double radius = Math.hypot(dx, dy);
                double angle = Math.atan2(dy, dx);

                // Curved ridges, warped enough that ridges end and split — which is
                // where minutiae come from. A pure sine grating has none.
                double warp = 0.35 * ridgePeriod * Math.sin(3 * angle + 0.7 * seed)
                        + 0.20 * ridgePeriod * Math.sin((x + 1.3 * y) / (2.5 * ridgePeriod) + seed);
                double phase = (radius + warp) / ridgePeriod;
                double value = 128 + 110 * Math.sin(2 * Math.PI * phase);

                // Fade towards the edges so the print has a finite, plausible area.
                double falloff = Math.max(0.0, 1.0 - radius / (0.52 * size));
                int level = (int) Math.round(255 - (255 - value) * falloff);
                image.getRaster().setSample(x, y, 0, Math.max(0, Math.min(255, level)));
            }
        }
        return toPng(image);
    }

    /** Bytes that are not a decodable image, for the failure paths. */
    static byte[] corruptPng() {
        return "PNG\r\n\nthis is not a real png".getBytes(java.nio.charset.StandardCharsets.ISO_8859_1);
    }

    private static byte[] toPng(BufferedImage image) {
        try {
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            ImageIO.write(image, "png", buffer);
            return buffer.toByteArray();
        } catch (IOException exception) {
            throw new UncheckedIOException(exception);
        }
    }
}
