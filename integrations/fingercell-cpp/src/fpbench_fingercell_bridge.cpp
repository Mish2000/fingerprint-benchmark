// fpbench Stage 13A — FingerCell 3.3 qualification bridge.
//
// The smallest program that can answer Stage 13A's runtime questions, and
// nothing more. It is not an adapter: it produces no ResultSet, applies no
// threshold, makes no decision, caches no template and knows nothing about the
// benchmark's protocol beyond which side of a pair is the reference.
//
// WHAT IT DOES NOT DO WHEN IT IS BUILT
//
// Nothing. Every path below runs only under an explicit subcommand. The build
// compiles and links this file and stops: it does not load a vendor module, does
// not obtain a licence, and does not start the trial clock. That separation is
// deliberate — the trial runs 30 days from an explicit activation, and a route
// that fails to compile should cost nothing (docs/adr/0115).
//
// WHAT IT DOES WHEN IT IS RUN
//
//   settings   construct the engine and report every property it exposes,
//              reading them before anything is set (docs/adr/0118)
//   extract    one image -> one fresh template, at an effective 500 PPI
//   match      two templates -> one native integer
//   pair       two images -> both orientations, each side extracted freshly
//   self       one image -> two independent extractions -> one comparison
//
// Output is `key=value` lines on stdout, one per line, for the Python driver to
// parse. Errors go to stderr with a non-zero exit status. A failure is never
// reported as a score.

#include <algorithm>
#include <cstddef>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#if defined(__linux__)
#include <sys/utsname.h>
#endif

#include <NCore.hpp>
#include <NMedia.hpp>
#include <NLicensing.hpp>
#include <FingerCell.hpp>

using namespace Neurotec;
using namespace Neurotec::IO;
using namespace Neurotec::Images;
using namespace Neurotec::Licensing;

// Deliberately not `using namespace Neurotec::FingerCell`. The namespace and the
// class inside it share a name, so importing the namespace makes every bare
// mention of `FingerCell` ambiguous. The delivered tutorials fully qualify the
// type for the same reason; this alias does it once.
using FingerCellEngine = ::Neurotec::FingerCell::FingerCell;
using FingerCellFormat = ::Neurotec::FingerCell::FingerCellTemplateFormat;

namespace {

// The component this bridge is licensed for. Named explicitly, because the
// benchmark already runs a different product from the same vendor on this host
// and a licensing service being up says nothing about this entitlement
// (docs/adr/0114).
const NChar *const kLicenseComponent = N_T("FingerCell");
const NChar *const kLicenseServer = N_T("/local");
const NChar *const kLicensePort = N_T("5000");

// The benchmark's input profile. Not negotiable and not derived from anything
// the image file happens to claim.
const double kRequiredPpi = 500.0;

// Narrow an NString to something std::ostream can print.
//
// The same call the delivered sample support header uses for its stream
// operators, rather than a conversion invented here.
std::string ToUtf8(const NString &value)
{
	HNString handle = value.GetHandle();
	if (handle == NULL) return std::string();
	const NAChar *buffer = NULL;
	NInt length = 0;
	NCheck(NStringGetBufferA(handle, &length, &buffer));
	if (buffer == NULL) return std::string();
	return std::string(buffer, static_cast<std::size_t>(length));
}

void Emit(const std::string &key, const std::string &value)
{
	std::cout << key << "=" << value << "\n";
}

void Emit(const std::string &key, long long value)
{
	std::cout << key << "=" << value << "\n";
}

// Obtain a licence for the FingerCell component itself.
//
// Trial mode is passed in rather than read from the delivered flag file, so that
// starting the trial clock is always something the caller asked for by name.
// The delivered licensing subsystem's own name for what it is reporting.
std::string ObtainedStatusName(NLicenseObtainedStatus status)
{
	switch (status)
	{
	case nlosLicenseObtained: return "LICENSE_OBTAINED";
	case nlosLicenseNotObtained: return "LICENSE_NOT_OBTAINED";
	case nlosServerOffline: return "SERVER_OFFLINE";
	case nlosUnknown:
	default: return "UNKNOWN";
	}
}

bool ObtainLicense()
{
	// Read back rather than echoed: this is the runtime's own answer about the
	// client half of the trial switch, not the value we just passed in. The
	// switch itself is set before any licensing initialisation, in main, because
	// the runtime refuses it afterwards — see the note there.
	Emit("trial_mode", NLicenseManager::GetTrialMode() ? "true" : "false");

	// Ask the subsystem what it thinks the situation is before asking it to act.
	// A supported query, and the difference between "the service is unreachable"
	// and "the service is there and has nothing for this component" is the whole
	// question this stage is stuck on.
	try
	{
		const NLicenseObtainedStatus before =
			NLicense::GetObtainedStatus(kLicenseServer, kLicensePort, kLicenseComponent);
		Emit("obtained_status_before", ObtainedStatusName(before));
	}
	catch (NError &error)
	{
		Emit("obtained_status_before", "QUERY_FAILED");
		Emit("obtained_status_error_code", static_cast<long long>(error.GetCode()));
	}

	const bool obtained =
		NLicense::Obtain(kLicenseServer, kLicensePort, kLicenseComponent);

	try
	{
		const NLicenseObtainedStatus after =
			NLicense::GetObtainedStatus(kLicenseServer, kLicensePort, kLicenseComponent);
		Emit("obtained_status_after", ObtainedStatusName(after));
	}
	catch (NError &)
	{
		Emit("obtained_status_after", "QUERY_FAILED");
	}

	try
	{
		Emit(
			"component_activated",
			NLicense::IsComponentActivated(kLicenseComponent) ? "true" : "false");
	}
	catch (NError &)
	{
		Emit("component_activated", "QUERY_FAILED");
	}

	if (!obtained)
	{
		std::cerr << "could not obtain a licence for the "
		          << ToUtf8(NString(kLicenseComponent)) << " component" << std::endl;
		return false;
	}
	Emit("license_component", ToUtf8(NString(kLicenseComponent)));
	Emit("license_obtained", "true");
	return true;
}

void ReleaseLicense()
{
	try
	{
		NLicense::Release(kLicenseComponent);
	}
	catch (...)
	{
		// Releasing is best effort. A failure here is not a finding about the
		// route and must not turn a completed run into a failed one.
	}
}

// Load an image and make 500 PPI true at the point of extraction.
//
// The resolution is reported both as the file declared it and as the extractor
// will see it, so the evidence can say whether the loader preserved it or the
// bridge had to state it. Pixels are never touched: this sets metadata about the
// image, and a rescale would be fpbench choosing a preprocessing step.
NImage LoadAtBenchmarkResolution(const NChar *path)
{
	NImage image = NImage::FromFile(path);
	Emit("image_width", image.GetWidth());
	Emit("image_height", image.GetHeight());
	Emit("declared_horz_resolution", static_cast<long long>(image.GetHorzResolution()));
	Emit("declared_vert_resolution", static_cast<long long>(image.GetVertResolution()));
	Emit("resolution_is_aspect_ratio", image.GetResolutionIsAspectRatio() ? "true" : "false");

	image.SetResolutionIsAspectRatio(false);
	image.SetHorzResolution(static_cast<NFloat>(kRequiredPpi));
	image.SetVertResolution(static_cast<NFloat>(kRequiredPpi));

	Emit("effective_horz_resolution", static_cast<long long>(image.GetHorzResolution()));
	Emit("effective_vert_resolution", static_cast<long long>(image.GetVertResolution()));
	return image;
}

// Report the environment this process is running in.
//
// Enough to identify the substrate and nothing that identifies the machine or
// the person: no hostname, no machine ID, no user, no paths outside the store.
// The execution substrate is part of this implementation's identity and is
// published rather than folded into the platform string (docs/adr/0122).
void EmitEnvironmentIdentity()
{
#if defined(__linux__)
	Emit("os_family", "linux");
	struct utsname info;
	if (uname(&info) == 0)
	{
		Emit("kernel_release", std::string(info.release));
		Emit("machine", std::string(info.machine));
		// WSL identifies itself in the kernel release string. Recorded because
		// the vendor documents Linux x86-64 as a target and does not name WSL,
		// so the claim stays exactly as strong as the evidence: their Linux
		// build, run under this substrate.
		const std::string release(info.release);
		const bool wsl = release.find("microsoft") != std::string::npos ||
		                 release.find("Microsoft") != std::string::npos ||
		                 release.find("WSL") != std::string::npos;
		Emit("wsl_indicated", wsl ? "true" : "false");
	}
#elif defined(_WIN32)
	Emit("os_family", "windows");
	Emit("wsl_indicated", "false");
#else
	Emit("os_family", "unknown");
#endif
	Emit("pointer_bits", static_cast<long long>(sizeof(void *) * 8));
}

// Record which shared objects this process actually mapped.
//
// The operating system's own report about our own process, read after the
// engine has been constructed. This is not an inspection of a vendor artifact:
// it is documentation of the environment a score would be produced in, and it is
// the only thing that can show a component loaded during construction that no
// link closure would ever mention (docs/adr/0121).
void EmitLoadedModules()
{
#if defined(__linux__)
	std::ifstream maps("/proc/self/maps");
	if (!maps)
	{
		Emit("loaded_modules_available", "false");
		return;
	}
	Emit("loaded_modules_available", "true");
	std::vector<std::string> seen;
	std::string line;
	while (std::getline(maps, line))
	{
		const std::size_t start = line.find('/');
		if (start == std::string::npos) continue;
		const std::string path = line.substr(start);
		if (path.find(".so") == std::string::npos) continue;
		if (std::find(seen.begin(), seen.end(), path) != seen.end()) continue;
		seen.push_back(path);
	}
	std::sort(seen.begin(), seen.end());
	Emit("loaded_module_count", static_cast<long long>(seen.size()));
	for (std::size_t index = 0; index < seen.size(); index++)
	{
		// Only the file name. A full path on this host names a person.
		const std::string &full = seen[index];
		const std::size_t slash = full.find_last_of('/');
		const std::string name = slash == std::string::npos ? full : full.substr(slash + 1);
		Emit("loaded_module." + std::to_string(index), name);
	}
#else
	Emit("loaded_modules_available", "false");
#endif
}

// The diagnostic first run.
//
// Environment, licence, construction, properties, loaded modules, clean exit —
// and deliberately no Extract and no Match. If the licensing or the settings
// profile surprise us, this costs seconds instead of a whole qualification.
int CommandDiagnose(bool trialMode)
{
	EmitEnvironmentIdentity();

	if (!ObtainLicense()) return 2;

	FingerCellEngine fingerCell;
	Emit("engine_constructed", "true");

	NPropertyBag properties;
	fingerCell.CaptureProperties(properties);
	Emit("property_count", properties.GetCount());
	for (NInt index = 0; index < properties.GetCount(); index++)
	{
		NNameValuePair pair = properties.Get(index);
		Emit("property." + ToUtf8(pair.GetName()), ToUtf8(pair.GetValue().ToString()));
	}

	Emit("typed.ImageQualityThreshold", fingerCell.GetImageQualityThreshold());
	Emit("typed.MatchingAlgorithm", fingerCell.GetMatchingAlgorithm());
	Emit("typed.TemplateFormat", static_cast<long long>(fingerCell.GetTemplateFormat()));

	// After construction, so that anything the engine pulled in on the way up is
	// already mapped.
	EmitLoadedModules();

	Emit("extract_performed", "false");
	Emit("match_performed", "false");

	ReleaseLicense();
	Emit("clean_shutdown", "true");
	return 0;
}

// Report every property the engine exposes, before anything has been set.
//
// This uses the SDK's own property capture rather than a list written in
// advance: the typed accessors cover three settings and the documented surface
// is wider, so a closure built from the header alone would be incomplete. What
// it reports is what upstream makes externally selectable — not implementation
// internals (docs/adr/0118, docs/adr/0120).
int CommandSettings(bool trialMode)
{
	if (!ObtainLicense()) return 2;

	FingerCellEngine fingerCell;
	Emit("engine_constructed", "true");

	NPropertyBag properties;
	fingerCell.CaptureProperties(properties);
	Emit("property_count", properties.GetCount());

	for (NInt index = 0; index < properties.GetCount(); index++)
	{
		NNameValuePair pair = properties.Get(index);
		Emit("property." + ToUtf8(pair.GetName()), ToUtf8(pair.GetValue().ToString()));
	}

	// The three the delivered binding types directly, reported again by their
	// typed accessors so the two views can be compared.
	Emit("typed.ImageQualityThreshold", fingerCell.GetImageQualityThreshold());
	Emit("typed.MatchingAlgorithm", fingerCell.GetMatchingAlgorithm());
	Emit("typed.TemplateFormat", static_cast<long long>(fingerCell.GetTemplateFormat()));
	Emit("typed.MergeTemplatesMaxRecords", fingerCell.MergeTemplatesGetMaxNumberOfRecords());

	ReleaseLicense();
	return 0;
}

int CommandExtract(bool trialMode, const NChar *imagePath, const NChar *outPath)
{
	if (!ObtainLicense()) return 2;

	FingerCellEngine fingerCell;
	NImage image = LoadAtBenchmarkResolution(imagePath);
	NBuffer record = fingerCell.Extract(image);
	Emit("template_size_bytes", static_cast<long long>(record.GetSize()));
	Emit("template_format", static_cast<long long>(fingerCell.GetTemplateFormat()));
	NFile::WriteAllBytes(outPath, record);
	Emit("template_written", "true");

	ReleaseLicense();
	return 0;
}

int CommandMatch(bool trialMode, const NChar *referencePath, const NChar *candidatePath)
{
	if (!ObtainLicense()) return 2;

	FingerCellEngine fingerCell;
	NBuffer reference = NFile::ReadAllBytes(referencePath);
	NBuffer candidate = NFile::ReadAllBytes(candidatePath);
	NInt score = fingerCell.Match(reference, candidate);
	Emit("score", static_cast<long long>(score));

	ReleaseLicense();
	return 0;
}

// Both orientations, each side extracted freshly.
//
// The frozen binding is pair.left -> reference, pair.right -> candidate, taken
// from the words the delivered header itself uses (docs/adr/0119). The reversed
// score is produced for observation only: nothing here averages, maximises or
// selects between the two.
int CommandPair(bool trialMode, const NChar *leftPath, const NChar *rightPath)
{
	if (!ObtainLicense()) return 2;

	FingerCellEngine fingerCell;

	NImage leftImage = LoadAtBenchmarkResolution(leftPath);
	NBuffer leftTemplate = fingerCell.Extract(leftImage);
	NImage rightImage = LoadAtBenchmarkResolution(rightPath);
	NBuffer rightTemplate = fingerCell.Extract(rightImage);

	Emit("reference_template_size_bytes", static_cast<long long>(leftTemplate.GetSize()));
	Emit("candidate_template_size_bytes", static_cast<long long>(rightTemplate.GetSize()));

	NInt forward = fingerCell.Match(leftTemplate, rightTemplate);
	Emit("score_forward", static_cast<long long>(forward));

	NInt reversed = fingerCell.Match(rightTemplate, leftTemplate);
	Emit("score_reversed", static_cast<long long>(reversed));

	ReleaseLicense();
	return 0;
}

// SELF, from two genuinely independent extractions of the same image.
//
// Two loads, two extractions, two templates. An engine that noticed both sides
// were the same object could return a constant, and that constant would be a
// fact about this bridge's plumbing rather than about the algorithm.
int CommandSelf(bool trialMode, const NChar *imagePath)
{
	if (!ObtainLicense()) return 2;

	FingerCellEngine fingerCell;

	NImage first = LoadAtBenchmarkResolution(imagePath);
	NBuffer firstTemplate = fingerCell.Extract(first);

	NImage second = LoadAtBenchmarkResolution(imagePath);
	NBuffer secondTemplate = fingerCell.Extract(second);

	Emit("independent_extractions", 2);
	Emit("templates_shared", "false");

	NInt score = fingerCell.Match(firstTemplate, secondTemplate);
	Emit("score_self", static_cast<long long>(score));

	ReleaseLicense();
	return 0;
}

int Usage()
{
	std::cerr << "fpbench FingerCell bridge (Stage 13A qualification)\n"
	          << "  settings <trial>\n"
	          << "  extract  <trial> <image> <template-out>\n"
	          << "  match    <trial> <reference-template> <candidate-template>\n"
	          << "  pair     <trial> <left-image> <right-image>\n"
	          << "  self     <trial> <image>\n"
	          << "\n<trial> is 0 or 1 and decides whether trial mode is requested.\n"
	          << "No subcommand does anything until it is named: building this file\n"
	          << "loads no module and obtains no licence.\n";
	return 1;
}

bool TrialFlag(const NChar *value)
{
	return NString(value) == NString(N_T("1"));
}

} // namespace

int main(int argc, NChar **argv)
{
	if (argc < 3) return Usage();

	const NString command(argv[1]);
	const bool trialMode = TrialFlag(argv[2]);

	// The trial switch comes first, and the order is upstream's requirement
	// rather than a preference. Setting it later fails outright:
	//
	//     (-7) TrialMode cannot be changed after NLicenseManager initialization
	//
	// Licensing initialisation happens during core start-up, so anything that
	// sets trial mode after `NCore::OnStart()` is asking for a mode the runtime
	// has already committed. Every delivered tutorial sets it in the same place,
	// before any SDK work; the ordering only becomes visible when something
	// initialises licensing explicitly (docs/adr/0123).
	NLicenseManager::SetTrialMode(trialMode);

	// Required runtime initialisation, and not optional. Every delivered
	// tutorial performs it before touching the SDK, by way of the sample support
	// header; without it the licensing subsystem is never brought up.
	NCore::OnStart();

	int status;
	try
	{
		if (command == NString(N_T("diagnose")))
		{
			status = CommandDiagnose(trialMode);
		}
		else if (command == NString(N_T("settings")))
		{
			status = CommandSettings(trialMode);
		}
		else if (command == NString(N_T("extract")))
		{
			if (argc < 5) { NCore::OnExit(NFalse); return Usage(); }
			status = CommandExtract(trialMode, argv[3], argv[4]);
		}
		else if (command == NString(N_T("match")))
		{
			if (argc < 5) { NCore::OnExit(NFalse); return Usage(); }
			status = CommandMatch(trialMode, argv[3], argv[4]);
		}
		else if (command == NString(N_T("pair")))
		{
			if (argc < 5) { NCore::OnExit(NFalse); return Usage(); }
			status = CommandPair(trialMode, argv[3], argv[4]);
		}
		else if (command == NString(N_T("self")))
		{
			if (argc < 4) { NCore::OnExit(NFalse); return Usage(); }
			status = CommandSelf(trialMode, argv[3]);
		}
		else
		{
			NCore::OnExit(NFalse);
			return Usage();
		}
		NCore::OnExit(NFalse);
		return status;
	}
	catch (NError &error)
	{
		// A structured failure, never a pseudo-score. The exit status and the
		// message are what the driver records; nothing here invents a number to
		// keep the output shape regular.
		std::cerr << "error_code=" << error.GetCode() << "\n"
		          << "error=" << ToUtf8(error.ToString()) << std::endl;
		NCore::OnExit(NFalse);
		return 3;
	}
	catch (const std::exception &error)
	{
		std::cerr << "error=" << error.what() << std::endl;
		NCore::OnExit(NFalse);
		return 4;
	}
}
