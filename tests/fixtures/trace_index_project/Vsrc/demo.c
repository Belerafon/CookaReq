#include "demo.h"

int demo_step(int value) {
    /* @covers LLR1, LLR2: clamp and diagnostics */
    if (value > 100) {
        return 100;
    }
    return value;
}
