package org.fpbench.sourceafisbridge;

import com.machinezoo.sourceafis.FingerprintCompatibility;

/**
 * Identity of this bridge and of the SourceAFIS build behind it.
 *
 * <p>The SourceAFIS version is <em>asked of SourceAFIS at runtime</em> rather than
 * recorded as a constant here. A constant would keep saying 3.18.1 after someone
 * swapped the jar, and the whole point of the version command is to catch exactly
 * that: the Python side refuses to run when the library on the classpath is not the
 * one the experiment was defined against.
 */
public final class BridgeVersion {

    /** Wire format of the request and response documents. */
    public static final String SCHEMA_VERSION = "1";

    /** Version of this bridge program. Bump when its behaviour changes. */
    public static final String BRIDGE_VERSION = "1";

    /** Protocol name, so a mismatch is obvious rather than subtle. */
    public static final String BRIDGE_PROTOCOL = "fpbench.sourceafis.bridge.v1";

    private BridgeVersion() {
    }

    /** The version of the SourceAFIS implementation actually on the classpath. */
    public static String sourceafisVersion() {
        return FingerprintCompatibility.version();
    }
}
