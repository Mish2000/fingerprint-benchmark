// fpbench Stage 18A — OpenAFIS raw 1:1 similarity bridge.
//
// The smallest program that turns two minutiae template files into one raw
// OpenAFIS similarity score. It is not an adapter: it produces no ResultSet,
// applies no threshold, makes no decision, and knows nothing about the
// benchmark's protocol beyond which side of a pair is the probe.
//
// WHAT IT IS A TRANSCRIPTION OF
//
// The upstream README publishes the 1:1 usage verbatim, and this file follows it
// without addition:
//
//     TemplateISO19794_2_2005<uint32_t, Fingerprint> t1(1);
//     if (!t1.load("./fvc2002/DB1_B/101_1.iso")) { /* Load error */ }
//     TemplateISO19794_2_2005<uint32_t, Fingerprint> t2(2);
//     if (!t2.load("./fvc2002/DB1_B/101_2.iso")) { /* Load error */ }
//     MatchSimilarity match;
//     uint8_t s {};
//     match.compute(s, t1.fingerprints()[0], t2.fingerprints()[0]);
//
// The only deliberate difference is the id type: `std::string`, so a score line
// can carry the pair id it belongs to. Both instantiations are explicit in
// upstream's own TemplateISO19794_2_2005.cpp, so this is a choice between two
// shipped types and not a new one.
//
// THE SCORE IS NOT COMPUTED HERE
//
// Upstream's Match.cpp computes it, and this bridge never touches the number:
//
//     result = (uint8_t)((maxMatched * maxMatched * 100)
//                        / (probe.minutiaeCount() * candidate.minutiaeCount()))
//
// assigned only when `maxMatched > Param::MinimumMinutiae` (4). When too little
// structure pairs up, `result` keeps its initial 0 — so **0 is a valid raw score
// and never a failure**. There is no transformation, no scaling, no clamping and
// no threshold anywhere below.
//
// NO TEMPLATE CACHE
//
// Every comparison loads both sides fresh from disk, exactly as the README
// example does. Parsing is a pure function of the file bytes, so a cache would
// be sound — but it would also be a question to answer later, and the parse is
// cheap. What Stage 18A caches is the *extractor's* output on disk (3,000 .iso
// files), which is a different thing and happens before this program runs.
//
// SUBCOMMANDS
//
//   identity                 report the build's instruction set and limits
//   match <left> <right>     one pair -> one line
//   batch                    stdin `id \t left \t right` -> one line each
//
// Output is tab-separated on stdout, one line per comparison:
//
//   <id> <status> <score> <load_left_us> <load_right_us> <match_us>
//
// `score` is the raw integer on OK and -1 on every other status, so a failure can
// never be read as a number. Errors go to stderr; a per-pair failure is a status,
// not an exit code, because the run must not stop for one bad template.

#include <chrono>
#include <cstdint>
#include <exception>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "OpenAFIS.h"

using namespace OpenAFIS;

namespace {

using IsoTemplate = TemplateISO19794_2_2005<std::string, Fingerprint>;
using CsvTemplate = TemplateCSV<std::string, Fingerprint>;

using Clock = std::chrono::steady_clock;

[[nodiscard]] long long micros_since(const Clock::time_point start)
{
    return std::chrono::duration_cast<std::chrono::microseconds>(Clock::now() - start).count();
}

enum class Format { Iso, Csv };

// One side of a comparison, loaded and timed. `ok` distinguishes "the parser
// refused the file" from "the parser accepted it but produced no fingerprint" —
// upstream indexes fingerprints()[0] unguarded, and an empty vector there is
// undefined behaviour rather than a score.
struct LoadedSide {
    bool ok {};
    bool has_fingerprint {};
    long long micros {};
};

template <class TemplateType> LoadedSide load_side(TemplateType& t, const std::string& path)
{
    LoadedSide side;
    const auto start = Clock::now();
    bool loaded = false;
    try {
        loaded = t.load(path);
    } catch (const std::exception&) {
        // delaunator throws when the minutiae are degenerate (collinear, or too
        // few to triangulate). Upstream builds with -fno-exceptions and lets that
        // terminate; here it is a per-pair load failure so the other 5,999 pairs
        // still run.
        loaded = false;
    }
    side.micros = micros_since(start);
    side.ok = loaded;
    side.has_fingerprint = loaded && !t.fingerprints().empty();
    return side;
}

struct Outcome {
    std::string status;
    int score { -1 };
    long long load_left_us {};
    long long load_right_us {};
    long long match_us {};
};

template <class TemplateType> Outcome compare(const std::string& left_path, const std::string& right_path)
{
    Outcome outcome;

    TemplateType left("left");
    const auto left_side = load_side(left, left_path);
    outcome.load_left_us = left_side.micros;

    TemplateType right("right");
    const auto right_side = load_side(right, right_path);
    outcome.load_right_us = right_side.micros;

    const auto left_usable = left_side.ok && left_side.has_fingerprint;
    const auto right_usable = right_side.ok && right_side.has_fingerprint;

    if (!left_usable && !right_usable) {
        outcome.status = "LOAD_FAILED_BOTH";
        return outcome;
    }
    if (!left_usable) {
        outcome.status = left_side.ok ? "NO_FINGERPRINT_LEFT" : "LOAD_FAILED_LEFT";
        return outcome;
    }
    if (!right_usable) {
        outcome.status = right_side.ok ? "NO_FINGERPRINT_RIGHT" : "LOAD_FAILED_RIGHT";
        return outcome;
    }

    // left -> probe, right -> candidate. Frozen, and never swapped or symmetrised.
    uint8_t score {};
    const auto start = Clock::now();
    try {
        MatchSimilarity matcher;
        matcher.compute(score, left.fingerprints()[0], right.fingerprints()[0]);
    } catch (const std::exception&) {
        outcome.match_us = micros_since(start);
        outcome.status = "MATCH_EXCEPTION";
        return outcome;
    }
    outcome.match_us = micros_since(start);
    outcome.status = "OK";
    outcome.score = static_cast<int>(score);
    return outcome;
}

Outcome compare_with(const Format format, const std::string& left_path, const std::string& right_path)
{
    return format == Format::Iso ? compare<IsoTemplate>(left_path, right_path) : compare<CsvTemplate>(left_path, right_path);
}

void emit(const std::string& id, const Outcome& outcome)
{
    std::cout << id << '\t' << outcome.status << '\t' << outcome.score << '\t' << outcome.load_left_us << '\t' << outcome.load_right_us << '\t'
              << outcome.match_us << '\n';
}

int run_identity()
{
    std::cout << "openafis_instruction_set\t" << InstructionSet << '\n';
    std::cout << "score_native_type\tuint8_t\n";
    std::cout << "score_direction\tHIGHER_MORE_SIMILAR\n";
    std::cout << "score_transform\tNONE\n";
    std::cout << "threshold\tNONE\n";
    std::cout << "param_minimum_minutiae\t" << Param::MinimumMinutiae << '\n';
    std::cout << "param_maximum_rotations\t" << Param::MaximumRotations << '\n';
    std::cout << "param_maximum_local_distance\t" << static_cast<int>(Param::MaximumLocalDistance) << '\n';
    std::cout << "param_maximum_global_distance\t" << static_cast<int>(Param::MaximumGlobalDistance) << '\n';
    std::cout << "iso_minimum_length\t" << IsoTemplate::MinimumLength << '\n';
    std::cout << "iso_maximum_length\t" << IsoTemplate::MaximumLength << '\n';
    return 0;
}

int run_batch(const Format format)
{
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) {
            continue;
        }
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        std::istringstream fields(line);
        std::string id;
        std::string left_path;
        std::string right_path;
        if (!std::getline(fields, id, '\t') || !std::getline(fields, left_path, '\t') || !std::getline(fields, right_path, '\t')) {
            std::cerr << "malformed batch line: " << line << '\n';
            return 2;
        }
        emit(id, compare_with(format, left_path, right_path));
        std::cout.flush();
    }
    return 0;
}

Format parse_format(const std::vector<std::string>& args)
{
    for (size_t i = 0; i + 1 < args.size(); i++) {
        if (args[i] == "--format") {
            if (args[i + 1] == "csv") {
                return Format::Csv;
            }
        }
    }
    return Format::Iso;
}

void usage()
{
    std::cerr << "usage:\n"
                 "  fpbench_openafis_bridge identity\n"
                 "  fpbench_openafis_bridge match <left> <right> [--format iso|csv]\n"
                 "  fpbench_openafis_bridge batch [--format iso|csv]   # stdin: id\\tleft\\tright\n";
}

}

int main(int argc, const char** argv)
{
    const std::vector<std::string> args(argv + 1, argv + argc);
    if (args.empty()) {
        usage();
        return 2;
    }
    const auto& command = args[0];

    if (command == "identity") {
        return run_identity();
    }
    if (command == "batch") {
        return run_batch(parse_format(args));
    }
    if (command == "match") {
        if (args.size() < 3) {
            usage();
            return 2;
        }
        emit("match", compare_with(parse_format(args), args[1], args[2]));
        return 0;
    }
    usage();
    return 2;
}
