package org.fpbench.sourceafisbridge;

import com.machinezoo.sourceafis.FingerprintImage;
import com.machinezoo.sourceafis.FingerprintImageOptions;
import com.machinezoo.sourceafis.FingerprintMatcher;
import com.machinezoo.sourceafis.FingerprintTemplate;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * One comparison, from two paths to one score.
 *
 * <p>Three properties are load-bearing and each is enforced here rather than assumed:
 *
 * <ol>
 *   <li><b>Both sides are extracted independently.</b> Even when the two paths are
 *       identical — which is exactly what a SELF comparison looks like — the bytes are
 *       read twice and two templates are built. Reusing one would make SELF take a
 *       different code path from every other stage, and it is the stage most likely to
 *       be measuring something subtle. {@code extraction_count} is reported so the
 *       caller can check rather than trust.
 *   <li><b>DPI is explicit.</b> SourceAFIS ignores whatever resolution a PNG header
 *       claims, which is precisely what this project needs: SD300C files declare 5080
 *       ppi and are genuinely 2000 (docs/adr/0004, docs/adr/0016).
 *   <li><b>Left is the probe, right is the candidate.</b> Fixed, never averaged or
 *       reversed. Asymmetry, if it is ever worth measuring, is a separate experiment.
 * </ol>
 *
 * <p>The reading and extraction steps go through {@link ImagePipeline} so that a test
 * can count them. That indirection exists for the tests and for nothing else; it is
 * package-private and never surfaces beyond this jar.
 */
public final class SourceAfisComparisonService {

    /** The two operations that touch an image, isolated so they can be counted. */
    interface ImagePipeline {
        byte[] read(Path path, String side, String stage) throws BridgeFailure;

        FingerprintTemplate extract(byte[] encoded, double dpi, String side, String stage)
                throws BridgeFailure;
    }

    private final ImagePipeline pipeline;

    public SourceAfisComparisonService() {
        this(new SourceAfisPipeline());
    }

    SourceAfisComparisonService(ImagePipeline pipeline) {
        this.pipeline = pipeline;
    }

    public CompareResponse compare(CompareRequest request) {
        Map<String, Double> timings = new LinkedHashMap<>();
        long started = System.nanoTime();
        int extractions = 0;

        try {
            long mark = System.nanoTime();
            byte[] leftBytes = pipeline.read(
                    request.leftPath(), BridgeFailure.SIDE_LEFT, BridgeFailure.Stage.LEFT_INPUT);
            timings.put("left_input_read", millisSince(mark));

            mark = System.nanoTime();
            FingerprintTemplate leftTemplate = pipeline.extract(
                    leftBytes,
                    request.left().dpi(),
                    BridgeFailure.SIDE_LEFT,
                    BridgeFailure.Stage.LEFT_EXTRACTION);
            extractions++;
            timings.put("left_template_extraction", millisSince(mark));

            // Read and extract the right side from scratch. When both paths point at
            // the same file this looks wasteful; it is the guarantee that SELF is not
            // a special case.
            mark = System.nanoTime();
            byte[] rightBytes = pipeline.read(
                    request.rightPath(), BridgeFailure.SIDE_RIGHT, BridgeFailure.Stage.RIGHT_INPUT);
            timings.put("right_input_read", millisSince(mark));

            mark = System.nanoTime();
            FingerprintTemplate rightTemplate = pipeline.extract(
                    rightBytes,
                    request.right().dpi(),
                    BridgeFailure.SIDE_RIGHT,
                    BridgeFailure.Stage.RIGHT_EXTRACTION);
            extractions++;
            timings.put("right_template_extraction", millisSince(mark));

            mark = System.nanoTime();
            FingerprintMatcher matcher;
            try {
                matcher = new FingerprintMatcher(leftTemplate);
            } catch (RuntimeException exception) {
                throw BridgeFailure.of(
                        BridgeFailure.Code.MATCHING_FAILED,
                        BridgeFailure.Stage.MATCHING,
                        "Matcher could not be initialised",
                        exception);
            }
            timings.put("matcher_initialization", millisSince(mark));

            mark = System.nanoTime();
            double score;
            try {
                score = matcher.match(rightTemplate);
            } catch (RuntimeException exception) {
                throw BridgeFailure.of(
                        BridgeFailure.Code.MATCHING_FAILED,
                        BridgeFailure.Stage.MATCHING,
                        "Matching failed",
                        exception);
            }
            timings.put("matching", millisSince(mark));

            if (!Double.isFinite(score) || score < 0) {
                // SourceAFIS documents a non-negative, higher-is-better similarity.
                // Anything else means the assumption the harness records alongside
                // every score no longer holds, and that must surface loudly.
                throw BridgeFailure.of(
                        BridgeFailure.Code.MATCHING_FAILED,
                        BridgeFailure.Stage.MATCHING,
                        "Matcher returned a score that is not a finite non-negative number",
                        null);
            }

            timings.put("bridge_total", millisSince(started));
            return CompareResponse.success(
                    request.requestId(),
                    score,
                    BridgeVersion.sourceafisVersion(),
                    extractions,
                    timings);

        } catch (BridgeFailure failure) {
            timings.put("bridge_total", millisSince(started));
            return CompareResponse.failure(
                    request.requestId(), failure, BridgeVersion.sourceafisVersion(), timings);
        }
    }

    private static double millisSince(long startNanos) {
        return (System.nanoTime() - startNanos) / 1_000_000.0;
    }

    /** The real pipeline: files from disk, templates from SourceAFIS. */
    static final class SourceAfisPipeline implements ImagePipeline {

        @Override
        public byte[] read(Path path, String side, String stage) throws BridgeFailure {
            try {
                return Files.readAllBytes(path);
            } catch (IOException | RuntimeException exception) {
                // Deliberately no path in the message: this text ends up in a stored
                // result and from there in reports.
                throw new BridgeFailure(
                        BridgeFailure.Code.INPUT_READ_FAILED,
                        stage,
                        side,
                        "Input image could not be read",
                        exception);
            }
        }

        @Override
        public FingerprintTemplate extract(byte[] encoded, double dpi, String side, String stage)
                throws BridgeFailure {
            // Three separate steps, so that three different problems get three
            // different failure codes instead of one vague one.
            FingerprintImageOptions options;
            try {
                options = new FingerprintImageOptions().dpi(dpi);
            } catch (RuntimeException exception) {
                throw new BridgeFailure(
                        BridgeFailure.Code.UNSUPPORTED_RESOLUTION,
                        stage,
                        side,
                        "SourceAFIS rejected the requested resolution",
                        exception);
            }

            FingerprintImage image;
            try {
                image = new FingerprintImage(encoded, options);
            } catch (RuntimeException exception) {
                throw new BridgeFailure(
                        BridgeFailure.Code.IMAGE_DECODE_FAILED,
                        stage,
                        side,
                        "Input image could not be decoded",
                        exception);
            }

            try {
                return new FingerprintTemplate(image);
            } catch (RuntimeException exception) {
                throw new BridgeFailure(
                        BridgeFailure.Code.TEMPLATE_EXTRACTION_FAILED,
                        stage,
                        side,
                        "Template could not be extracted from the image",
                        exception);
            }
        }
    }
}
