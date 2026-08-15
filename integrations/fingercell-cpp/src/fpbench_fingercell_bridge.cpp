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

#include <iostream>
#include <string>
#include <vector>

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
bool ObtainLicense(bool trialMode)
{
	NLicenseManager::SetTrialMode(trialMode);
	Emit("trial_mode", NLicenseManager::GetTrialMode() ? "true" : "false");
	if (!NLicense::Obtain(kLicenseServer, kLicensePort, kLicenseComponent))
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

// Report every property the engine exposes, before anything has been set.
//
// This uses the SDK's own property capture rather than a list written in
// advance: the typed accessors cover three settings and the documented surface
// is wider, so a closure built from the header alone would be incomplete. What
// it reports is what upstream makes externally selectable — not implementation
// internals (docs/adr/0118, docs/adr/0120).
int CommandSettings(bool trialMode)
{
	if (!ObtainLicense(trialMode)) return 2;

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
	if (!ObtainLicense(trialMode)) return 2;

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
	if (!ObtainLicense(trialMode)) return 2;

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
	if (!ObtainLicense(trialMode)) return 2;

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
	if (!ObtainLicense(trialMode)) return 2;

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

	try
	{
		if (command == NString(N_T("settings")))
		{
			return CommandSettings(trialMode);
		}
		if (command == NString(N_T("extract")))
		{
			if (argc < 5) return Usage();
			return CommandExtract(trialMode, argv[3], argv[4]);
		}
		if (command == NString(N_T("match")))
		{
			if (argc < 5) return Usage();
			return CommandMatch(trialMode, argv[3], argv[4]);
		}
		if (command == NString(N_T("pair")))
		{
			if (argc < 5) return Usage();
			return CommandPair(trialMode, argv[3], argv[4]);
		}
		if (command == NString(N_T("self")))
		{
			if (argc < 4) return Usage();
			return CommandSelf(trialMode, argv[3]);
		}
		return Usage();
	}
	catch (NError &error)
	{
		// A structured failure, never a pseudo-score. The exit status and the
		// message are what the driver records; nothing here invents a number to
		// keep the output shape regular.
		std::cerr << "error_code=" << error.GetCode() << "\n"
		          << "error=" << ToUtf8(error.ToString()) << std::endl;
		return 3;
	}
	catch (const std::exception &error)
	{
		std::cerr << "error=" << error.what() << std::endl;
		return 4;
	}
}
