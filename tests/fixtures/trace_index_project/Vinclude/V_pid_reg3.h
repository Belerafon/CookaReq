#ifndef V_PID_REG3_H
#define V_PID_REG3_H

#include <stdint.h>

typedef struct {
        int32_t uprsat_reg3;
        int32_t up1_reg3;
        int32_t DiffCounter;
        int32_t KdFilterInitFlag;
        int32_t e_reg3Dz;
} TPidReg3Internal;

typedef struct {
        int32_t pid_ref_reg3;
        int32_t pid_fdb_reg3;
        int32_t e_reg3;
        int32_t up_reg3;
        int32_t ui_reg3;
        int32_t ud_reg3;
        int32_t pid_out_reg3;
        int32_t saterr_reg3;
        int32_t saterr_reg3Add;
        int32_t e_reg3_filterOut;
        int32_t DeadZone;
        int32_t Kp_reg3;
        int32_t Ki_reg3;
        int32_t Kd_reg3;
        int32_t Kc_reg3;
        int32_t Kf_d;
        int32_t DiffDelim;
        int32_t pid_out_min;
        int32_t pid_out_max;
        TPidReg3Internal internal;
} TPidReg3;

void pid_reg3_calc(TPidReg3 *v);
void pid_reg3_reset(TPidReg3 *v);

#endif
