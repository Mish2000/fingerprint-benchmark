package org.fpbench.sourceafisbridge;

import static org.junit.jupiter.api.Assertions.assertAll;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.machinezoo.sourceafis.FingerprintTemplate;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class SourceAfisComparisonServiceTest {

    private static CompareRequest request(Path left, double leftDpi, Path right, double rightDpi) {
        return new CompareRequest(
                "1",
                "job_0123456789abcdef",
                new CompareRequest.ImageSpec(left.toAbsolutePath().toString(), leftDpi),
                new CompareRequest.ImageSpec(right.toAbsolutePath().toString(), rightDpi));
    }

    private static Path write(Path directory, String name, byte[] bytes) throws IOException {
        Path path = directory.resolve(name);
        Files.write(path, bytes);
        return path;
    }

    // ------------------------------------------------------------------ success

    @Test
    void aComparisonProducesAFiniteNonNegativeScore(@TempDir Path dir) throws IOException {
        Path left = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Path right = write(dir, "b.png", SyntheticFingerprints.whorlPng(500, 4));

        CompareResponse response =
                new SourceAfisComparisonService().compare(request(left, 500, right, 500));

        assertAll(
                () -> assertEquals("success", response.status, "status"),
                () -> assertNotNull(response.score, "score"),
                () -> assertTrue(Double.isFinite(response.score), "score is finite"),
                () -> assertTrue(response.score >= 0, "score is non-negative"),
                () -> assertNull(response.code, "no failure code on success"),
                () -> assertEquals(2, response.extractionCount, "extraction_count"));
    }

    @Test
    void theResponseEchoesTheRequestIdAndVersions(@TempDir Path dir) throws IOException {
        Path image = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        CompareResponse response =
                new SourceAfisComparisonService().compare(request(image, 500, image, 500));

        assertAll(
                () -> assertEquals("job_0123456789abcdef", response.requestId),
                () -> assertEquals("1", response.schemaVersion),
                () -> assertEquals("1", response.bridgeVersion),
                () -> assertEquals(BridgeVersion.sourceafisVersion(), response.sourceafisVersion));
    }

    @Test
    void theSameInputsProduceTheSameScore(@TempDir Path dir) throws IOException {
        Path left = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 2));
        Path right = write(dir, "b.png", SyntheticFingerprints.whorlPng(500, 5));
        SourceAfisComparisonService service = new SourceAfisComparisonService();

        Double first = service.compare(request(left, 500, right, 500)).score;
        Double second = service.compare(request(left, 500, right, 500)).score;

        assertEquals(first, second, "SourceAFIS is deterministic for identical input");
    }

    @Test
    void allTimingsAreFiniteAndNonNegative(@TempDir Path dir) throws IOException {
        Path image = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        CompareResponse response =
                new SourceAfisComparisonService().compare(request(image, 500, image, 500));

        assertTrue(response.timingsMs.containsKey("bridge_total"), "bridge_total is reported");
        response.timingsMs.forEach((name, value) -> assertTrue(
                Double.isFinite(value) && value >= 0, name + " is finite and non-negative"));
    }

    // -------------------------------------------------------------------- DPI

    @ParameterizedTest
    @ValueSource(ints = {500, 1000, 2000})
    void everySd300ResolutionIsAccepted(int dpi, @TempDir Path dir) throws IOException {
        // The image is generated at the resolution it claims, so this measures whether
        // the DPI is accepted rather than whether a mis-scaled image can be extracted.
        Path left = write(dir, "a.png", SyntheticFingerprints.whorlPng(dpi, 1));
        Path right = write(dir, "b.png", SyntheticFingerprints.whorlPng(dpi, 3));

        CompareResponse response =
                new SourceAfisComparisonService().compare(request(left, dpi, right, dpi));

        assertEquals("success", response.status, "status at " + dpi + " dpi: " + response.code);
        assertTrue(response.score >= 0);
    }

    @Test
    void differentResolutionsPerSideAreAllowed(@TempDir Path dir) throws IOException {
        // SD300 pairs cross resolutions only across releases, but the bridge must not
        // assume the two sides agree.
        Path left = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Path right = write(dir, "b.png", SyntheticFingerprints.whorlPng(1000, 1));

        CompareResponse response =
                new SourceAfisComparisonService().compare(request(left, 500, right, 1000));

        assertEquals("success", response.status, "" + response.code);
    }

    // -------------------------------------------------- independent extraction

    /** Counts reads and extractions, and records which bytes each side saw. */
    private static final class CountingPipeline
            implements SourceAfisComparisonService.ImagePipeline {
        private final SourceAfisComparisonService.ImagePipeline delegate =
                new SourceAfisComparisonService.SourceAfisPipeline();
        final List<String> reads = new ArrayList<>();
        final List<String> extractions = new ArrayList<>();
        final List<FingerprintTemplate> templates = new ArrayList<>();

        @Override
        public byte[] read(Path path, String side, String stage) throws BridgeFailure {
            reads.add(side);
            return delegate.read(path, side, stage);
        }

        @Override
        public FingerprintTemplate extract(byte[] encoded, double dpi, String side, String stage)
                throws BridgeFailure {
            extractions.add(side);
            FingerprintTemplate template = delegate.extract(encoded, dpi, side, stage);
            templates.add(template);
            return template;
        }
    }

    @Test
    void bothSidesAreExtractedIndependently(@TempDir Path dir) throws IOException {
        Path left = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Path right = write(dir, "b.png", SyntheticFingerprints.whorlPng(500, 6));
        CountingPipeline pipeline = new CountingPipeline();

        new SourceAfisComparisonService(pipeline).compare(request(left, 500, right, 500));

        assertEquals(List.of("left", "right"), pipeline.reads);
        assertEquals(List.of("left", "right"), pipeline.extractions);
    }

    @Test
    void theSamePathIsStillExtractedTwice(@TempDir Path dir) throws IOException {
        // A SELF comparison. Reusing the first template would be invisible in the
        // score and would make SELF the one stage that took a different code path.
        Path image = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        CountingPipeline pipeline = new CountingPipeline();

        CompareResponse response =
                new SourceAfisComparisonService(pipeline).compare(request(image, 500, image, 500));

        assertAll(
                () -> assertEquals(2, pipeline.reads.size(), "both sides read"),
                () -> assertEquals(2, pipeline.extractions.size(), "both sides extracted"),
                () -> assertEquals(2, response.extractionCount, "extraction_count reported"),
                () -> assertTrue(
                        pipeline.templates.get(0) != pipeline.templates.get(1),
                        "two distinct template objects, not one reused"));
    }

    @Test
    void leftIsTheProbeAndRightIsTheCandidate(@TempDir Path dir) throws IOException {
        // The order the pipeline is asked for the two sides is the order they are used:
        // left becomes the matcher's probe, right the candidate it is matched against.
        Path left = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Path right = write(dir, "b.png", SyntheticFingerprints.whorlPng(500, 7));
        CountingPipeline pipeline = new CountingPipeline();

        new SourceAfisComparisonService(pipeline).compare(request(left, 500, right, 500));

        assertEquals("left", pipeline.extractions.get(0), "probe is extracted first");
        assertEquals("right", pipeline.extractions.get(1), "candidate is extracted second");
    }

    // --------------------------------------------------------------- failures

    @Test
    void aMissingInputIsReportedAsAReadFailure(@TempDir Path dir) throws IOException {
        Path present = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Path absent = dir.resolve("nope.png");

        CompareResponse response =
                new SourceAfisComparisonService().compare(request(absent, 500, present, 500));

        assertAll(
                () -> assertEquals("failure", response.status),
                () -> assertEquals(BridgeFailure.Code.INPUT_READ_FAILED, response.code),
                () -> assertEquals(BridgeFailure.Stage.LEFT_INPUT, response.stage),
                () -> assertEquals("left", response.side),
                () -> assertNull(response.score, "a failure carries no score"));
    }

    @Test
    void aCorruptImageIsReportedAsADecodeFailure(@TempDir Path dir) throws IOException {
        Path good = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Path bad = write(dir, "bad.png", SyntheticFingerprints.corruptPng());

        CompareResponse response =
                new SourceAfisComparisonService().compare(request(good, 500, bad, 500));

        assertAll(
                () -> assertEquals("failure", response.status),
                () -> assertEquals(BridgeFailure.Code.IMAGE_DECODE_FAILED, response.code),
                () -> assertEquals(BridgeFailure.Stage.RIGHT_EXTRACTION, response.stage),
                () -> assertEquals("right", response.side));
    }

    @Test
    void aFailureResponseDoesNotEchoThePath(@TempDir Path dir) throws IOException {
        Path good = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Path bad = write(dir, "secret-subject-00001000.png", SyntheticFingerprints.corruptPng());

        CompareResponse response =
                new SourceAfisComparisonService().compare(request(good, 500, bad, 500));

        assertAll(
                () -> assertTrue(
                        !response.message.contains("secret-subject"),
                        "message must not name the file: " + response.message),
                () -> assertTrue(
                        !response.message.contains(dir.toString()),
                        "message must not contain a path"));
    }

    @Test
    void aFailureStillReportsTimings(@TempDir Path dir) throws IOException {
        Path good = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Path absent = dir.resolve("nope.png");

        CompareResponse response =
                new SourceAfisComparisonService().compare(request(good, 500, absent, 500));

        assertTrue(response.timingsMs.containsKey("bridge_total"));
        assertTrue(response.timingsMs.get("bridge_total") >= 0);
    }

    @Test
    void aFailureReportsTheExceptionType(@TempDir Path dir) throws IOException {
        Path good = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Path bad = write(dir, "bad.png", SyntheticFingerprints.corruptPng());

        CompareResponse response =
                new SourceAfisComparisonService().compare(request(good, 500, bad, 500));

        assertNotNull(response.exceptionType, "the underlying exception type helps triage");
    }
}
