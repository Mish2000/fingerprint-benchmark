package org.fpbench.sourceafisbridge;

import static org.junit.jupiter.api.Assertions.assertAll;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class BridgeMainTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private record Invocation(int exitCode, String stdout, String stderr) {
        JsonNode json() throws IOException {
            return MAPPER.readTree(stdout);
        }
    }

    private static Invocation invoke(String[] args, String stdin) {
        InputStream originalIn = System.in;
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        ByteArrayOutputStream err = new ByteArrayOutputStream();
        try {
            System.setIn(new ByteArrayInputStream(stdin.getBytes(StandardCharsets.UTF_8)));
            int code = BridgeMain.run(
                    args,
                    new PrintStream(out, true, StandardCharsets.UTF_8),
                    new PrintStream(err, true, StandardCharsets.UTF_8));
            return new Invocation(
                    code,
                    out.toString(StandardCharsets.UTF_8),
                    err.toString(StandardCharsets.UTF_8));
        } finally {
            System.setIn(originalIn);
        }
    }

    private static String compareRequest(Path left, double leftDpi, Path right, double rightDpi) {
        return """
            {"schema_version":"1","request_id":"job_0123456789abcdef",
             "left":{"path":%s,"dpi":%s},
             "right":{"path":%s,"dpi":%s}}
            """
                .formatted(
                        quote(left.toAbsolutePath().toString()),
                        leftDpi,
                        quote(right.toAbsolutePath().toString()),
                        rightDpi);
    }

    private static String quote(String value) {
        try {
            return MAPPER.writeValueAsString(value);
        } catch (IOException exception) {
            throw new AssertionError(exception);
        }
    }

    private static Path write(Path dir, String name, byte[] bytes) throws IOException {
        Path path = dir.resolve(name);
        Files.write(path, bytes);
        return path;
    }

    // -------------------------------------------------------------- version

    @Test
    void versionReportsTheRuntimeSourceafisVersion() throws IOException {
        Invocation result = invoke(new String[] {"version"}, "");

        assertEquals(BridgeMain.EXIT_OK, result.exitCode(), result.stderr());
        JsonNode json = result.json();
        assertAll(
                () -> assertEquals("1", json.get("schema_version").asText()),
                () -> assertEquals("1", json.get("bridge_version").asText()),
                () -> assertEquals(
                        "fpbench.sourceafis.bridge.v1", json.get("bridge_protocol").asText()),
                () -> assertEquals(
                        BridgeVersion.sourceafisVersion(),
                        json.get("sourceafis_version").asText(),
                        "the version must come from SourceAFIS, not from a constant"),
                () -> assertTrue(json.hasNonNull("java_version")),
                () -> assertTrue(json.hasNonNull("java_vendor")));
    }

    @Test
    void theRuntimeVersionIsTheOneTheBuildPinned() {
        // If this fails, the jar on the classpath is not the one the experiment was
        // defined against — which is exactly what environment validation must catch.
        assertEquals("3.18.1", BridgeVersion.sourceafisVersion());
    }

    // -------------------------------------------------------------- compare

    @Test
    void aValidRequestProducesExactlyOneJsonDocument(@TempDir Path dir) throws IOException {
        Path image = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Invocation result =
                invoke(new String[] {"compare"}, compareRequest(image, 500, image, 500));

        assertEquals(BridgeMain.EXIT_OK, result.exitCode(), result.stderr());
        assertEquals(
                1,
                result.stdout().strip().split("\\}\\s*\\{").length,
                "stdout must hold one document only");
        assertEquals("success", result.json().get("status").asText());
        assertEquals(2, result.json().get("extraction_count").asInt());
    }

    @Test
    void anExpectedFailureStillExitsZero(@TempDir Path dir) throws IOException {
        Path good = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Path bad = write(dir, "bad.png", SyntheticFingerprints.corruptPng());

        Invocation result =
                invoke(new String[] {"compare"}, compareRequest(good, 500, bad, 500));

        assertEquals(
                BridgeMain.EXIT_OK,
                result.exitCode(),
                "an undecodable image is a result, not a crash");
        assertEquals("failure", result.json().get("status").asText());
        assertEquals("image_decode_failed", result.json().get("code").asText());
    }

    // ------------------------------------------------------ invalid requests

    @Test
    void anUnknownFieldIsRejected(@TempDir Path dir) throws IOException {
        Path image = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        String request = compareRequest(image, 500, image, 500)
                .replace("\"request_id\"", "\"ground_truth\":\"mated\",\"request_id\"");

        Invocation result = invoke(new String[] {"compare"}, request);

        assertEquals(BridgeMain.EXIT_INVALID_REQUEST, result.exitCode());
        assertTrue(result.stdout().isBlank(), "no document on a rejected request");
    }

    @Test
    void anUnsupportedSchemaVersionIsRejected(@TempDir Path dir) throws IOException {
        Path image = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        String request =
                compareRequest(image, 500, image, 500).replace("\"schema_version\":\"1\"", "\"schema_version\":\"99\"");

        Invocation result = invoke(new String[] {"compare"}, request);

        assertEquals(BridgeMain.EXIT_INVALID_REQUEST, result.exitCode());
        assertTrue(result.stderr().contains("schema_version"));
    }

    @Test
    void malformedJsonIsRejected() {
        Invocation result = invoke(new String[] {"compare"}, "{not json");
        assertEquals(BridgeMain.EXIT_INVALID_REQUEST, result.exitCode());
        assertTrue(result.stdout().isBlank());
    }

    @Test
    void emptyStdinIsRejected() {
        Invocation result = invoke(new String[] {"compare"}, "");
        assertEquals(BridgeMain.EXIT_INVALID_REQUEST, result.exitCode());
    }

    @Test
    void anUnknownCommandIsRejected() {
        Invocation result = invoke(new String[] {"extract"}, "");
        assertEquals(BridgeMain.EXIT_INVALID_REQUEST, result.exitCode());
    }

    @Test
    void missingArgumentsAreRejected() {
        assertEquals(BridgeMain.EXIT_INVALID_REQUEST, invoke(new String[] {}, "").exitCode());
    }

    // ----------------------------------------------- request-level validation

    @Test
    void aRelativePathIsRejected() {
        CompareRequest request = new CompareRequest(
                "1",
                "job_0123456789abcdef",
                new CompareRequest.ImageSpec("relative/a.png", 500.0),
                new CompareRequest.ImageSpec("relative/b.png", 500.0));

        CompareRequest.InvalidRequestException failure = assertThrows(
                CompareRequest.InvalidRequestException.class, request::validate);
        assertTrue(failure.getMessage().contains("absolute"));
    }

    @Test
    void anInvalidDpiIsRejected(@TempDir Path dir) {
        Path image = dir.resolve("a.png").toAbsolutePath();
        for (Double dpi : new Double[] {null, 0.0, -500.0, Double.NaN, Double.POSITIVE_INFINITY}) {
            CompareRequest request = new CompareRequest(
                    "1",
                    "job_0123456789abcdef",
                    new CompareRequest.ImageSpec(image.toString(), dpi),
                    new CompareRequest.ImageSpec(image.toString(), 500.0));
            assertThrows(
                    CompareRequest.InvalidRequestException.class,
                    request::validate,
                    "dpi " + dpi + " must be rejected");
        }
    }

    @Test
    void aBlankRequestIdIsRejected(@TempDir Path dir) {
        Path image = dir.resolve("a.png").toAbsolutePath();
        CompareRequest request = new CompareRequest(
                "1",
                "  ",
                new CompareRequest.ImageSpec(image.toString(), 500.0),
                new CompareRequest.ImageSpec(image.toString(), 500.0));
        assertThrows(CompareRequest.InvalidRequestException.class, request::validate);
    }

    @Test
    void aMissingSideIsRejected(@TempDir Path dir) {
        Path image = dir.resolve("a.png").toAbsolutePath();
        CompareRequest request = new CompareRequest(
                "1",
                "job_0123456789abcdef",
                new CompareRequest.ImageSpec(image.toString(), 500.0),
                null);
        assertThrows(CompareRequest.InvalidRequestException.class, request::validate);
    }

    @Test
    void theRequestCarriesNoProtocolInformation() {
        // docs/adr/0010, checked against the wire format rather than by reading it.
        java.util.Set<String> fields = new java.util.HashSet<>();
        for (var component : CompareRequest.class.getRecordComponents()) {
            fields.add(component.getName());
        }
        assertEquals(java.util.Set.of("schemaVersion", "requestId", "left", "right"), fields);
        for (var component : CompareRequest.ImageSpec.class.getRecordComponents()) {
            assertTrue(
                    java.util.Set.of("path", "dpi").contains(component.getName()),
                    "unexpected field on the wire: " + component.getName());
        }
    }

    @Test
    void theRequestIdDoesNotChangeTheScore(@TempDir Path dir) throws IOException {
        Path left = write(dir, "a.png", SyntheticFingerprints.whorlPng(500, 1));
        Path right = write(dir, "b.png", SyntheticFingerprints.whorlPng(500, 8));

        Invocation first =
                invoke(new String[] {"compare"}, compareRequest(left, 500, right, 500));
        Invocation second = invoke(
                new String[] {"compare"},
                compareRequest(left, 500, right, 500)
                        .replace("job_0123456789abcdef", "job_fedcba9876543210"));

        assertEquals(
                first.json().get("score").asDouble(),
                second.json().get("score").asDouble(),
                "request_id is for correlation only");
        assertNotEquals(
                first.json().get("request_id").asText(), second.json().get("request_id").asText());
    }
}
