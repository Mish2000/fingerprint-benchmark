// The production fpbench bridge to VeriFinger 2025.2, through upstream's own
// Java binding.
//
// Two commands and nothing else:
//
//     version    what this runtime is, read from the runtime
//     compare    two image paths in, one integer score or one failure out
//
// It is deliberately not the Stage 11A qualification harness. That program was
// built to answer questions about a candidate — it chooses fixtures, provokes
// failures and hides scores behind digests — and none of that belongs in the
// thing that produces six thousand benchmark results.
//
// What this program is not allowed to know is as important as what it does.
// It never receives a subject, a finger position, a release, a pair kind, a
// protocol stage, a ground truth, an expected decision, a threshold, or any
// other algorithm's score. It receives two paths and two resolutions
// (docs/adr/0010).
//
// **The route is upstream's own `verify-finger`.** Obtain the two finger
// licences, construct one NBiometricClient, read the delivered defaults before
// touching anything, set exactly what that tutorial sets, build two independent
// subjects and call `verify(reference, candidate)`. The score is the integer on
// the reference subject's first matching result, read under both OK and
// MATCH_NOT_FOUND — which is what makes the number independent of the
// tutorial's own 48 (Stage 11A, spec section 10).
//
// **No decision leaves this process.** The engine's MATCH/NO-MATCH answer is
// never emitted. A `match` boolean here would be a threshold fpbench did not
// choose, arriving through the back door (docs/adr/0003).
//
// **A failure is never a score of zero.** Every path that cannot produce a
// score emits a `failure` document naming a code and the stage it happened at,
// and the Python side decides whether that code is VeriFinger declining a
// print or the harness being broken (spec section 12).
//
// Invoked as:
//     java -cp <bridge.jar>;<pinned neurotec jars> \
//          org.fpbench.verifingerbridge.VeriFingerBridge <command>
// with `compare` reading one JSON request from stdin. Exactly one JSON object
// reaches stdout, always, including when something goes wrong.

package org.fpbench.verifingerbridge;

import com.neurotec.biometrics.NBiometricStatus;
import com.neurotec.biometrics.NFinger;
import com.neurotec.biometrics.NMatchingSpeed;
import com.neurotec.biometrics.NSubject;
import com.neurotec.biometrics.client.NBiometricClient;
import com.neurotec.images.NImage;
import com.neurotec.lang.NModule;
import com.neurotec.licensing.NLicense;
import com.neurotec.licensing.NLicenseManager;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public final class VeriFingerBridge {

    // ------------------------------------------------------------ identity

    static final String SCHEMA_VERSION = "1";
    static final String BRIDGE_PROTOCOL = "fpbench.verifinger.bridge.v1";
    static final String BRIDGE_VERSION = "1";

    /** The licences upstream's own 1:1 tutorial obtains, in its order. */
    static final String LICENCES = "FingerMatcher,FingerExtractor";

    /** The canonical input set is 500 ppi and this route accepts nothing else.
     *  Declaring a resolution is metadata; resampling a pixel is forbidden
     *  everywhere on this route (spec sections 6 and 7). */
    static final int REQUIRED_PPI = 500;

    /** What the delivered engine must already hold, before this program
     *  configures anything. Read out of a running client by Stage 11A; not one
     *  of them was chosen here. A runtime that disagrees is refused rather than
     *  silently corrected (spec section 8).
     *
     *  Kept in the same order and the same spelling as
     *  `fpbench.verifinger.identity.EXPECTED_RUNTIME_DEFAULTS`; a contract test
     *  parses this table out of this file and asserts the two agree. */
    static final String[][] EXPECTED_DEFAULTS = {
        {"Fingers.TemplateSize", "LARGE"},
        {"Fingers.ExtractionScenario", "0"},
        {"Fingers.FastExtraction", "false"},
        {"Fingers.QualityThreshold", "40"},
        {"Fingers.MinimalMinutiaCount", "10"},
        {"Fingers.DetectTips", "false"},
        {"Fingers.DetectLiveness", "false"},
        {"Fingers.LivenessConfidenceThreshold", "0"},
        {"Fingers.MaximalRotation", "180.0"},
        {"Matching.Scenario", "0"},
    };

    /** The one value this route sets, because `verify-finger` sets it. Not
     *  because anybody here measured LOW to be better (spec section 9). */
    static final String MATCHING_SPEED = "LOW";

    /** The same tutorial's threshold, kept so the official route is reproduced
     *  exactly — and then ignored, because the score is read under
     *  MATCH_NOT_FOUND too (spec section 10). */
    static final int OFFICIAL_SAMPLE_MATCHING_THRESHOLD = 48;

    // --------------------------------------------------------- status table

    /** The two statuses that carry a score. */
    private static final Set<NBiometricStatus> SCORE_BEARING = new LinkedHashSet<>(
        Arrays.asList(NBiometricStatus.OK, NBiometricStatus.MATCH_NOT_FOUND));

    /** Statuses that are VeriFinger's opinion of a fingerprint: a print it will
     *  not extract, a sample it judges unusable, a finger it cannot match.
     *  Every one of these is an algorithm outcome and is recorded per pair
     *  (spec section 13).
     *
     *  Written out rather than defaulted to, so that a status the vendor adds in
     *  a later release is reported as unclassified instead of being folded into
     *  "the print was bad". */
    private static final Set<NBiometricStatus> BIOMETRIC_STATUSES = new LinkedHashSet<>(
        Arrays.asList(
            NBiometricStatus.SOURCE_MISSING,
            NBiometricStatus.CLEANING_NEEDED,
            NBiometricStatus.OBJECTS_NOT_REMOVED,
            NBiometricStatus.OBJECT_MISSING,
            NBiometricStatus.OBJECT_NOT_FOUND,
            NBiometricStatus.TOO_FEW_OBJECTS,
            NBiometricStatus.TOO_MANY_OBJECTS,
            NBiometricStatus.BAD_OBJECT_SEQUENCE,
            NBiometricStatus.SPOOF_DETECTED,
            NBiometricStatus.MASK_DETECTED,
            NBiometricStatus.BAD_OBJECT,
            NBiometricStatus.BAD_DYNAMIC_RANGE,
            NBiometricStatus.BAD_EXPOSURE,
            NBiometricStatus.BAD_SHARPNESS,
            NBiometricStatus.TOO_NOISY,
            NBiometricStatus.BAD_CONTRAST,
            NBiometricStatus.BAD_LIGHTING,
            NBiometricStatus.OCCLUSION,
            NBiometricStatus.BAD_POSE,
            NBiometricStatus.TOO_FEW_FEATURES,
            NBiometricStatus.TOO_SOFT,
            NBiometricStatus.TOO_HARD,
            NBiometricStatus.MOTION_BLUR,
            NBiometricStatus.COMPRESSION_ARTIFACTS,
            NBiometricStatus.BAD_POSITION,
            NBiometricStatus.TOO_NORTH,
            NBiometricStatus.TOO_EAST,
            NBiometricStatus.TOO_SOUTH,
            NBiometricStatus.TOO_WEST,
            NBiometricStatus.TOO_CLOSE,
            NBiometricStatus.TOO_FAR,
            NBiometricStatus.BAD_SPEED,
            NBiometricStatus.TOO_SLOW,
            NBiometricStatus.TOO_FAST,
            NBiometricStatus.BAD_SIZE,
            NBiometricStatus.TOO_SHORT,
            NBiometricStatus.TOO_LONG,
            NBiometricStatus.TOO_NARROW,
            NBiometricStatus.TOO_WIDE,
            NBiometricStatus.TOO_SKEWED,
            NBiometricStatus.WRONG_DIRECTION,
            NBiometricStatus.WRONG_HAND,
            NBiometricStatus.TIPS,
            NBiometricStatus.TOO_FEW_SAMPLES,
            NBiometricStatus.INCOMPATIBLE_SAMPLES));

    // ------------------------------------------------------------- failures

    static final String CODE_INVALID_REQUEST = "invalid_request";
    static final String CODE_UNSUPPORTED_RESOLUTION = "unsupported_resolution";
    static final String CODE_INPUT_UNREADABLE = "input_unreadable";
    static final String CODE_IMAGE_DECODE_FAILED = "image_decode_failed";
    static final String CODE_LICENCE_NOT_OBTAINED = "licence_not_obtained";
    static final String CODE_RUNTIME_UNAVAILABLE = "runtime_unavailable";
    static final String CODE_RUNTIME_DEFAULTS_MISMATCH = "runtime_defaults_mismatch";
    /** The engine declined to produce a score for these two prints. One code,
     *  because `verify` returns one status for a call that both extracts and
     *  matches: Stage 11A provoked an unextractable reference and an
     *  unextractable candidate and got `BAD_OBJECT` for both. The vendor's own
     *  word travels beside it in `engine_status`, so nothing is lost by not
     *  inventing a second code this API cannot distinguish. */
    static final String CODE_EXTRACTION_FAILED = "extraction_failed";
    static final String CODE_ENGINE_TIMEOUT = "engine_timeout";
    static final String CODE_ENGINE_ERROR = "engine_error";
    static final String CODE_UNCLASSIFIED_ENGINE_STATUS = "unclassified_engine_status";
    static final String CODE_BRIDGE_FAILURE = "bridge_failure";

    static final String STAGE_REQUEST = "request";
    static final String STAGE_LICENSING = "licensing";
    static final String STAGE_ENGINE = "engine";
    static final String STAGE_INPUT = "input";
    static final String STAGE_VERIFY = "verify";
    static final String STAGE_SCORE = "score";

    /** The request fields this bridge accepts, and the complete list of them.
     *  Anything else is refused rather than ignored: a request carrying a pair
     *  kind or a threshold must fail loudly, not quietly do nothing
     *  (spec section 5). */
    private static final Set<String> REQUEST_FIELDS = new LinkedHashSet<>(
        Arrays.asList(
            "schema_version",
            "request_id",
            "left_image_path",
            "left_effective_ppi",
            "right_image_path",
            "right_effective_ppi"));

    public static void main(String[] args) {
        if (args.length != 1) {
            System.err.println("usage: VeriFingerBridge <version|compare>");
            System.exit(2);
            return;
        }
        try {
            if ("version".equals(args[0])) {
                Json.emit(version());
                return;
            }
            if ("compare".equals(args[0])) {
                Json.emit(compare(readStdin()));
                return;
            }
            System.err.println("unknown command: " + args[0]);
            System.exit(2);
        } catch (Throwable unexpected) {
            // Still one JSON object, always. A bridge that died silently would
            // be indistinguishable from a bridge that never started, and the
            // Python side would have to guess which.
            Map<String, Object> response = new LinkedHashMap<>();
            response.put("schema_version", SCHEMA_VERSION);
            response.put("bridge_protocol", BRIDGE_PROTOCOL);
            response.put("bridge_version", BRIDGE_VERSION);
            response.put("status", "failure");
            response.put("code", CODE_BRIDGE_FAILURE);
            response.put("stage", STAGE_ENGINE);
            response.put("message", describe(unexpected));
            response.put("exception_type", unexpected.getClass().getName());
            Json.emit(response);
            System.exit(3);
        }
    }

    // ------------------------------------------------------------- version

    /** What this runtime is, asked of the runtime rather than assumed.
     *
     *  Everything here is a property of the installation and of the JVM. There
     *  is no licence key, no activation identifier, no machine code and no
     *  absolute path: module locations are published as bare file names,
     *  because where a DLL lives is a fact about one computer (spec sections 4,
     *  38 and 39). */
    static Map<String, Object> version() {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("schema_version", SCHEMA_VERSION);
        response.put("bridge_protocol", BRIDGE_PROTOCOL);
        response.put("bridge_version", BRIDGE_VERSION);

        boolean licensed = false;
        String licenceDetail = "";
        try {
            NLicenseManager.setTrialMode(true);
            licensed = NLicense.obtain("/local", 5000, LICENCES);
        } catch (Throwable refused) {
            licenceDetail = describe(refused);
        }
        response.put("licences_requested", LICENCES);
        response.put("licences_obtained", licensed);
        response.put("licence_detail", licenceDetail);

        NBiometricClient client = null;
        try {
            client = new NBiometricClient();
            // The engine loads its native modules lazily; touching one property
            // forces that, so the inventory below is what this process really
            // loaded rather than what it might load later.
            client.getMatchingThreshold();
            response.put("runtime_started", true);
            response.put("loaded_modules", loadedModules());
            response.put("delivered_runtime_defaults", readDefaults(client));
            response.put("configured_settings", configuredSettings());
        } catch (Throwable unavailable) {
            response.put("runtime_started", false);
            response.put("loaded_modules", new ArrayList<Map<String, Object>>());
            response.put("delivered_runtime_defaults", new LinkedHashMap<String, String>());
            response.put("configured_settings", configuredSettings());
            response.put("runtime_detail", describe(unavailable));
        } finally {
            dispose(client);
        }

        response.put("java_version", System.getProperty("java.version"));
        response.put("java_vendor", System.getProperty("java.vendor"));
        response.put("java_vm_name", System.getProperty("java.vm.name"));
        response.put("os_name", System.getProperty("os.name"));
        response.put("os_arch", System.getProperty("os.arch"));
        response.put("required_ppi", REQUIRED_PPI);
        response.put("score_direction", "HIGHER_IS_BETTER");
        response.put("native_score_type", "java_int");
        response.put("decision_returned", false);
        return response;
    }

    /** The native modules this process actually loaded, each with its version.
     *
     *  Names and versions only. `NModule.getFileName()` is an absolute path on
     *  this machine and is deliberately reduced to its base name. */
    private static List<Map<String, Object>> loadedModules() {
        List<Map<String, Object>> modules = new ArrayList<>();
        try {
            for (NModule module : NModule.getLoadedModules()) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("name", safely(module::getName));
                row.put("product", safely(module::getProduct));
                row.put("company", safely(module::getCompany));
                row.put("version", safely(module::getVersion));
                row.put("file_name", new File(safely(module::getFileName)).getName());
                modules.add(row);
            }
        } catch (Throwable unreadable) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("name", "UNREADABLE:" + unreadable.getClass().getSimpleName());
            modules.add(row);
        }
        return modules;
    }

    // ------------------------------------------------------------- compare

    static Map<String, Object> compare(String payload) {
        Map<String, Object> request;
        try {
            request = Json.parseObject(payload);
        } catch (RuntimeException malformed) {
            return failure(null, CODE_INVALID_REQUEST, STAGE_REQUEST, malformed.getMessage(), null, null);
        }

        Set<String> unknown = new LinkedHashSet<>(request.keySet());
        unknown.removeAll(REQUEST_FIELDS);
        if (!unknown.isEmpty()) {
            // The one place benchmark knowledge could enter this process, closed.
            return failure(
                null, CODE_INVALID_REQUEST, STAGE_REQUEST,
                "the request carries fields this bridge may not receive: " + unknown,
                null, null);
        }

        String requestId = text(request, "request_id");
        String schema = text(request, "schema_version");
        if (requestId == null || schema == null) {
            return failure(requestId, CODE_INVALID_REQUEST, STAGE_REQUEST,
                "request_id and schema_version are required", null, null);
        }
        if (!SCHEMA_VERSION.equals(schema)) {
            return failure(requestId, CODE_INVALID_REQUEST, STAGE_REQUEST,
                "unsupported schema_version " + schema, null, null);
        }

        String leftPath = text(request, "left_image_path");
        String rightPath = text(request, "right_image_path");
        Integer leftPpi = integer(request, "left_effective_ppi");
        Integer rightPpi = integer(request, "right_effective_ppi");
        if (leftPath == null || rightPath == null || leftPpi == null || rightPpi == null) {
            return failure(requestId, CODE_INVALID_REQUEST, STAGE_REQUEST,
                "both image paths and both resolutions are required", null, null);
        }
        if (leftPpi != REQUIRED_PPI || rightPpi != REQUIRED_PPI) {
            return failure(requestId, CODE_UNSUPPORTED_RESOLUTION, STAGE_REQUEST,
                "this route runs at " + REQUIRED_PPI + " ppi only; the request "
                    + "declared " + leftPpi + " and " + rightPpi,
                null, null);
        }
        for (String[] side : new String[][] {{"left", leftPath}, {"right", rightPath}}) {
            File file = new File(side[1]);
            if (!file.isAbsolute()) {
                return failure(requestId, CODE_INVALID_REQUEST, STAGE_REQUEST,
                    side[0] + " image path must be absolute", side[0], null);
            }
            if (!file.isFile()) {
                return failure(requestId, CODE_INPUT_UNREADABLE, STAGE_INPUT,
                    side[0] + " image is not a readable file", side[0], null);
            }
        }

        long started = System.nanoTime();
        NBiometricClient client = null;
        NSubject reference = null;
        NSubject candidate = null;
        try {
            try {
                NLicenseManager.setTrialMode(true);
                if (!NLicense.obtain("/local", 5000, LICENCES)) {
                    return failure(requestId, CODE_LICENCE_NOT_OBTAINED, STAGE_LICENSING,
                        "the SDK refused the FingerExtractor and FingerMatcher licences",
                        null, null);
                }
            } catch (Throwable refused) {
                return failure(requestId, CODE_LICENCE_NOT_OBTAINED, STAGE_LICENSING,
                    describe(refused), null, refused.getClass().getName());
            }

            try {
                client = new NBiometricClient();
                client.getMatchingThreshold();
            } catch (Throwable unavailable) {
                return failure(requestId, CODE_RUNTIME_UNAVAILABLE, STAGE_ENGINE,
                    describe(unavailable), null, unavailable.getClass().getName());
            }

            // Read before write, always. A default read after configuration is
            // our own setting handed back under the vendor's name.
            String drift = defaultsMismatch(client);
            if (drift != null) {
                return failure(requestId, CODE_RUNTIME_DEFAULTS_MISMATCH, STAGE_ENGINE,
                    drift, null, null);
            }

            client.setFingersMatchingSpeed(NMatchingSpeed.LOW);
            client.setMatchingThreshold(OFFICIAL_SAMPLE_MATCHING_THRESHOLD);

            // Two subjects, two fingers, two extractions. Nothing is shared
            // between the sides, and nothing is reused when the two paths are
            // the same file — which is exactly the SELF case (spec section 14).
            try {
                reference = subjectOf(new File(leftPath));
            } catch (Throwable failed) {
                return failure(requestId, CODE_IMAGE_DECODE_FAILED, STAGE_INPUT,
                    describe(failed), "left", failed.getClass().getName());
            }
            try {
                candidate = subjectOf(new File(rightPath));
            } catch (Throwable failed) {
                return failure(requestId, CODE_IMAGE_DECODE_FAILED, STAGE_INPUT,
                    describe(failed), "right", failed.getClass().getName());
            }

            NBiometricStatus status;
            long verifyStarted = System.nanoTime();
            try {
                status = client.verify(reference, candidate);
            } catch (Throwable failed) {
                return failure(requestId, CODE_ENGINE_ERROR, STAGE_VERIFY,
                    describe(failed), null, failed.getClass().getName());
            }
            double verifyMillis = (System.nanoTime() - verifyStarted) / 1_000_000.0;

            // Read *after* the verify call, deliberately. `setFileName` is lazy:
            // the engine loads the image as part of the route, and asking for it
            // beforehand would both return nothing and insert a load the
            // official sample does not perform. Afterwards the resolution the
            // engine actually saw is available, which is the number worth
            // checking — and worth recording on every stored result
            // (spec section 7).
            String leftResolution = observedResolution(reference);
            String rightResolution = observedResolution(candidate);
            String resolutionProblem = resolutionProblem(leftResolution, "left");
            if (resolutionProblem == null) {
                resolutionProblem = resolutionProblem(rightResolution, "right");
            }
            if (resolutionProblem != null) {
                return failure(requestId, CODE_UNSUPPORTED_RESOLUTION, STAGE_INPUT,
                    resolutionProblem, null, null);
            }

            if (!SCORE_BEARING.contains(status)) {
                Map<String, Object> response = classify(requestId, status);
                response.put("timings_ms", timings(started, verifyMillis));
                return response;
            }

            int score;
            try {
                score = reference.getMatchingResults().get(0).getScore();
            } catch (Throwable unreadable) {
                return failure(requestId, CODE_ENGINE_ERROR, STAGE_SCORE,
                    "the engine reported " + status + " and produced no readable "
                        + "matching result: " + describe(unreadable),
                    null, unreadable.getClass().getName());
            }

            Map<String, Object> response = new LinkedHashMap<>();
            response.put("schema_version", SCHEMA_VERSION);
            response.put("bridge_protocol", BRIDGE_PROTOCOL);
            response.put("bridge_version", BRIDGE_VERSION);
            response.put("request_id", requestId);
            response.put("status", "success");
            response.put("score", score);
            response.put("score_direction", "HIGHER_IS_BETTER");
            response.put("native_score_type", "java_int");
            response.put("engine_status", String.valueOf(status));
            response.put("extraction_count", 2);
            response.put("left_image_ppi", leftResolution);
            response.put("right_image_ppi", rightResolution);
            response.put("timings_ms", timings(started, verifyMillis));
            return response;
        } finally {
            dispose(reference);
            dispose(candidate);
            dispose(client);
        }
    }

    /** One subject, built the way `verify-finger` builds one. */
    private static NSubject subjectOf(File image) {
        NSubject subject = new NSubject();
        NFinger finger = new NFinger();
        finger.setFileName(image.getAbsolutePath());
        subject.getFingers().add(finger);
        return subject;
    }

    /** The resolution the engine saw, as ``horizontal x vertical``.
     *
     *  ``"unavailable"`` when the engine did not retain the loaded image, which
     *  is a fact worth recording rather than an error: on a route whose inputs
     *  are a verified 500 ppi set, the request's own declaration is already the
     *  binding requirement (spec section 7). */
    private static String observedResolution(NSubject subject) {
        try {
            NFinger finger = subject.getFingers().get(0);
            NImage image = finger.getImage();
            if (image == null) {
                return "unavailable";
            }
            return trim(image.getHorzResolution()) + "x" + trim(image.getVertResolution());
        } catch (Throwable unreadable) {
            return "unavailable";
        }
    }

    private static String trim(float value) {
        return value == Math.rint(value)
            ? String.valueOf((long) value)
            : String.valueOf(value);
    }

    /** Confirm the image the engine loaded declares the resolution this route
     *  runs at. Confirmation, not correction: the canonical set is 500 ppi in
     *  its own pHYs chunk, so an image that says otherwise is not from that set,
     *  and rescaling it here would be exactly the preprocessing this route
     *  forbids (spec sections 6 and 7). */
    private static String resolutionProblem(String observed, String side) {
        if ("unavailable".equals(observed)) {
            return null;
        }
        String expected = REQUIRED_PPI + "x" + REQUIRED_PPI;
        if (expected.equals(observed)) {
            return null;
        }
        return side + " image declares " + observed + " ppi, and this route runs "
            + "at " + expected + " only";
    }

    /** Name a non-score engine status, or refuse to name it. */
    private static Map<String, Object> classify(String requestId, NBiometricStatus status) {
        String name = String.valueOf(status);
        if (BIOMETRIC_STATUSES.contains(status)) {
            // Extraction and matching both surface as one status from behind a
            // single verify call, so the code says what the engine said and the
            // Python side does not pretend to know which half declined.
            return failure(requestId, CODE_EXTRACTION_FAILED, STAGE_VERIFY,
                "the engine reported " + name + " and produced no score",
                null, null, name);
        }
        if (status == NBiometricStatus.TIMEOUT) {
            return failure(requestId, CODE_ENGINE_TIMEOUT, STAGE_VERIFY,
                "the engine timed out", null, null, name);
        }
        if (status == NBiometricStatus.NONE
            || status == NBiometricStatus.CANCELED
            || status == NBiometricStatus.SOURCE_NOT_FOUND
            || status == NBiometricStatus.INCOMPATIBLE_SOURCE
            || status == NBiometricStatus.ID_NOT_FOUND
            || status == NBiometricStatus.DUPLICATE_ID
            || status == NBiometricStatus.DUPLICATE_FOUND
            || status == NBiometricStatus.CONFLICT
            || status == NBiometricStatus.INVALID_OPERATIONS
            || status == NBiometricStatus.INVALID_ID
            || status == NBiometricStatus.INVALID_QUERY
            || status == NBiometricStatus.INVALID_PROPERTY_VALUE
            || status == NBiometricStatus.INVALID_FIELD_VALUE
            || status == NBiometricStatus.INVALID_SAMPLE_RESOLUTION
            || status == NBiometricStatus.OPERATION_NOT_SUPPORTED
            || status == NBiometricStatus.OPERATION_NOT_ACTIVATED
            || status == NBiometricStatus.SOURCE_ERROR
            || status == NBiometricStatus.CAPTURE_ERROR
            || status == NBiometricStatus.COMMUNICATION_ERROR
            || status == NBiometricStatus.INTERNAL_ERROR) {
            return failure(requestId, CODE_ENGINE_ERROR, STAGE_VERIFY,
                "the engine reported " + name + ", which is a fault of the "
                    + "installation rather than of the fingerprint",
                null, null, name);
        }
        // A status this bridge has never been told about. Refusing to guess is
        // the point: an unknown outcome silently counted as "a bad print" would
        // be a defect wearing a finding's clothes (spec section 31).
        return failure(requestId, CODE_UNCLASSIFIED_ENGINE_STATUS, STAGE_VERIFY,
            "the engine reported " + name + ", which this bridge does not "
                + "classify; classify it deliberately rather than guessing",
            null, null, name);
    }

    // -------------------------------------------------------- the defaults

    private static Map<String, String> readDefaults(NBiometricClient client) {
        Map<String, String> values = new LinkedHashMap<>();
        for (String[] entry : EXPECTED_DEFAULTS) {
            values.put(entry[0], readProperty(client, entry[0]));
        }
        return values;
    }

    private static Map<String, String> configuredSettings() {
        Map<String, String> values = new LinkedHashMap<>();
        values.put("Fingers.MatchingSpeed", MATCHING_SPEED);
        values.put("Matching.Threshold", String.valueOf(OFFICIAL_SAMPLE_MATCHING_THRESHOLD));
        return values;
    }

    /** Which delivered default disagrees with the frozen profile, if any. */
    private static String defaultsMismatch(NBiometricClient client) {
        List<String> differences = new ArrayList<>();
        for (String[] entry : EXPECTED_DEFAULTS) {
            String found = readProperty(client, entry[0]);
            if (!entry[1].equals(found)) {
                differences.add(entry[0] + "=" + found + " (expected " + entry[1] + ")");
            }
        }
        if (differences.isEmpty()) {
            return null;
        }
        return "the delivered runtime defaults are not the ones this route was "
            + "qualified against: " + String.join(", ", differences);
    }

    private static String readProperty(NBiometricClient client, String name) {
        try {
            Object value = client.getProperty(name);
            return value == null ? "null" : String.valueOf(value);
        } catch (Throwable unreadable) {
            return "UNREADABLE:" + unreadable.getClass().getSimpleName();
        }
    }

    // ----------------------------------------------------------- machinery

    private static Map<String, Object> failure(
            String requestId, String code, String stage, String message,
            String side, String exceptionType) {
        return failure(requestId, code, stage, message, side, exceptionType, null);
    }

    private static Map<String, Object> failure(
            String requestId, String code, String stage, String message,
            String side, String exceptionType, String engineStatus) {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("schema_version", SCHEMA_VERSION);
        response.put("bridge_protocol", BRIDGE_PROTOCOL);
        response.put("bridge_version", BRIDGE_VERSION);
        if (requestId != null) {
            response.put("request_id", requestId);
        }
        response.put("status", "failure");
        response.put("code", code);
        response.put("stage", stage);
        response.put("message", message == null ? code : message);
        if (side != null) {
            response.put("side", side);
        }
        if (exceptionType != null) {
            response.put("exception_type", exceptionType);
        }
        if (engineStatus != null) {
            response.put("engine_status", engineStatus);
        }
        return response;
    }

    private static Map<String, Object> timings(long started, double verifyMillis) {
        Map<String, Object> timings = new LinkedHashMap<>();
        timings.put("bridge_total", (System.nanoTime() - started) / 1_000_000.0);
        timings.put("verify", verifyMillis);
        return timings;
    }

    private static void dispose(Object disposable) {
        if (disposable == null) {
            return;
        }
        try {
            if (disposable instanceof NSubject) {
                ((NSubject) disposable).dispose();
            } else if (disposable instanceof NBiometricClient) {
                ((NBiometricClient) disposable).dispose();
            }
        } catch (Throwable ignored) {
            // Disposal noise must never replace the answer already computed.
        }
    }

    /** A one-line, path-free rendering of a throwable. */
    private static String describe(Throwable error) {
        String message = error.getMessage();
        String rendered = error.getClass().getSimpleName()
            + (message == null ? "" : ": " + message);
        rendered = rendered.replace('\n', ' ').replace('\r', ' ');
        return rendered.length() > 400 ? rendered.substring(0, 400) : rendered;
    }

    private interface Reader {
        Object read() throws Exception;
    }

    private static String safely(Reader reader) {
        try {
            Object value = reader.read();
            return value == null ? "null" : String.valueOf(value);
        } catch (Throwable unreadable) {
            return "UNREADABLE:" + unreadable.getClass().getSimpleName();
        }
    }

    private static String text(Map<String, Object> request, String key) {
        Object value = request.get(key);
        return value instanceof String ? (String) value : null;
    }

    private static Integer integer(Map<String, Object> request, String key) {
        Object value = request.get(key);
        if (value instanceof Long) {
            return (int) (long) (Long) value;
        }
        if (value instanceof Integer) {
            return (Integer) value;
        }
        return null;
    }

    private static String readStdin() {
        try (InputStream stream = System.in) {
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            byte[] block = new byte[8192];
            int read;
            while ((read = stream.read(block)) > 0) {
                buffer.write(block, 0, read);
            }
            return buffer.toString(StandardCharsets.UTF_8);
        } catch (Exception unreadable) {
            throw new IllegalStateException("the request could not be read", unreadable);
        }
    }

    private VeriFingerBridge() {
    }

    // ------------------------------------------------------------------ JSON
    //
    // Written rather than depended on. A JSON library would be a third-party
    // component this stage would have to enrol, pin and publish — for one flat
    // object in and one shallow object out.

    static final class Json {

        static void emit(Map<String, Object> value) {
            StringBuilder out = new StringBuilder();
            write(out, value);
            System.out.println(out);
            System.out.flush();
        }

        @SuppressWarnings("unchecked")
        static void write(StringBuilder out, Object value) {
            if (value == null) {
                out.append("null");
            } else if (value instanceof Map) {
                out.append('{');
                boolean first = true;
                for (Map.Entry<String, Object> entry : ((Map<String, Object>) value).entrySet()) {
                    if (!first) {
                        out.append(',');
                    }
                    first = false;
                    writeString(out, entry.getKey());
                    out.append(':');
                    write(out, entry.getValue());
                }
                out.append('}');
            } else if (value instanceof List) {
                out.append('[');
                boolean first = true;
                for (Object item : (List<Object>) value) {
                    if (!first) {
                        out.append(',');
                    }
                    first = false;
                    write(out, item);
                }
                out.append(']');
            } else if (value instanceof Boolean || value instanceof Number) {
                out.append(value);
            } else {
                writeString(out, String.valueOf(value));
            }
        }

        private static void writeString(StringBuilder out, String value) {
            out.append('"');
            for (int i = 0; i < value.length(); i++) {
                char c = value.charAt(i);
                switch (c) {
                    case '"': out.append("\\\""); break;
                    case '\\': out.append("\\\\"); break;
                    case '\n': out.append("\\n"); break;
                    case '\r': out.append("\\r"); break;
                    case '\t': out.append("\\t"); break;
                    default:
                        if (c < 0x20) {
                            out.append(String.format("\\u%04x", (int) c));
                        } else {
                            out.append(c);
                        }
                }
            }
            out.append('"');
        }

        /** Parse one flat JSON object of strings, integers and booleans.
         *
         *  Deliberately narrow. The request shape is six scalar fields, and a
         *  parser that accepted nested documents would be accepting a shape
         *  this bridge has no use for. */
        static Map<String, Object> parseObject(String payload) {
            String text = payload == null ? "" : payload.trim();
            if (text.isEmpty()) {
                throw new IllegalArgumentException("the request is empty");
            }
            Cursor cursor = new Cursor(text);
            cursor.skipWhitespace();
            cursor.expect('{');
            Map<String, Object> result = new LinkedHashMap<>();
            cursor.skipWhitespace();
            if (cursor.peek() == '}') {
                cursor.next();
                cursor.requireEnd();
                return result;
            }
            while (true) {
                cursor.skipWhitespace();
                String key = cursor.readString();
                cursor.skipWhitespace();
                cursor.expect(':');
                cursor.skipWhitespace();
                Object value = cursor.readScalar();
                if (result.put(key, value) != null) {
                    throw new IllegalArgumentException("duplicate field " + key);
                }
                cursor.skipWhitespace();
                char c = cursor.next();
                if (c == '}') {
                    break;
                }
                if (c != ',') {
                    throw new IllegalArgumentException("expected , or } at " + cursor.at());
                }
            }
            cursor.requireEnd();
            return result;
        }

        private static final class Cursor {
            private final String text;
            private int index;

            Cursor(String text) {
                this.text = text;
            }

            int at() {
                return index;
            }

            void skipWhitespace() {
                while (index < text.length() && Character.isWhitespace(text.charAt(index))) {
                    index++;
                }
            }

            char peek() {
                if (index >= text.length()) {
                    throw new IllegalArgumentException("the request ends early");
                }
                return text.charAt(index);
            }

            char next() {
                char c = peek();
                index++;
                return c;
            }

            void expect(char expected) {
                char c = next();
                if (c != expected) {
                    throw new IllegalArgumentException(
                        "expected " + expected + " at " + (index - 1));
                }
            }

            void requireEnd() {
                skipWhitespace();
                if (index != text.length()) {
                    throw new IllegalArgumentException(
                        "the request holds more than one document");
                }
            }

            String readString() {
                expect('"');
                StringBuilder out = new StringBuilder();
                while (true) {
                    char c = next();
                    if (c == '"') {
                        return out.toString();
                    }
                    if (c != '\\') {
                        out.append(c);
                        continue;
                    }
                    char escaped = next();
                    switch (escaped) {
                        case '"': out.append('"'); break;
                        case '\\': out.append('\\'); break;
                        case '/': out.append('/'); break;
                        case 'b': out.append('\b'); break;
                        case 'f': out.append('\f'); break;
                        case 'n': out.append('\n'); break;
                        case 'r': out.append('\r'); break;
                        case 't': out.append('\t'); break;
                        case 'u':
                            if (index + 4 > text.length()) {
                                throw new IllegalArgumentException("truncated escape");
                            }
                            out.append((char) Integer.parseInt(
                                text.substring(index, index + 4), 16));
                            index += 4;
                            break;
                        default:
                            throw new IllegalArgumentException(
                                "unsupported escape \\" + escaped);
                    }
                }
            }

            Object readScalar() {
                char c = peek();
                if (c == '"') {
                    return readString();
                }
                if (c == 't' || c == 'f' || c == 'n') {
                    String word = readWord();
                    if ("true".equals(word)) {
                        return Boolean.TRUE;
                    }
                    if ("false".equals(word)) {
                        return Boolean.FALSE;
                    }
                    if ("null".equals(word)) {
                        return null;
                    }
                    throw new IllegalArgumentException("unexpected token " + word);
                }
                int start = index;
                if (c == '-' || c == '+') {
                    index++;
                }
                while (index < text.length() && Character.isDigit(text.charAt(index))) {
                    index++;
                }
                if (index == start) {
                    throw new IllegalArgumentException("unexpected character at " + index);
                }
                if (index < text.length()
                    && (text.charAt(index) == '.'
                        || text.charAt(index) == 'e'
                        || text.charAt(index) == 'E')) {
                    // Resolutions are whole numbers of pixels per inch. A
                    // fractional one means the caller is not this adapter.
                    throw new IllegalArgumentException(
                        "only integers are accepted at " + index);
                }
                return Long.parseLong(text.substring(start, index));
            }

            private String readWord() {
                int start = index;
                while (index < text.length()
                    && Character.isLetter(text.charAt(index))) {
                    index++;
                }
                return text.substring(start, index);
            }
        }

        private Json() {
        }
    }
}
