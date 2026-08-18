// Stage 20A qualification probe for the official University of Bologna MCC SDK v2.0.
//
// This is deliberately not a production fpbench adapter. It loads only the
// vendor-supplied minutiae examples, invokes the documented baseline MCC API
// without setting any parameters, and emits one JSON qualification record.

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Web.Script.Serialization;
using BioLab.Biometrics.Fingerprint.Mcc;
using BioLab.Biometrics.Mcc.Sdk;

namespace Fpbench.Stage20A.MccSdkV2Probe
{
    internal static class Program
    {
        private const string MatchApi =
            "System.Double BioLab.Biometrics.Mcc.Sdk.MccSdk.MatchMccTemplates(System.Object,System.Object)";

        private const string ProductionTemplateApi =
            "System.Object BioLab.Biometrics.Mcc.Sdk.MccSdk.CreateMccTemplate(" +
            "System.Int32,System.Int32,System.Int32,BioLab.Biometrics.Mcc.Sdk.Minutia[])";

        private const string SmokeTemplateApi =
            "System.Object BioLab.Biometrics.Mcc.Sdk.MccSdk." +
            "CreateMccTemplateFromTextTemplate(System.String)";

        public static int Main(string[] args)
        {
            if (args.Length != 1)
            {
                Console.Error.WriteLine("usage: MccSdkV2Probe.exe <official-package-root>");
                return 2;
            }

            try
            {
                string packageRoot = Path.GetFullPath(args[0]);
                string sampleRoot = Path.Combine(packageRoot, "SampleMinutiae");
                string first = RequiredFile(sampleRoot, "1_1.txt");
                string related = RequiredFile(sampleRoot, "1_2.txt");
                string unrelated = RequiredFile(sampleRoot, "2_1.txt");

                Dictionary<string, object> record = new Dictionary<string, object>();
                record["schema"] = "stage_20a_mcc_sdk_v2_probe_v1";
                record["assembly"] = AssemblyRecord(typeof(MccSdk).Assembly);
                record["runtime"] = RuntimeRecord();
                record["public_api"] = PublicApiRecord(typeof(MccSdk).Assembly);
                record["native_defaults"] = NativeDefaultsRecord();
                record["smoke"] = SmokeRecord(first, related, unrelated);
                record["failure_behavior"] = FailureBehaviorRecord(first);
                record["sd300_used"] = false;
                record["parameter_setters_called"] = false;
                record["production_adapter"] = false;

                JavaScriptSerializer serializer = new JavaScriptSerializer();
                serializer.MaxJsonLength = Int32.MaxValue;
                Console.WriteLine(serializer.Serialize(record));
                return 0;
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine(exception.GetType().FullName + ": " + exception.Message);
                return 1;
            }
        }

        private static string RequiredFile(string directory, string name)
        {
            string path = Path.Combine(directory, name);
            if (!File.Exists(path))
                throw new FileNotFoundException("official sample is absent", name);
            return path;
        }

        private static Dictionary<string, object> AssemblyRecord(Assembly assembly)
        {
            AssemblyName name = assembly.GetName();
            PortableExecutableKinds peKind;
            ImageFileMachine machine;
            assembly.ManifestModule.GetPEKind(out peKind, out machine);

            Dictionary<string, object> record = new Dictionary<string, object>();
            record["full_name"] = assembly.FullName;
            record["name"] = name.Name;
            record["version"] = name.Version.ToString();
            record["image_runtime_version"] = assembly.ImageRuntimeVersion;
            record["portable_executable_kinds"] = peKind.ToString();
            record["image_file_machine"] = machine.ToString();
            record["referenced_assemblies"] = assembly.GetReferencedAssemblies()
                .OrderBy(item => item.Name, StringComparer.Ordinal)
                .Select(item => (object)new Dictionary<string, object>
                {
                    { "name", item.Name },
                    { "version", item.Version.ToString() }
                }).ToArray();
            return record;
        }

        private static Dictionary<string, object> RuntimeRecord()
        {
            Dictionary<string, object> record = new Dictionary<string, object>();
            record["clr_version"] = Environment.Version.ToString();
            record["os_version"] = Environment.OSVersion.VersionString;
            record["process_64bit"] = Environment.Is64BitProcess;
            record["machine_64bit"] = Environment.Is64BitOperatingSystem;
            return record;
        }

        private static object[] PublicApiRecord(Assembly assembly)
        {
            return assembly.GetExportedTypes()
                .OrderBy(type => type.FullName, StringComparer.Ordinal)
                .Select(type => (object)TypeRecord(type))
                .ToArray();
        }

        private static Dictionary<string, object> TypeRecord(Type type)
        {
            BindingFlags declared = BindingFlags.Public | BindingFlags.DeclaredOnly |
                                    BindingFlags.Instance | BindingFlags.Static;
            Dictionary<string, object> record = new Dictionary<string, object>();
            record["full_name"] = type.FullName;
            record["kind"] = type.IsEnum ? "enum" :
                (type.IsValueType ? "struct" : (type.IsClass ? "class" : "other"));
            record["enum_values"] = type.IsEnum ? Enum.GetNames(type) : new string[0];
            record["constructors"] = type.GetConstructors(BindingFlags.Public | BindingFlags.Instance)
                .Select(ConstructorSignature).OrderBy(value => value, StringComparer.Ordinal).ToArray();
            record["properties"] = type.GetProperties(declared)
                .Select(PropertySignature).OrderBy(value => value, StringComparer.Ordinal).ToArray();
            record["methods"] = type.GetMethods(declared)
                .Where(method => !method.IsSpecialName)
                .Select(MethodSignature).OrderBy(value => value, StringComparer.Ordinal).ToArray();
            return record;
        }

        private static string ConstructorSignature(ConstructorInfo constructor)
        {
            return constructor.DeclaringType.FullName + "(" +
                   String.Join(",", constructor.GetParameters().Select(ParameterSignature)) + ")";
        }

        private static string PropertySignature(PropertyInfo property)
        {
            string scope = (property.GetGetMethod() ?? property.GetSetMethod()).IsStatic ? "static " : "";
            return scope + TypeName(property.PropertyType) + " " + property.Name +
                   " { " + (property.CanRead ? "get; " : "") +
                   (property.CanWrite ? "set; " : "") + "}";
        }

        private static string MethodSignature(MethodInfo method)
        {
            return (method.IsStatic ? "static " : "") + TypeName(method.ReturnType) + " " +
                   method.DeclaringType.FullName + "." + method.Name + "(" +
                   String.Join(",", method.GetParameters().Select(ParameterSignature)) + ")";
        }

        private static string ParameterSignature(ParameterInfo parameter)
        {
            Type type = parameter.ParameterType;
            string modifier = parameter.IsOut ? "out " : (type.IsByRef ? "ref " : "");
            if (type.IsByRef)
                type = type.GetElementType();
            return modifier + TypeName(type) + " " + parameter.Name;
        }

        private static string TypeName(Type type)
        {
            if (type.IsArray)
            {
                string commas = new string(',', type.GetArrayRank() - 1);
                return TypeName(type.GetElementType()) + "[" + commas + "]";
            }
            return type.FullName ?? type.Name;
        }

        private static Dictionary<string, object> NativeDefaultsRecord()
        {
            Dictionary<string, object> record = new Dictionary<string, object>();
            record["authority"] = "public SDK optimal-parameter properties";
            record["selection"] = "SDK_OPTIMAL_DEFAULTS";
            record["baseline_variant"] = "MCC";
            record["enroll"] = ReadProperties(MccEnrollParameters.MccOptimalEnrollParameters);
            record["match"] = ReadProperties(MccMatchParameters.MccOptimalMatchParameters);
            return record;
        }

        private static Dictionary<string, object> ReadProperties(object instance)
        {
            Dictionary<string, object> values = new Dictionary<string, object>();
            foreach (PropertyInfo property in instance.GetType()
                .GetProperties(BindingFlags.Public | BindingFlags.Instance)
                .Where(property => property.CanRead && property.GetIndexParameters().Length == 0)
                .OrderBy(property => property.Name, StringComparer.Ordinal))
            {
                object value = property.GetValue(instance, null);
                if (value == null || value is string || value is bool || value is int ||
                    value is long || value is float || value is double || value.GetType().IsEnum)
                {
                    values[property.Name] = value == null ? null :
                        (value.GetType().IsEnum ? value.ToString() : value);
                }
            }
            return values;
        }

        private static Dictionary<string, object> SmokeRecord(
            string first, string related, string unrelated)
        {
            // Each score gets fresh template constructions on both sides. SELF is
            // therefore a normal two-template invocation, never a path shortcut.
            double self = Score(Fresh(first), Fresh(first));
            double relatedForward = Score(Fresh(first), Fresh(related));
            double relatedReverse = Score(Fresh(related), Fresh(first));
            double unrelatedForward = Score(Fresh(first), Fresh(unrelated));
            double unrelatedReverse = Score(Fresh(unrelated), Fresh(first));

            double[] scores = new double[]
            {
                self, relatedForward, relatedReverse, unrelatedForward, unrelatedReverse
            };

            Dictionary<string, object> record = new Dictionary<string, object>();
            record["sample_authority"] = "SDK_PROVIDED_SAMPLE_MINUTIAE";
            record["sample_files"] = new string[] { "1_1.txt", "1_2.txt", "2_1.txt" };
            record["sample_template_api"] = SmokeTemplateApi;
            record["production_route_template_api"] = ProductionTemplateApi;
            record["match_api"] = MatchApi;
            record["self_templates_constructed_independently"] = true;
            record["self"] = self;
            record["related_forward"] = relatedForward;
            record["related_reverse"] = relatedReverse;
            record["unrelated_forward"] = unrelatedForward;
            record["unrelated_reverse"] = unrelatedReverse;
            record["related_exactly_symmetric"] = relatedForward.Equals(relatedReverse);
            record["unrelated_exactly_symmetric"] = unrelatedForward.Equals(unrelatedReverse);
            record["all_finite"] = scores.All(IsFinite);
            record["all_in_documented_range"] = scores.All(value => value >= 0.0 && value <= 1.0);
            record["zero_score_observed_as_success"] = scores.Any(value => value == 0.0);
            return record;
        }

        private static object Fresh(string sample)
        {
            return MccSdk.CreateMccTemplateFromTextTemplate(sample);
        }

        private static double Score(object left, object right)
        {
            return MccSdk.MatchMccTemplates(left, right);
        }

        private static bool IsFinite(double value)
        {
            return !Double.IsNaN(value) && !Double.IsInfinity(value);
        }

        private static Dictionary<string, object> FailureBehaviorRecord(string validSample)
        {
            string invalid = Path.Combine(
                Path.GetTempPath(), "fpbench-stage20a-" + Guid.NewGuid().ToString("N") + ".txt");
            Dictionary<string, object> record = new Dictionary<string, object>();
            try
            {
                File.WriteAllText(invalid, "not-a-minutiae-template\n");
                record["invalid_text_template"] = ObserveCreate(invalid);
                record["null_left_template"] = ObserveMatch(null, Fresh(validSample));
            }
            finally
            {
                if (File.Exists(invalid))
                    File.Delete(invalid);
            }
            record["zero_is_never_used_as_an_exception_sentinel"] = true;
            return record;
        }

        private static Dictionary<string, object> ObserveCreate(string path)
        {
            try
            {
                object template = MccSdk.CreateMccTemplateFromTextTemplate(path);
                return Observation("RETURNED", template == null ? "null" : template.GetType().FullName);
            }
            catch (Exception exception)
            {
                return Observation("THREW", exception.GetType().FullName);
            }
        }

        private static Dictionary<string, object> ObserveMatch(object left, object right)
        {
            try
            {
                double score = MccSdk.MatchMccTemplates(left, right);
                return Observation("RETURNED", score.ToString("R", CultureInfo.InvariantCulture));
            }
            catch (Exception exception)
            {
                return Observation("THREW", exception.GetType().FullName);
            }
        }

        private static Dictionary<string, object> Observation(string outcome, string detail)
        {
            return new Dictionary<string, object>
            {
                { "outcome", outcome },
                { "detail", detail }
            };
        }
    }
}
