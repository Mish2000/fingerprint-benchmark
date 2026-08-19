// Stage 20B production bridge to the official University of Bologna MCC SDK v2.0.
//
// One process per comparison. It reads a payload describing two sides, builds
// one baseline MCC template per side through the official in-memory template
// API, matches them once, and prints a single tab-separated line.
//
// What this bridge deliberately does NOT contain:
//
//     no parameter setter          no threshold
//     no filtering                 no score transform
//     no top-N or sorting          no clamping of an out-of-range score
//     no deduplication             no decision of any kind
//     no rotation search           no state carried between invocations
//
// Every biometric decision belongs to the SDK; every benchmark decision belongs
// to fpbench. This file is the wire between them and nothing else. A score of
// 0.0 is a successful similarity, never a failure sentinel, and an exception is
// never turned into a score.
//
// No vendor byte lives in this repository. The bridge is compiled outside the
// working tree against `Sdk/MccSdk.dll` from the official archive.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using BioLab.Biometrics.Fingerprint.Mcc;
using BioLab.Biometrics.Mcc.Sdk;

namespace Fpbench.Stage20B.MccSdkV2Bridge
{
    /// <summary>The closed outcome vocabulary this bridge may print.</summary>
    internal static class Status
    {
        public const string Ok = "OK";
        public const string TemplateRefusalLeft = "MCC_TEMPLATE_REFUSAL_LEFT";
        public const string TemplateRefusalRight = "MCC_TEMPLATE_REFUSAL_RIGHT";
        public const string TemplateRefusalBoth = "MCC_TEMPLATE_REFUSAL_BOTH";
        public const string MatchRefusal = "MCC_MATCH_REFUSAL";
        public const string InvalidScore = "MCC_INVALID_SCORE";
        public const string RuntimeFailure = "MCC_RUNTIME_FAILURE";
        public const string BridgeFailure = "BRIDGE_FAILURE";
    }

    internal sealed class BridgePayloadException : Exception
    {
        public BridgePayloadException(string reason) : base(reason) { }
    }

    /// <summary>One side of a comparison, exactly as CreateMccTemplate takes it.</summary>
    internal sealed class Side
    {
        public int Width;
        public int Height;
        public int Resolution;
        public Minutia[] Minutiae;
    }

    internal static class Program
    {
        public const string Protocol = "FPBENCH-MCC-BRIDGE-1";
        public const string BridgeVersion = "1.0.0";

        private const string TemplateApi =
            "System.Object BioLab.Biometrics.Mcc.Sdk.MccSdk.CreateMccTemplate(" +
            "System.Int32,System.Int32,System.Int32,BioLab.Biometrics.Mcc.Sdk.Minutia[])";

        private const string MatchApi =
            "System.Double BioLab.Biometrics.Mcc.Sdk.MccSdk.MatchMccTemplates(" +
            "System.Object,System.Object)";

        public static int Main(string[] args)
        {
            Console.OutputEncoding = new UTF8Encoding(false);
            try
            {
                if (args.Length == 1 && args[0] == "identity")
                    return Identity();
                if (args.Length == 2 && args[0] == "match")
                    return Match(args[1]);

                Console.Error.WriteLine("usage: FpbenchMccBridge.exe identity");
                Console.Error.WriteLine("       FpbenchMccBridge.exe match <payload-path>");
                return 2;
            }
            catch (Exception exception)
            {
                // Nothing below Main is allowed to escape as a stack trace: a
                // 6,000-comparison run must be able to record what happened and
                // carry on. The type name is the whole detail — never a path,
                // never a minutia.
                WriteOutcome(Status.RuntimeFailure, null, null, null, null, 0, 0,
                             exception.GetType().FullName);
                return 1;
            }
        }

        // ------------------------------------------------------------- identity

        /// <summary>
        /// What this bridge is and what the SDK's untouched defaults are.
        ///
        /// Printed rather than assumed so that <c>validate_environment</c> can
        /// check the loaded assembly and every optimal parameter against the
        /// values Stage 20A recorded, before a single image is opened.
        /// </summary>
        private static int Identity()
        {
            Assembly assembly = typeof(MccSdk).Assembly;
            AssemblyName name = assembly.GetName();
            PortableExecutableKinds peKind;
            ImageFileMachine machine;
            assembly.ManifestModule.GetPEKind(out peKind, out machine);

            Emit("bridge_protocol", Protocol);
            Emit("bridge_version", BridgeVersion);
            Emit("assembly_full_name", assembly.FullName);
            Emit("assembly_name", name.Name);
            Emit("assembly_version", name.Version.ToString());
            Emit("image_runtime_version", assembly.ImageRuntimeVersion);
            Emit("portable_executable_kinds", peKind.ToString());
            Emit("image_file_machine", machine.ToString());
            Emit("clr_version", Environment.Version.ToString());
            Emit("process_64bit", Environment.Is64BitProcess ? "true" : "false");
            Emit("template_api", TemplateApi);
            Emit("match_api", MatchApi);
            Emit("variant", "baseline_mcc");
            Emit("parameter_setters_called", "false");
            Emit("score_native_type", "System.Double");
            Emit("score_transform", "NONE");
            Emit("threshold", "NONE");
            Emit("template_cache", "disabled");

            EmitParameters("default_enroll", MccEnrollParameters.MccOptimalEnrollParameters);
            EmitParameters("default_match", MccMatchParameters.MccOptimalMatchParameters);
            return 0;
        }

        private static void EmitParameters(string prefix, object instance)
        {
            foreach (PropertyInfo property in instance.GetType()
                .GetProperties(BindingFlags.Public | BindingFlags.Instance)
                .Where(item => item.CanRead && item.GetIndexParameters().Length == 0)
                .OrderBy(item => item.Name, StringComparer.Ordinal))
            {
                object value = property.GetValue(instance, null);
                if (value == null)
                {
                    Emit(prefix + "." + property.Name, "null");
                    continue;
                }
                if (value is string || value is bool || value is int || value is long ||
                    value is float || value is double || value.GetType().IsEnum)
                {
                    Emit(prefix + "." + property.Name, Scalar(value));
                }
            }
        }

        private static string Scalar(object value)
        {
            if (value is bool) return ((bool)value) ? "true" : "false";
            if (value is double) return ((double)value).ToString("R", CultureInfo.InvariantCulture);
            if (value is float) return ((float)value).ToString("R", CultureInfo.InvariantCulture);
            if (value is int) return ((int)value).ToString(CultureInfo.InvariantCulture);
            if (value is long) return ((long)value).ToString(CultureInfo.InvariantCulture);
            return value.ToString();
        }

        private static void Emit(string key, string value)
        {
            Console.WriteLine(key + "\t" + value);
        }

        // ---------------------------------------------------------------- match

        /// <summary>
        /// Two templates, one match, one line. In that order and no other.
        /// </summary>
        private static int Match(string payloadPath)
        {
            Side left;
            Side right;
            try
            {
                ReadPayload(payloadPath, out left, out right);
            }
            catch (BridgePayloadException payloadFailure)
            {
                WriteOutcome(Status.BridgeFailure, null, null, null, null, 0, 0,
                             payloadFailure.Message);
                return 0;
            }
            catch (IOException exception)
            {
                WriteOutcome(Status.BridgeFailure, null, null, null, null, 0, 0,
                             exception.GetType().FullName);
                return 0;
            }
            catch (UnauthorizedAccessException exception)
            {
                WriteOutcome(Status.BridgeFailure, null, null, null, null, 0, 0,
                             exception.GetType().FullName);
                return 0;
            }

            int leftCount = left.Minutiae.Length;
            int rightCount = right.Minutiae.Length;

            // Both sides are attempted before either is reported, so that a pair
            // neither side of which can become a template is recorded as _BOTH
            // rather than as whichever side happened to be tried first.
            object leftTemplate = null;
            object rightTemplate = null;
            string leftDetail = null;
            string rightDetail = null;

            Stopwatch clock = Stopwatch.StartNew();
            long leftStarted = clock.ElapsedTicks;
            try
            {
                leftTemplate = MccSdk.CreateMccTemplate(
                    left.Width, left.Height, left.Resolution, left.Minutiae);
            }
            catch (Exception exception)
            {
                leftDetail = exception.GetType().FullName;
            }
            long leftFinished = clock.ElapsedTicks;

            // A second, independent construction even when both sides carry the
            // same minutiae: SELF is an ordinary comparison here (Stage 20A,
            // section 10), never a cached template and never a shortcut.
            try
            {
                rightTemplate = MccSdk.CreateMccTemplate(
                    right.Width, right.Height, right.Resolution, right.Minutiae);
            }
            catch (Exception exception)
            {
                rightDetail = exception.GetType().FullName;
            }
            long rightFinished = clock.ElapsedTicks;

            double leftMicros = MicrosOf(leftFinished - leftStarted);
            double rightMicros = MicrosOf(rightFinished - leftFinished);

            if (leftTemplate == null || rightTemplate == null)
            {
                string status = leftTemplate == null && rightTemplate == null
                    ? Status.TemplateRefusalBoth
                    : (leftTemplate == null
                        ? Status.TemplateRefusalLeft
                        : Status.TemplateRefusalRight);
                string detail = leftDetail ?? rightDetail ?? "template_is_null";
                WriteOutcome(status, null, leftMicros, rightMicros, null,
                             leftCount, rightCount, detail);
                return 0;
            }

            double score;
            long matchStarted = clock.ElapsedTicks;
            try
            {
                score = MccSdk.MatchMccTemplates(leftTemplate, rightTemplate);
            }
            catch (Exception exception)
            {
                WriteOutcome(Status.MatchRefusal, null, leftMicros, rightMicros,
                             MicrosOf(clock.ElapsedTicks - matchStarted),
                             leftCount, rightCount, exception.GetType().FullName);
                return 0;
            }
            double matchMicros = MicrosOf(clock.ElapsedTicks - matchStarted);

            // The number is printed exactly as the SDK produced it, in every
            // case. An out-of-range or non-finite result is reported as such and
            // handed on unaltered — clamping it would invent a similarity the
            // matcher never returned.
            bool valid = !Double.IsNaN(score) && !Double.IsInfinity(score)
                         && score >= 0.0 && score <= 1.0;
            WriteOutcome(valid ? Status.Ok : Status.InvalidScore,
                         score, leftMicros, rightMicros, matchMicros,
                         leftCount, rightCount, null);
            return 0;
        }

        private static double MicrosOf(long ticks)
        {
            return ticks * 1000000.0 / Stopwatch.Frequency;
        }

        private static void WriteOutcome(
            string status, double? score,
            double? templateLeftMicros, double? templateRightMicros, double? matchMicros,
            int leftMinutiae, int rightMinutiae, string detail)
        {
            string[] fields = new string[]
            {
                status,
                score.HasValue ? score.Value.ToString("R", CultureInfo.InvariantCulture) : "",
                FormatMicros(templateLeftMicros),
                FormatMicros(templateRightMicros),
                FormatMicros(matchMicros),
                leftMinutiae.ToString(CultureInfo.InvariantCulture),
                rightMinutiae.ToString(CultureInfo.InvariantCulture),
                detail ?? ""
            };
            Console.WriteLine(String.Join("\t", fields));
        }

        private static string FormatMicros(double? value)
        {
            return value.HasValue
                ? value.Value.ToString("F3", CultureInfo.InvariantCulture)
                : "";
        }

        // -------------------------------------------------------------- payload

        /// <summary>
        /// Parse the two sides, strictly.
        ///
        /// The format is deliberately the SDK's own documented minutiae text
        /// format (Appendix A) twice over — width, height, resolution, count,
        /// then one <c>x y direction</c> row per minutia — so that what the
        /// bridge receives can be read against the vendor's own examples.
        /// Anything at all unexpected is a BRIDGE_FAILURE rather than a guess.
        /// </summary>
        private static void ReadPayload(string path, out Side left, out Side right)
        {
            string[] lines = File.ReadAllLines(path);
            int cursor = 0;
            if (lines.Length == 0 || lines[cursor].Trim() != Protocol)
                throw new BridgePayloadException("payload_protocol_mismatch");
            cursor++;

            left = ReadSide(lines, ref cursor, "LEFT");
            right = ReadSide(lines, ref cursor, "RIGHT");

            while (cursor < lines.Length)
            {
                if (lines[cursor].Trim().Length != 0)
                    throw new BridgePayloadException("payload_trailing_content");
                cursor++;
            }
        }

        private static Side ReadSide(string[] lines, ref int cursor, string label)
        {
            if (cursor >= lines.Length)
                throw new BridgePayloadException("payload_truncated_header");
            string[] header = Fields(lines[cursor]);
            cursor++;
            if (header.Length != 5 || header[0] != label)
                throw new BridgePayloadException("payload_bad_header");

            Side side = new Side();
            side.Width = ReadPositive(header[1], "width");
            side.Height = ReadPositive(header[2], "height");
            side.Resolution = ReadPositive(header[3], "resolution");
            int count = ReadCount(header[4]);

            Minutia[] minutiae = new Minutia[count];
            for (int index = 0; index < count; index++)
            {
                if (cursor >= lines.Length)
                    throw new BridgePayloadException("payload_truncated_minutiae");
                string[] row = Fields(lines[cursor]);
                cursor++;
                if (row.Length != 3)
                    throw new BridgePayloadException("payload_bad_minutia_row");

                Minutia minutia = new Minutia();
                minutia.X = ReadInteger(row[0], "x");
                minutia.Y = ReadInteger(row[1], "y");
                minutia.Direction = ReadDouble(row[2]);
                minutiae[index] = minutia;
            }
            side.Minutiae = minutiae;
            return side;
        }

        private static string[] Fields(string line)
        {
            return line.Trim().Split(new char[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
        }

        private static int ReadInteger(string text, string what)
        {
            int value;
            if (!Int32.TryParse(text, NumberStyles.AllowLeadingSign,
                                CultureInfo.InvariantCulture, out value))
                throw new BridgePayloadException("payload_bad_" + what);
            return value;
        }

        private static int ReadPositive(string text, string what)
        {
            int value = ReadInteger(text, what);
            if (value <= 0)
                throw new BridgePayloadException("payload_bad_" + what);
            return value;
        }

        private static int ReadCount(string text)
        {
            int value = ReadInteger(text, "count");
            if (value < 0)
                throw new BridgePayloadException("payload_bad_count");
            return value;
        }

        private static double ReadDouble(string text)
        {
            double value;
            if (!Double.TryParse(text, NumberStyles.Float,
                                 CultureInfo.InvariantCulture, out value))
                throw new BridgePayloadException("payload_bad_direction");
            if (Double.IsNaN(value) || Double.IsInfinity(value))
                throw new BridgePayloadException("payload_bad_direction");
            return value;
        }
    }
}
