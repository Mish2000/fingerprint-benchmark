# fpbench Stage 18A — OpenAFIS raw 1:1 bridge.
#
# Compiles the pinned OpenAFIS tree and this bridge into one binary. Nothing in
# here is fetched: FPBENCH_OPENAFIS_SOURCE must already point at a checkout of
#
#     neilharan/openafis @ 3ae1c757c6dafea977a33ef51380e37f1715e626
#
# which lives in the local artifact store outside this repository. No upstream
# byte is ever copied in here, and build/ is ignored.
#
# Usage:
#
#   make FPBENCH_OPENAFIS_SOURCE=/path/to/openafis
#
# WHY NOT UPSTREAM'S CMAKE
#
# Two reasons, both plumbing, and both recorded in the route contract:
#
#   -Werror     upstream pairs it with -Wall -Wextra -Wshadow -pedantic-errors.
#               A 2021 tree does not compile clean under gcc 13, and the stage is
#               execution-first: a warning is not a reason to have no scores.
#
#   -fno-exceptions
#               upstream disables exceptions, but delaunator-cpp throws on
#               degenerate minutiae. With exceptions off, one bad template aborts
#               the process and takes the other 5,999 comparisons with it. They
#               are enabled here so that a bad template is a recorded per-pair
#               status instead.
#
# Everything that could move a score is upstream's: -O3 -march=native
# -mtune=native -fstrict-aliasing and C++17, the same as upstream's non-MSVC
# branch. No -ffast-math anywhere (upstream sets /fp:fast on MSVC only, and this
# is a gcc build).

FPBENCH_OPENAFIS_SOURCE ?=

ifeq ($(strip $(FPBENCH_OPENAFIS_SOURCE)),)
$(error FPBENCH_OPENAFIS_SOURCE is not set. Point it at the pinned openafis checkout in the local artifact store)
endif

OPENAFIS_LIB      := $(FPBENCH_OPENAFIS_SOURCE)/lib
OPENAFIS_3RDPARTY := $(FPBENCH_OPENAFIS_SOURCE)/3rdparty

BUILD_DIR ?= build
TARGET    := $(BUILD_DIR)/fpbench_openafis_bridge

UPSTREAM_SOURCES := $(wildcard $(OPENAFIS_LIB)/*.cpp)
BRIDGE_SOURCES   := src/fpbench_openafis_bridge.cpp src/fpbench_openafis_csv_instantiation.cpp

CXX      ?= g++
CXXFLAGS ?= -std=c++17 -O3 -march=native -mtune=native -fstrict-aliasing -Wall -Wextra -Wno-deprecated
CPPFLAGS += -I$(OPENAFIS_LIB) -I$(OPENAFIS_3RDPARTY)
LDLIBS   += -lpthread

.PHONY: all clean print-config

all: $(TARGET)

$(TARGET): $(UPSTREAM_SOURCES) $(BRIDGE_SOURCES) | $(BUILD_DIR)
	@test -d "$(OPENAFIS_LIB)" || { echo "no upstream lib directory at $(OPENAFIS_LIB)"; exit 1; }
	@test -d "$(OPENAFIS_3RDPARTY)" || { echo "no upstream 3rdparty directory at $(OPENAFIS_3RDPARTY)"; exit 1; }
	$(CXX) $(CXXFLAGS) $(CPPFLAGS) $(UPSTREAM_SOURCES) $(BRIDGE_SOURCES) -o $@ $(LDLIBS)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

# Reports where the build would look. Prints paths and touches nothing.
print-config:
	@echo "source     $(FPBENCH_OPENAFIS_SOURCE)"
	@echo "lib        $(OPENAFIS_LIB)"
	@echo "3rdparty   $(OPENAFIS_3RDPARTY)"
	@echo "target     $(TARGET)"
	@echo "cxx        $(CXX)"
	@echo "cxxflags   $(CXXFLAGS)"

clean:
	rm -rf $(BUILD_DIR)
