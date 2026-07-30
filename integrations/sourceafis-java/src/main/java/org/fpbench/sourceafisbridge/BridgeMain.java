package org.fpbench.sourceafisbridge;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Entry point. Two commands, one JSON document out, nothing else.
 *
 * <pre>
 *   java -jar fpbench-sourceafis-bridge.jar version
 *   java -jar fpbench-sourceafis-bridge.jar compare   &lt; request.json
 * </pre>
 *
 * <p>Exit codes carry meaning, because the Python side classifies on them:
 *
 * <ul>
 *   <li><b>0</b> — a document was produced. That includes an expected comparison
 *       failure: unreadable image, undecodable image, no template. Those are results,
 *       not crashes (docs/adr/0013).
 *   <li><b>64</b> — the request itself was unusable. A caller bug.
 *   <li><b>70</b> — something in this program went wrong. Our bug.
 * </ul>
 *
 * <p>stdout carries exactly one JSON document and never anything else; diagnostics go
 * to stderr. A stray print on stdout would make the response unparseable, which the
 * Python side treats as a contract violation.
 */
public final class BridgeMain {

    static final int EXIT_OK = 0;
    static final int EXIT_INVALID_REQUEST = 64;
    static final int EXIT_INTERNAL_ERROR = 70;

    private static final ObjectMapper MAPPER = new ObjectMapper()
            // Unknown fields are a protocol mismatch, not something to shrug at.
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);

    private BridgeMain() {
    }

    public static void main(String[] args) {
        PrintStream out = new PrintStream(System.out, true, StandardCharsets.UTF_8);
        PrintStream err = new PrintStream(System.err, true, StandardCharsets.UTF_8);
        System.exit(run(args, out, err));
    }

    static int run(String[] args, PrintStream out, PrintStream err) {
        if (args.length != 1) {
            err.println("usage: version | compare");
            return EXIT_INVALID_REQUEST;
        }

        try {
            switch (args[0]) {
                case "version":
                    out.println(MAPPER.writeValueAsString(versionDocument()));
                    return EXIT_OK;
                case "compare":
                    return compare(out, err);
                default:
                    err.println("unknown command: " + args[0]);
                    return EXIT_INVALID_REQUEST;
            }
        } catch (CompareRequest.InvalidRequestException exception) {
            err.println("invalid request: " + exception.getMessage());
            return EXIT_INVALID_REQUEST;
        } catch (JsonProcessingException exception) {
            err.println("invalid request JSON: " + exception.getOriginalMessage());
            return EXIT_INVALID_REQUEST;
        } catch (Throwable throwable) {
            // Broad on purpose. A bug here must be reported as a bug — non-zero, with
            // nothing on stdout — rather than dressed up as a biometric failure.
            err.println("internal bridge error: " + throwable);
            return EXIT_INTERNAL_ERROR;
        }
    }

    private static int compare(PrintStream out, PrintStream err)
            throws IOException, CompareRequest.InvalidRequestException {
        byte[] stdin = System.in.readAllBytes();
        if (stdin.length == 0) {
            err.println("invalid request: empty stdin");
            return EXIT_INVALID_REQUEST;
        }

        CompareRequest request =
                MAPPER.readValue(new String(stdin, StandardCharsets.UTF_8), CompareRequest.class);
        request.validate();

        CompareResponse response = new SourceAfisComparisonService().compare(request);
        out.println(MAPPER.writeValueAsString(response));
        return EXIT_OK;
    }

    static Map<String, String> versionDocument() {
        Map<String, String> document = new LinkedHashMap<>();
        document.put("schema_version", BridgeVersion.SCHEMA_VERSION);
        document.put("bridge_version", BridgeVersion.BRIDGE_VERSION);
        document.put("bridge_protocol", BridgeVersion.BRIDGE_PROTOCOL);
        document.put("sourceafis_version", BridgeVersion.sourceafisVersion());
        document.put("java_version", System.getProperty("java.version"));
        document.put("java_vendor", System.getProperty("java.vendor"));
        document.put("java_vm_name", System.getProperty("java.vm.name"));
        document.put("os_name", System.getProperty("os.name"));
        document.put("os_arch", System.getProperty("os.arch"));
        return document;
    }
}
