package org.fpbench.sourceafisbridge;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonPropertyOrder;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * The single JSON document the bridge writes to stdout.
 *
 * <p>Two shapes, one type. A success carries a score and {@code extraction_count};
 * a failure carries a code, a stage and a fixed message. Absent fields are omitted
 * rather than sent as null, so the Python side can tell "not applicable" from
 * "explicitly empty".
 *
 * <p>There is no threshold, no decision and no similarity verdict here. The score is
 * SourceAFIS's own number and stays that way until a decision policy — which lives
 * far from this program — interprets it (docs/adr/0003).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonPropertyOrder({
    "schema_version",
    "request_id",
    "status",
    "score",
    "code",
    "stage",
    "side",
    "message",
    "exception_type",
    "sourceafis_version",
    "bridge_version",
    "extraction_count",
    "timings_ms"
})
public final class CompareResponse {

    @JsonProperty("schema_version")
    public final String schemaVersion = BridgeVersion.SCHEMA_VERSION;

    @JsonProperty("request_id")
    public final String requestId;

    @JsonProperty("status")
    public final String status;

    @JsonProperty("score")
    public final Double score;

    @JsonProperty("code")
    public final String code;

    @JsonProperty("stage")
    public final String stage;

    @JsonProperty("side")
    public final String side;

    @JsonProperty("message")
    public final String message;

    @JsonProperty("exception_type")
    public final String exceptionType;

    @JsonProperty("sourceafis_version")
    public final String sourceafisVersion;

    @JsonProperty("bridge_version")
    public final String bridgeVersion = BridgeVersion.BRIDGE_VERSION;

    @JsonProperty("extraction_count")
    public final Integer extractionCount;

    @JsonProperty("timings_ms")
    public final Map<String, Double> timingsMs;

    private CompareResponse(
            String requestId,
            String status,
            Double score,
            String code,
            String stage,
            String side,
            String message,
            String exceptionType,
            String sourceafisVersion,
            Integer extractionCount,
            Map<String, Double> timingsMs) {
        this.requestId = requestId;
        this.status = status;
        this.score = score;
        this.code = code;
        this.stage = stage;
        this.side = side;
        this.message = message;
        this.exceptionType = exceptionType;
        this.sourceafisVersion = sourceafisVersion;
        this.extractionCount = extractionCount;
        this.timingsMs = new LinkedHashMap<>(timingsMs);
    }

    public static CompareResponse success(
            String requestId,
            double score,
            String sourceafisVersion,
            int extractionCount,
            Map<String, Double> timingsMs) {
        return new CompareResponse(
                requestId,
                "success",
                score,
                null,
                null,
                null,
                null,
                null,
                sourceafisVersion,
                extractionCount,
                timingsMs);
    }

    public static CompareResponse failure(
            String requestId,
            BridgeFailure failure,
            String sourceafisVersion,
            Map<String, Double> timingsMs) {
        return new CompareResponse(
                requestId,
                "failure",
                null,
                failure.code(),
                failure.stage(),
                failure.side(),
                failure.getMessage(),
                failure.exceptionType(),
                sourceafisVersion,
                null,
                timingsMs);
    }
}
