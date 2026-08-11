// The bounded Stage 11A qualification pass, in upstream's own Java binding.
//
// This program answers the nine Stage 11A gates that cannot be answered by
// reading files. It is deliberately small: two synthetic fixtures, a handful of
// comparisons, and a JSON report on stdout. It is not a benchmark, it never sees
// SD300, and it prints no score.
//
// **No score value leaves this process.** Determinism is proved by emitting a
// SHA-256 over the canonical decimal form of each score and comparing digests,
// which is the same trick this repository uses everywhere else it needs to
// compare a quantity without publishing it.
//
// **The route is upstream's own `verify-finger` and nothing else**: obtain the
// two finger licences, construct one NBiometricClient, set only what that
// tutorial sets, and read the score from the reference subject's first matching
// result under both OK and MATCH_NOT_FOUND. Settings the tutorial does not touch
// are *read*, never set — that is the point of the pass (docs/adr/0105).
//
// **One number is measured, not two.** `verify(reference, candidate)` loads both
// images, extracts both templates and matches them behind a single call, so the
// only honest latency is end to end. Timing the construction of two NSubject
// objects and calling it extraction latency would measure object allocation.
//
// Four modes, because three of the failure classes are about a runtime that is
// missing something and a process cannot un-load what it has already loaded:
//
//     full        the licensed route on the complete installation
//     restart     the same, run again by the driver for the third determinism level
//     no-models   the licensed route against an installation without Fingers.ndf
//     no-licence  the complete installation, with no licence obtained
//
// Invoked as:
//     java VeriFingerQualification <fixtureDir> <mode>
// and it writes one JSON object to stdout. If the runtime started and something
// then went wrong, it still writes one, with ok=false and a stage label — an
// execution that failed is a finding, and must not look like an execution that
// never happened.

import com.neurotec.biometrics.NBiometricStatus;
import com.neurotec.biometrics.NFinger;
import com.neurotec.biometrics.NMatchingSpeed;
import com.neurotec.biometrics.NSubject;
import com.neurotec.biometrics.client.NBiometricClient;
import com.neurotec.lang.NModule;
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
     *  The manual documents these names, so a value read under one is a value
     *  under the name the vendor published; and several documented parameters
     *  have no dedicated Java accessor, so a bean-only pass would silently
     *  report a shorter profile than the one that exists. */
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

    private static long verifyNanos = 0L;
    private static long verifyCount = 0L;
    private static int scoresProduced = 0;

    private static final Map<String, Object> REPORT = new LinkedHashMap<>();

    public static void main(String[] args) {
        long startedAt = System.nanoTime();
        if (args.length < 2) {
            System.err.println("usage: VeriFingerQualification <fixtureDir> <mode>");
            System.exit(2);
        }
        File fixtures = new File(args[0]);
        String mode = args[1];

        REPORT.put("mode", mode);
        REPORT.put("ok", false);
        REPORT.put("stage", "starting");
        REPORT.put("runtime_started", false);

        NBiometricClient client = null;
        try {
            // Trial mode, exactly as the shipped TrialFlag.txt and every upstream
            // sample set it. Nothing here bypasses or resets anything.
            REPORT.put("stage", "licensing");
            NLicenseManager.setTrialMode(true);

            boolean wantsLicence = !"no-licence".equals(mode);
            boolean obtained = false;
            if (wantsLicence) {
                obtained = NLicense.obtain("/local", 5000, LICENCES);
            }
            REPORT.put("licences_requested", wantsLicence ? LICENCES : "");
            REPORT.put("licences_obtained", obtained);
            if (wantsLicence && !obtained) {
                REPORT.put("stage", "licensing");
                REPORT.put("error", "LICENCES_NOT_OBTAINED");
                emit(REPORT);
                System.exit(3);
            }

            REPORT.put("stage", "engine-construction");
            client = new NBiometricClient();
            // The engine loads its native modules lazily; touching one property
            // forces that before the module inventory is read.
            client.getMatchingThreshold();
            REPORT.put("runtime_started", true);

            // --- the runtime's own identity, from the loaded modules ----------
            // Not the Java version. `NModule.getLoadedModules()` reports the
            // native Neurotechnology modules this process actually loaded, each
            // with its own product name and version, which is what "the version
            // the running library reports" means (spec correction 6).
            REPORT.put("loaded_modules", loadedModules());

            if ("no-licence".equals(mode)) {
                // The controlled cause for the licence failure class: a complete
                // installation, an engine that constructed, and no licence.
                REPORT.put("stage", "failure-probe");
                REPORT.put(
                    "failure_semantics",
                    List.of(failureCase(
                        client,
                        "licence or runtime failure",
                        new File(fixtures, "fixture_a.png"),
                        new File(fixtures, "fixture_b.png"))));
                REPORT.put("ok", true);
                REPORT.put("stage", "complete");
                emit(REPORT);
                return;
            }

            if ("no-models".equals(mode)) {
                // The controlled cause for the missing-component class: the
                // engine is licensed and constructed and the algorithm's own
                // data file is not on disk.
                REPORT.put("stage", "failure-probe");
                REPORT.put(
                    "failure_semantics",
                    List.of(failureCase(
                        client,
                        "missing runtime component",
                        new File(fixtures, "fixture_a.png"),
                        new File(fixtures, "fixture_b.png"))));
                REPORT.put("ok", true);
                REPORT.put("stage", "complete");
                emit(REPORT);
                return;
            }

            // --- what the authoritative sample sets, and only that ------------
            REPORT.put("stage", "configuration");
            client.setFingersMatchingSpeed(NMatchingSpeed.LOW);
            REPORT.put("settings_set_by_this_pass", new String[] {
                "Fingers.MatchingSpeed=Low (verify-finger sets it)",
            });
            REPORT.put("threshold_set_by_this_pass", false);

            // --- delivered runtime defaults ----------------------------------
            REPORT.put("stage", "reading-defaults");
            REPORT.put("delivered_extraction_defaults", readParameters(client, EXTRACTION_PARAMETERS));
            REPORT.put("delivered_matching_defaults", readParameters(client, MATCHING_PARAMETERS));

            long startupNanos = System.nanoTime() - startedAt;

            File a = new File(fixtures, "fixture_a.png");
            File b = new File(fixtures, "fixture_b.png");
            File blank = new File(fixtures, "fixture_blank.png");
            File invalid = new File(fixtures, "fixture_invalid.png");
            File unsupported = new File(fixtures, "fixture_unsupported.dat");

            // --- pair orientation: both orderings ----------------------------
            REPORT.put("stage", "pair-orientation");
            String forward = scoreDigest(client, a, b);
            String reverse = scoreDigest(client, b, a);
            if (forward == null || reverse == null) {
                throw new IllegalStateException(
                    "a fixture pair produced no score, so the route cannot be qualified");
            }
            Map<String, Object> orientation = new LinkedHashMap<>();
            orientation.put("orderings_scored", 2);
            orientation.put("score_digests_equal", forward.equals(reverse));
            orientation.put("both_orderings_produced_a_score", true);
            REPORT.put("pair_orientation", orientation);

            // --- SELF(A, A) as two independent extractions -------------------
            // Two NSubjects built from the same file. Nothing is reused between
            // them: each carries its own NFinger and each is extracted by the
            // engine on its own, which is what the SELF rule requires.
            REPORT.put("stage", "self-semantics");
            String selfDigest = scoreDigest(client, a, a);
            Map<String, Object> self = new LinkedHashMap<>();
            self.put("independent_extractions", 2);
            self.put("representation_reused", false);
            self.put("score_present", selfDigest != null);
            self.put("equals_cross_pair_digest", selfDigest != null && selfDigest.equals(forward));
            REPORT.put("self_semantics", self);

            // --- determinism, two of the three levels ------------------------
            // The third level is a fresh process, which this program cannot
            // perform on itself; the driver runs it twice and compares.
            REPORT.put("stage", "determinism");
            String sameObjects = scoreDigest(client, a, b);
            NBiometricClient fresh = new NBiometricClient();
            fresh.setFingersMatchingSpeed(NMatchingSpeed.LOW);
            String freshObjects = scoreDigest(fresh, a, b);
            fresh.dispose();
            Map<String, Object> determinism = new LinkedHashMap<>();
            determinism.put("same objects, same process", forward.equals(sameObjects));
            determinism.put("fresh objects, same process", forward.equals(freshObjects));
            REPORT.put("determinism_within_process", determinism);
            REPORT.put("pair_score_digest", forward);

            // --- failure semantics, four of the six in this process ----------
            REPORT.put("stage", "failure-semantics");
            List<Map<String, Object>> failures = new ArrayList<>();
            failures.add(failureCase(client, "invalid image", a, invalid));
            failures.add(failureCase(client, "unsupported image", a, unsupported));
            failures.add(failureCase(client, "extraction failure", a, blank));
            failures.add(failureCase(client, "matcher failure", blank, a));
            REPORT.put("failure_semantics", failures);

            // --- feasibility, to an order of magnitude -----------------------
            REPORT.put("stage", "feasibility");
            Map<String, Object> feasibility = new LinkedHashMap<>();
            feasibility.put("startup_millis", startupNanos / 1_000_000L);
            feasibility.put("verify_invocations", verifyCount);
            feasibility.put("end_to_end_verify_millis_total", verifyNanos / 1_000_000L);
            feasibility.put(
                "end_to_end_verify_millis_mean",
                verifyCount == 0 ? 0L : (verifyNanos / verifyCount) / 1_000_000L);
            feasibility.put(
                "end_to_end_verify_micros_mean",
                verifyCount == 0 ? 0L : (verifyNanos / verifyCount) / 1_000L);
            Runtime runtime = Runtime.getRuntime();
            feasibility.put("peak_heap_megabytes",
                (runtime.totalMemory() - runtime.freeMemory()) / (1024L * 1024L));
            feasibility.put("accelerator_required", false);
            feasibility.put(
                "what_was_measured",
                "one end-to-end verify call: both images loaded, both templates "
                    + "extracted and the pair matched, behind the single API call "
                    + "the 1:1 route uses");
            REPORT.put("feasibility", feasibility);

            REPORT.put("qualification_scores_produced", scoresProduced);
            REPORT.put("benchmark_scores_produced", 0);
            REPORT.put("sd300_used", false);
            REPORT.put("java_runtime_version", System.getProperty("java.version"));
            REPORT.put("java_vendor", System.getProperty("java.vendor"));
            REPORT.put("operating_system", System.getProperty("os.name"));
            REPORT.put("architecture", System.getProperty("os.arch"));
            REPORT.put("ok", true);
            REPORT.put("stage", "complete");
            emit(REPORT);
        } catch (Throwable error) {
            // The runtime may already have started. Saying so is what lets the
            // driver write a FAILED record rather than an absent one, and a
            // failed execution is a finding (spec correction 5).
            REPORT.put("ok", false);
            REPORT.put("error", error.getClass().getName() + ": " + error.getMessage());
            REPORT.put("qualification_scores_produced", scoresProduced);
            emit(REPORT);
            System.exit(4);
        } finally {
            if (client != null) {
                try {
                    client.dispose();
                } catch (Throwable ignored) {
                    // Disposal noise must not overwrite the report above.
                }
            }
        }
    }

    /** The native modules this process actually loaded, each with its version. */
    private static List<Map<String, Object>> loadedModules() {
        List<Map<String, Object>> modules = new ArrayList<>();
        try {
            for (NModule module : NModule.getLoadedModules()) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("name", safely(module::getName));
                row.put("product", safely(module::getProduct));
                row.put("company", safely(module::getCompany));
                row.put("version", safely(module::getVersion));
                row.put("file_name", safely(module::getFileName));
                modules.add(row);
            }
        } catch (Throwable unreadable) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("name", "UNREADABLE:" + unreadable.getClass().getSimpleName());
            modules.add(row);
        }
        return modules;
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

    /** Every documented parameter, read through the generic property interface. */
    private static Map<String, String> readParameters(NBiometricClient client, String[] names) {
        Map<String, String> values = new LinkedHashMap<>();
        for (String name : names) {
            try {
                Object value = client.getProperty(name, Object.class);
                values.put(name, value == null ? "null" : String.valueOf(value));
            } catch (Throwable unreadable) {
                // A parameter the delivered package does not expose is recorded
                // as unreadable, and the preflight counts that as unresolved
                // rather than as a value. A shorter profile that looked complete
                // would be the worst of the three outcomes.
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
            referenceSubject = subjectOf(reference);
            candidateSubject = subjectOf(candidate);

            // The whole route is behind this one call, so this is the whole
            // measurement: load, extract, extract, match.
            long started = System.nanoTime();
            NBiometricStatus status = client.verify(referenceSubject, candidateSubject);
            verifyNanos += System.nanoTime() - started;
            verifyCount += 1;

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

    /** One failure class, reported by the outcome its controlled cause produced. */
    private static Map<String, Object> failureCase(
            NBiometricClient client, String failureClass, File reference, File candidate) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("failure_class", failureClass);
        row.put("reference_fixture", reference.getName());
        row.put("candidate_fixture", candidate.getName());
        NSubject referenceSubject = null;
        NSubject candidateSubject = null;
        try {
            referenceSubject = subjectOf(reference);
            candidateSubject = subjectOf(candidate);
            NBiometricStatus status = client.verify(referenceSubject, candidateSubject);
            row.put("status", String.valueOf(status));
            boolean scored = false;
            if (status == NBiometricStatus.OK || status == NBiometricStatus.MATCH_NOT_FOUND) {
                try {
                    scored = !referenceSubject.getMatchingResults().isEmpty();
                } catch (Throwable noResults) {
                    scored = false;
                }
            }
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
