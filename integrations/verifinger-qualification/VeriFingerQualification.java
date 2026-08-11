// The bounded Stage 11A qualification pass, in upstream's own Java binding.
//
// This program answers the nine Stage 11A gates that cannot be answered by
// reading files. It is deliberately small: one pair of synthetic fixtures, a
// handful of comparisons, and a JSON report on stdout. It is not a benchmark, it
// never sees SD300, and it prints no score.
//
// **No score value leaves this process.** Determinism is proved by emitting a
// SHA-256 over the canonical decimal form of each score and comparing digests,
// which is the same trick this repository uses everywhere else it needs to
// compare a quantity without publishing it. The driver that invokes this program
// records equalities and counts only.
//
// The route is upstream's own `verify-finger` tutorial and nothing else: obtain
// the two finger licences, construct one NBiometricClient, set only what that
// tutorial sets, and read the score from the reference subject's first matching
// result under both OK and MATCH_NOT_FOUND. Settings the tutorial does not touch
// are *read*, never set — that is the whole point of the pass (docs/adr/0105).
//
// Invoked as:
//     java VeriFingerQualification <fixtureDir> <passLabel>
// and it writes one JSON object to stdout.

import com.neurotec.biometrics.NBiometricStatus;
import com.neurotec.biometrics.NFinger;
import com.neurotec.biometrics.NMatchingSpeed;
import com.neurotec.biometrics.NSubject;
import com.neurotec.biometrics.client.NBiometricClient;
import com.neurotec.licensing.NLicense;
import com.neurotec.licensing.NLicenseManager;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class VeriFingerQualification {

    /** The licences upstream's own 1:1 tutorial obtains, in its order. */
    private static final String LICENCES = "FingerMatcher,FingerExtractor";

    /** The documented parameter names, read through the generic property
     *  interface rather than through bean accessors.
     *
     *  Two reasons. The manual documents these names, so a value read under one
     *  is a value under the name the vendor published; and several documented
     *  parameters have no dedicated Java accessor at all, so a bean-only pass
     *  would silently report a shorter profile than the one that exists. */
    private static final String[] EXTRACTION_PARAMETERS = {
        "Fingers.TemplateSize",
        "Fingers.ExtractionScenario",
        "Fingers.FastExtraction",
        "Fingers.QualityThreshold",
        "Fingers.MinimalMinutiaCount",
        "Fingers.DetectTips",
        "Fingers.DetectLiveness",
        "Fingers.LivenessConfidenceThreshold",
        "Fingers.DeterminePatternClass",
        "Fingers.ReturnBinarizedImage",
        "Fingers.CalculateNfiq",
        "Fingers.CalculateNfiq2",
        "Fingers.CalculateNfiq21",
        "MaximalThreadCount",
    };

    private static final String[] MATCHING_PARAMETERS = {
        "Fingers.MatchingSpeed",
        "Fingers.MaximalRotation",
        "Matching.Scenario",
        "Matching.WithDetails",
        "Matching.MaximalResultCount",
        "Matching.FirstResultOnly",
    };

    private static long extractionNanos = 0L;
    private static long extractionCount = 0L;
    private static long matchingNanos = 0L;
    private static long matchingCount = 0L;
    private static int scoresProduced = 0;

    public static void main(String[] args) {
        long startedAt = System.nanoTime();
        if (args.length < 2) {
            System.err.println("usage: VeriFingerQualification <fixtureDir> <passLabel>");
            System.exit(2);
        }
        File fixtures = new File(args[0]);
        String passLabel = args[1];

        Map<String, Object> report = new LinkedHashMap<>();
        report.put("pass_label", passLabel);

        NBiometricClient client = null;
        try {
            // Trial mode, exactly as the shipped TrialFlag.txt and every upstream
            // sample set it. Nothing here bypasses or resets anything.
            NLicenseManager.setTrialMode(true);
            boolean obtained = NLicense.obtain("/local", 5000, LICENCES);
            report.put("licences_requested", LICENCES);
            report.put("licences_obtained", obtained);
            if (!obtained) {
                report.put("error", "LICENCES_NOT_OBTAINED");
                emit(report);
                System.exit(3);
            }

            client = new NBiometricClient();

            // --- what the authoritative sample sets, and only that ------------
            client.setFingersMatchingSpeed(NMatchingSpeed.LOW);
            report.put("settings_set_by_this_pass", new String[] {
                "Fingers.MatchingSpeed=Low (verify-finger sets it)",
            });
            report.put("threshold_set_by_this_pass", false);

            // --- delivered runtime defaults ----------------------------------
            report.put("delivered_extraction_defaults", readParameters(client, EXTRACTION_PARAMETERS));
            report.put("delivered_matching_defaults", readParameters(client, MATCHING_PARAMETERS));

            long startupNanos = System.nanoTime() - startedAt;

            // --- the fixtures ------------------------------------------------
            File a = new File(fixtures, "fixture_a.png");
            File b = new File(fixtures, "fixture_b.png");
            File invalid = new File(fixtures, "fixture_invalid.png");
            File unsupported = new File(fixtures, "fixture_unsupported.dat");
            File missing = new File(fixtures, "fixture_absent.png");

            // --- pair orientation: both orderings ----------------------------
            String forward = scoreDigest(client, a, b);
            String reverse = scoreDigest(client, b, a);
            Map<String, Object> orientation = new LinkedHashMap<>();
            orientation.put("orderings_scored", 2);
            orientation.put("score_digests_equal", forward != null && forward.equals(reverse));
            orientation.put("both_orderings_produced_a_score", forward != null && reverse != null);
            report.put("pair_orientation", orientation);

            // --- SELF(A, A) as two independent extractions -------------------
            // Two NSubjects built from the same file. Nothing is reused between
            // them: each carries its own NFinger and each is extracted by the
            // engine on its own, which is what the SELF rule requires.
            String selfDigest = scoreDigest(client, a, a);
            Map<String, Object> self = new LinkedHashMap<>();
            self.put("independent_extractions", 2);
            self.put("representation_reused", false);
            self.put("score_present", selfDigest != null);
            self.put("equals_cross_pair_digest", selfDigest != null && selfDigest.equals(forward));
            report.put("self_semantics", self);

            // --- determinism, two of the three levels ------------------------
            // The third level is a fresh process, which this program cannot
            // perform on itself; the driver runs it twice and compares.
            String sameObjects = scoreDigest(client, a, b);
            NBiometricClient fresh = new NBiometricClient();
            fresh.setFingersMatchingSpeed(NMatchingSpeed.LOW);
            String freshObjects = scoreDigest(fresh, a, b);
            fresh.dispose();
            Map<String, Object> determinism = new LinkedHashMap<>();
            determinism.put("same objects, same process", forward.equals(sameObjects));
            determinism.put("fresh objects, same process", forward.equals(freshObjects));
            report.put("determinism_within_process", determinism);
            report.put("pair_score_digest", forward);

            // --- failure semantics -------------------------------------------
            List<Map<String, Object>> failures = new ArrayList<>();
            failures.add(failureCase(client, "invalid image", a, invalid));
            failures.add(failureCase(client, "unsupported image", a, unsupported));
            failures.add(failureCase(client, "extraction failure", a, missing));
            failures.add(failureCase(client, "matcher failure", missing, missing));
            report.put("failure_semantics", failures);

            // --- feasibility, to an order of magnitude -----------------------
            Map<String, Object> feasibility = new LinkedHashMap<>();
            feasibility.put("startup_millis", startupNanos / 1_000_000L);
            feasibility.put("extraction_invocations", extractionCount);
            feasibility.put("extraction_millis_total", extractionNanos / 1_000_000L);
            feasibility.put("matching_invocations", matchingCount);
            feasibility.put("matching_millis_total", matchingNanos / 1_000_000L);
            Runtime runtime = Runtime.getRuntime();
            feasibility.put("peak_heap_megabytes",
                (runtime.totalMemory() - runtime.freeMemory()) / (1024L * 1024L));
            feasibility.put("accelerator_required", false);
            report.put("feasibility", feasibility);

            report.put("qualification_scores_produced", scoresProduced);
            report.put("benchmark_scores_produced", 0);
            report.put("sd300_used", false);
            report.put("java_runtime_version", System.getProperty("java.version"));
            report.put("java_vendor", System.getProperty("java.vendor"));
            report.put("operating_system", System.getProperty("os.name"));
            report.put("architecture", System.getProperty("os.arch"));
            report.put("ok", true);
            emit(report);
        } catch (Throwable error) {
            report.put("ok", false);
            report.put("error", error.getClass().getName() + ": " + error.getMessage());
            emit(report);
            System.exit(4);
        } finally {
            if (client != null) {
                client.dispose();
            }
        }
    }

    /** Every documented parameter, read through the generic property interface. */
    private static Map<String, String> readParameters(NBiometricClient client, String[] names) {
        Map<String, String> values = new LinkedHashMap<>();
        for (String name : names) {
            try {
                Object value = client.getProperty(name, Object.class);
                values.put(name, value == null ? "null" : String.valueOf(value));
            } catch (Throwable unreadable) {
                // A parameter the delivered package does not expose is recorded
                // as unreadable rather than omitted: a shorter profile that
                // looked complete would be the worst of the three outcomes.
                values.put(name, "UNREADABLE:" + unreadable.getClass().getSimpleName());
            }
        }
        return values;
    }

    /** One comparison, reported as a digest of its score and never as the score. */
    private static String scoreDigest(NBiometricClient client, File reference, File candidate) {
        NSubject referenceSubject = null;
        NSubject candidateSubject = null;
        try {
            long extractionStart = System.nanoTime();
            referenceSubject = subjectOf(reference);
            candidateSubject = subjectOf(candidate);
            extractionNanos += System.nanoTime() - extractionStart;
            extractionCount += 2;

            long matchStart = System.nanoTime();
            NBiometricStatus status = client.verify(referenceSubject, candidateSubject);
            matchingNanos += System.nanoTime() - matchStart;
            matchingCount += 1;

            if (status != NBiometricStatus.OK && status != NBiometricStatus.MATCH_NOT_FOUND) {
                return null;
            }
            int score = referenceSubject.getMatchingResults().get(0).getScore();
            scoresProduced += 1;
            return sha256(Integer.toString(score));
        } catch (Throwable failed) {
            return null;
        } finally {
            if (referenceSubject != null) referenceSubject.dispose();
            if (candidateSubject != null) candidateSubject.dispose();
        }
    }

    /** One failure class, reported by the outcome it produced. */
    private static Map<String, Object> failureCase(
            NBiometricClient client, String failureClass, File reference, File candidate) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("failure_class", failureClass);
        NSubject referenceSubject = null;
        NSubject candidateSubject = null;
        try {
            referenceSubject = subjectOf(reference);
            candidateSubject = subjectOf(candidate);
            NBiometricStatus status = client.verify(referenceSubject, candidateSubject);
            row.put("status", String.valueOf(status));
            boolean scored = status == NBiometricStatus.OK
                || status == NBiometricStatus.MATCH_NOT_FOUND;
            row.put("score_present", scored);
            row.put("raised", false);
        } catch (Throwable failed) {
            row.put("status", failed.getClass().getSimpleName());
            row.put("score_present", false);
            row.put("raised", true);
        } finally {
            if (referenceSubject != null) referenceSubject.dispose();
            if (candidateSubject != null) candidateSubject.dispose();
        }
        return row;
    }

    private static NSubject subjectOf(File image) {
        NSubject subject = new NSubject();
        NFinger finger = new NFinger();
        finger.setFileName(image.getAbsolutePath());
        subject.getFingers().add(finger);
        return subject;
    }

    private static String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder(bytes.length * 2);
            for (byte b : bytes) {
                hex.append(String.format("%02x", b));
            }
            return hex.toString();
        } catch (Exception impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    // A three-hundred-line JSON dependency would be a third-party component this
    // stage would have to enrol, for one object. This writes what it needs.
    @SuppressWarnings("unchecked")
    private static void emit(Object value) {
        StringBuilder out = new StringBuilder();
        write(out, value);
        System.out.println(out);
    }

    @SuppressWarnings("unchecked")
    private static void write(StringBuilder out, Object value) {
        if (value == null) {
            out.append("null");
        } else if (value instanceof Map) {
            out.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> entry : ((Map<String, Object>) value).entrySet()) {
                if (!first) out.append(',');
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
                if (!first) out.append(',');
                first = false;
                write(out, item);
            }
            out.append(']');
        } else if (value instanceof String[]) {
            out.append('[');
            String[] items = (String[]) value;
            for (int i = 0; i < items.length; i++) {
                if (i > 0) out.append(',');
                writeString(out, items[i]);
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
}
