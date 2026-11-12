// SPDX-License-Identifier: GPL-3.0-or-later
#include <windows.h>

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

#include "nxrt/config.h"
#include "nxrt/ftrace.h"
#include "test_framework.h"

NXTEST_GROUP(ftrace)

NXTEST(capture_window_excludes_loading_and_events_after_end) {
    char temp[MAX_PATH] = {};
    GetTempPathA(sizeof temp, temp);
    const std::string path = std::string(temp) + "nxrt_trace_window_" + std::to_string(GetCurrentProcessId()) + ".trace";
    nxrt::config_set("prof", "trace", path.c_str());
    nxrt::config_set("prof", "trace_events", "64");
    nxrt::config_set("prof", "delay_sec", "10");
    nxrt::config_set("prof", "duration_sec", "10");
    nxrt::config_set("prof", "stall_ms", "0");
    const uint64_t before = nxrt::ft::now_ns();
    nxrt::ft::start_from_config();
    const uint64_t after = nxrt::ft::now_ns();
    const bool recording_during_delay = nxrt::ft::recording();
    const uint16_t zone = nxrt::ft::zone_id("test.window");
    // Synthetic timestamps exercise the window without a twenty-second sleep.
    // Choose the inside point relative to the return from start_from_config;
    // the assertion below checks that setup took less than the available slack.
    nxrt::ft::event(zone, before, before + 1, 1);
    nxrt::ft::event(zone, after + 15'000'000'000ull, after + 15'000'000'100ull, 2);
    nxrt::ft::event(zone, after + 25'000'000'000ull, after + 25'000'000'100ull, 3);
    nxrt::ft::stop();
    std::ifstream input(path);
    int events = 0;
    uint32_t last_arg = 0;
    for (std::string line; std::getline(input, line);) {
        if (line.empty() || line[0] == '#') continue;
        uint64_t t = 0, duration = 0;
        uint32_t thread = 0, id = 0;
        std::istringstream row(line);
        if (row >> t >> duration >> thread >> id >> last_arg) ++events;
    }
    input.close();
    std::remove(path.c_str());
    nxrt::config_set("prof", "trace", "");
    nxrt::config_set("prof", "delay_sec", "0");
    nxrt::config_set("prof", "duration_sec", "0");
    CHECK(after - before < 5'000'000'000ull);
    CHECK(!recording_during_delay);
    CHECK_EQ(events, 1);
    CHECK_EQ(last_arg, 2u);
    CHECK(!nxrt::ft::on());
}
