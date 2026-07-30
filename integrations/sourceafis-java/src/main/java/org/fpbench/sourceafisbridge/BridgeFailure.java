package org.fpbench.sourceafisbridge;

/**
 * An expected failure: the comparison could not produce a score, and that is
 * ordinary rather than exceptional.
 *
 * <p>Something the bridge is <em>supposed</em> to handle — an unreadable file, an
 * image SourceAFIS cannot decode, a template it cannot build — exits with code 0
 * and a well-formed failure document. The Python side turns that into a stored
 * result with a specific failure code. Only a broken request or a genuine bug in
 * this program exits non-zero.
 *
 * <p>Messages here are fixed strings. They must never carry a path, a filename or
 * anything derived from the image, because a failure document travels into stored
 * results and from there into reports.
 */
public final class BridgeFailure extends Exception {

    private static final long serialVersionUID = 1L;

    /** Failure codes. These map one-to-one onto fpbench's own taxonomy. */
    public static final class Code {
        public static final String INPUT_READ_FAILED = "input_read_failed";
        public static final String IMAGE_DECODE_FAILED = "image_decode_failed";
        public static final String UNSUPPORTED_RESOLUTION = "unsupported_resolution";
        public static final String TEMPLATE_EXTRACTION_FAILED = "template_extraction_failed";
        public static final String MATCHING_FAILED = "matching_failed";

        private Code() {
        }
    }

    /** Where in the bridge's own sequence the failure happened. */
    public static final class Stage {
        public static final String LEFT_INPUT = "left_input";
        public static final String RIGHT_INPUT = "right_input";
        public static final String LEFT_EXTRACTION = "left_extraction";
        public static final String RIGHT_EXTRACTION = "right_extraction";
        public static final String MATCHING = "matching";

        private Stage() {
        }
    }

    public static final String SIDE_LEFT = "left";
    public static final String SIDE_RIGHT = "right";

    private final String code;
    private final String stage;
    private final String side;
    private final String exceptionType;

    public BridgeFailure(String code, String stage, String side, String message, Throwable cause) {
        super(message);
        this.code = code;
        this.stage = stage;
        this.side = side;
        this.exceptionType = cause == null ? null : cause.getClass().getSimpleName();
    }

    /** A failure not tied to one side, such as matching. */
    public static BridgeFailure of(String code, String stage, String message, Throwable cause) {
        return new BridgeFailure(code, stage, null, message, cause);
    }

    public String code() {
        return code;
    }

    public String stage() {
        return stage;
    }

    public String side() {
        return side;
    }

    public String exceptionType() {
        return exceptionType;
    }
}
