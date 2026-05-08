#include <cassert>

#include "selfdrive/pandad/pandad.h"
#include "common/swaglog.h"
#include "common/util.h"
#include "system/hardware/hw.h"

int main(int argc, char *argv[]) {
  LOGW("starting pandad");

  if (!Hardware::PC()) {
    int err;
    err = util::set_realtime_priority(54);
    assert(err == 0);
    err = util::set_core_affinity({3});
    assert(err == 0);
  }

  std::string serial = (argc > 1) ? argv[1] : "";
  int panda_index = (argc > 2) ? std::stoi(argv[2]) : 0;
  pandad_main_thread(serial, panda_index);
  return 0;
}
