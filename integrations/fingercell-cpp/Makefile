# fpbench Stage 13A — FingerCell qualification bridge.
#
# This makefile compiles and links. It does not run anything.
#
# There is deliberately no `check`, no smoke target, no post-build execution and
# no test that loads a vendor module. Building must not obtain a licence, because
# obtaining one starts a 30-day clock that should not be spent on compiler errors
# (docs/adr/0115). The only thing `make` proves here is that the route builds
# against the delivered headers and libraries.
#
# The library list is not invented: it is exactly what the delivered tutorial
# build files name for the official 1:1 route.
#
#   Tutorials/FingerCell/CPP/FCVerifyFingerCPP/Makefile
#       LDLIBS ?= -lFingerCell -lNMedia -lNCore -lNLicensing
#
# Usage:
#
#   make FPBENCH_FINGERCELL_SDK=/path/to/FingerCell_3_3_SDK
#
# or export FPBENCH_FINGERCELL_SDK first. The SDK lives in the local artifact
# store, outside this repository, and no vendor byte is ever copied in here.

FPBENCH_FINGERCELL_SDK ?=

ifeq ($(strip $(FPBENCH_FINGERCELL_SDK)),)
$(error FPBENCH_FINGERCELL_SDK is not set. Point it at the unpacked FingerCell_3_3_SDK directory in the local artifact store)
endif

# The platform layout the bridge is built against. Overridable, because the
# archive ships several and the one in use is a property of this build rather
# than a project-wide constant.
ARCH_DIR ?= Linux_x86_64

SDK_INCLUDE := $(FPBENCH_FINGERCELL_SDK)/Include
SDK_LIB     := $(FPBENCH_FINGERCELL_SDK)/Lib/$(ARCH_DIR)
SDK_BIN     := $(FPBENCH_FINGERCELL_SDK)/Bin/$(ARCH_DIR)

BUILD_DIR   ?= build
TARGET      := $(BUILD_DIR)/fpbench_fingercell_bridge
SOURCES     := src/fpbench_fingercell_bridge.cpp

CXX      ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter
CPPFLAGS += -I$(SDK_INCLUDE)

# The vendor libraries live outside this tree and are not copied into it, so the
# link records where they are and the loader is told the same.
LDFLAGS  += -L$(SDK_LIB) -Wl,-rpath,$(SDK_LIB)
LDLIBS   += -lFingerCell -lNMedia -lNCore -lNLicensing

.PHONY: all clean print-config

all: $(TARGET)

$(TARGET): $(SOURCES) | $(BUILD_DIR)
	@test -d "$(SDK_INCLUDE)" || { echo "no delivered Include directory at $(SDK_INCLUDE)"; exit 1; }
	@test -d "$(SDK_LIB)" || { echo "no delivered Lib directory at $(SDK_LIB)"; exit 1; }
	$(CXX) $(CXXFLAGS) $(CPPFLAGS) $(SOURCES) -o $@ $(LDFLAGS) $(LDLIBS)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

# Reports where the build would look. Prints paths and touches nothing; it does
# not load a module and does not ask for a licence.
print-config:
	@echo "sdk      $(FPBENCH_FINGERCELL_SDK)"
	@echo "arch     $(ARCH_DIR)"
	@echo "include  $(SDK_INCLUDE)"
	@echo "lib      $(SDK_LIB)"
	@echo "bin      $(SDK_BIN)"
	@echo "target   $(TARGET)"
	@echo "libs     $(LDLIBS)"

clean:
	rm -rf $(BUILD_DIR)
