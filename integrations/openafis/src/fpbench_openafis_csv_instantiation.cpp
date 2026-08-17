// fpbench Stage 18A — the one link-level gap in upstream's CSV reader.
//
// TemplateCSV is a class template whose only definition lives in
// lib/TemplateCSV.cpp, and that file explicitly instantiates *nothing*. Every
// other template in the library ends with a block of `template class ...` lines;
// TemplateCSV does not, because upstream calls it "used for debug only" and its
// own CLI never reaches it. So `TemplateCSV<std::string, Fingerprint>::load`
// exists as source and not as a symbol, and any caller fails at link time.
//
// This translation unit supplies the missing instantiation and nothing else. It
// adds no code path, reads no file, and changes no parsing rule — upstream's
// reader is compiled exactly as written. It exists so that Stage 18A's fallback C
// (a format-only bridge from extractor minutiae into OpenAFIS CSV) can be reached
// without editing a single byte of the pinned tree.
//
// The CSV layout upstream defines, for the record:
//
//     line 1:      width,height
//     each minutia: type,x,y,angle_in_radians

#include "TemplateCSV.cpp"

namespace OpenAFIS
{
template class TemplateCSV<std::string, Fingerprint>;
}
