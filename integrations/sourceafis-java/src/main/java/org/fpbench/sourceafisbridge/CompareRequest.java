package org.fpbench.sourceafisbridge;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * What the bridge is asked to compare: two absolute image paths and two explicit
 * resolutions.
 *
 * <p>Note what is absent, and stays absent by construction: no pair id, no subject,
 * no finger, no impression, no protocol stage, no ground truth, no threshold. The
 * algorithm cannot treat a genuine comparison differently from an impostor one
 * because nothing in this document tells it which is which (docs/adr/0010).
 *
 * <p>{@code requestId} is the harness's opaque job id and exists purely so a log
 * line can be correlated with a stored result. It must not influence the score.
 *
 * <p>Unknown fields are rejected rather than ignored. A caller that sends a field
 * this bridge does not understand is running against a different protocol than it
 * thinks, and silently dropping it would hide that.
 */
public record CompareRequest(
        @JsonProperty("schema_version") String schemaVersion,
        @JsonProperty("request_id") String requestId,
        @JsonProperty("left") ImageSpec left,
        @JsonProperty("right") ImageSpec right) {

    public record ImageSpec(
            @JsonProperty("path") String path,
            @JsonProperty("dpi") Double dpi) {
    }

    /** Thrown when a request cannot be honoured at all. Exits non-zero. */
    public static final class InvalidRequestException extends Exception {
        private static final long serialVersionUID = 1L;

        public InvalidRequestException(String message) {
            super(message);
        }
    }

    /**
     * Check everything before any image is touched.
     *
     * @throws InvalidRequestException if the request is malformed. This is a caller
     *     bug, not a comparison failure, so it must not be reported as one.
     */
    public void validate() throws InvalidRequestException {
        if (!BridgeVersion.SCHEMA_VERSION.equals(schemaVersion)) {
            throw new InvalidRequestException(
                    "unsupported schema_version: " + schemaVersion);
        }
        if (requestId == null || requestId.isBlank()) {
            throw new InvalidRequestException("request_id is required");
        }
        validateSide("left", left);
        validateSide("right", right);
    }

    private static void validateSide(String name, ImageSpec spec)
            throws InvalidRequestException {
        if (spec == null) {
            throw new InvalidRequestException(name + " is required");
        }
        if (spec.path() == null || spec.path().isBlank()) {
            throw new InvalidRequestException(name + ".path is required");
        }
        Path path;
        try {
            path = Paths.get(spec.path());
        } catch (InvalidPathException exception) {
            throw new InvalidRequestException(name + ".path is not a usable path");
        }
        if (!path.isAbsolute()) {
            // A relative path would resolve against whatever directory the JVM
            // happens to have been started in, which is not something a stored
            // result could ever be reproduced from.
            throw new InvalidRequestException(name + ".path must be absolute");
        }
        Double dpi = spec.dpi();
        if (dpi == null || !Double.isFinite(dpi) || dpi <= 0) {
            throw new InvalidRequestException(name + ".dpi must be a finite positive number");
        }
    }

    public Path leftPath() {
        return Paths.get(left.path());
    }

    public Path rightPath() {
        return Paths.get(right.path());
    }
}
